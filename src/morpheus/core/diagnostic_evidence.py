"""Bounded redacted diagnostic evidence packages (AID-001).

Pure, dependency-free assembly of a diagnostic evidence package from
structured health, machine profile, deployment manifest, metrics, events,
selected log excerpts, benchmark regressions, and known runbook
references. Every section is size-bounded, secret-shaped content is
redacted, canary values are removed, and provenance records the product
version, source commit, and observation time. Nothing in the package can
inject sections, runbook references, or unchecked paths.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from morpheus.core.events import redact_text, sanitize_message
from morpheus.core.redaction import REDACTED, redact
from morpheus.core.runbooks import known_runbook_reference

DIAGNOSTIC_SCHEMA_VERSION = 1
SECTION_ORDER = (
    "health",
    "machine_profile",
    "deployment",
    "metrics",
    "events",
    "log_excerpts",
    "regressions",
    "runbooks",
)
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class DiagnosticEvidenceError(ValueError):
    """An evidence section is unbounded, redacted, or injected."""


@dataclass(frozen=True, slots=True)
class EvidenceLimits:
    max_events: int = 200
    max_metric_buckets: int = 240
    max_excerpts: int = 8
    max_excerpt_bytes: int = 64 * 1024
    max_runbooks: int = 16
    max_total_bytes: int = 2 * 1024 * 1024


DEFAULT_EVIDENCE_LIMITS = EvidenceLimits()


@dataclass(frozen=True, slots=True)
class DiagnosticProvenance:
    morpheus_version: str
    source_commit: str
    observed_at: str

    def to_json(self) -> dict[str, str]:
        return {
            "morpheus_version": self.morpheus_version,
            "source_commit": self.source_commit,
            "observed_at": self.observed_at,
        }


@dataclass(frozen=True, slots=True)
class DiagnosticEvidence:
    health: Mapping[str, Any]
    machine_profile: Mapping[str, Any]
    deployment: Mapping[str, Any]
    metrics: Mapping[str, Any]
    events: tuple[Mapping[str, Any], ...]
    log_excerpts: tuple[tuple[str, str], ...]
    regressions: tuple[Mapping[str, Any], ...]
    runbooks: tuple[str, ...]
    provenance: DiagnosticProvenance

    @property
    def sections(self) -> tuple[str, ...]:
        return SECTION_ORDER

    def manifest(self) -> dict[str, Any]:
        """Provenance, per-section digests, and the bounded section list."""
        digests = {
            name: _digest(json.dumps(getattr(self, name), sort_keys=True)) for name in SECTION_ORDER
        }
        return {
            "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
            "sections": list(SECTION_ORDER),
            "digests": digests,
            "provenance": self.provenance.to_json(),
        }


def build_diagnostic_evidence(
    *,
    health: Mapping[str, Any],
    machine_profile: Mapping[str, Any],
    deployment: Mapping[str, Any],
    metrics: Mapping[str, Any],
    events: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    log_excerpts: list[tuple[str, str]] | tuple[tuple[str, str], ...],
    regressions: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    runbooks: list[str] | tuple[str, ...],
    provenance: DiagnosticProvenance,
    canaries: Mapping[str, str] | None = None,
    limits: EvidenceLimits = DEFAULT_EVIDENCE_LIMITS,
) -> DiagnosticEvidence:
    """Assemble a bounded, redacted diagnostic evidence package.

    Sections are redacted recursively (secret-shaped keys and prompt/
    response content become ``[REDACTED]``), excerpts are sanitized and
    truncated, canary values are removed, runbook references must resolve
    against the known registry, and every bound violation raises
    :class:`DiagnosticEvidenceError`.
    """
    if len(events) > limits.max_events:
        raise DiagnosticEvidenceError(f"too many events: {len(events)} > {limits.max_events}")
    if len(log_excerpts) > limits.max_excerpts:
        raise DiagnosticEvidenceError(
            f"too many log excerpts: {len(log_excerpts)} > {limits.max_excerpts}"
        )
    if len(runbooks) > limits.max_runbooks:
        raise DiagnosticEvidenceError(
            f"too many runbook references: {len(runbooks)} > {limits.max_runbooks}"
        )
    _bound_metric_buckets(metrics, limits)

    redacted_events = tuple(redact(_sanitize_event(event, canaries)) for event in events)
    excerpts = tuple(
        (name, _bounded_excerpt(text, limits, canaries)) for name, text in log_excerpts
    )
    try:
        references = tuple(known_runbook_reference(identifier).id for identifier in runbooks)
    except ValueError as error:
        raise DiagnosticEvidenceError(f"invalid runbook reference: {error}") from error
    evidence = DiagnosticEvidence(
        health=redact(dict(health)),
        machine_profile=redact(dict(machine_profile)),
        deployment=redact(dict(deployment)),
        metrics=redact(dict(metrics)),
        events=redacted_events,
        log_excerpts=excerpts,
        regressions=tuple(redact(regression) for regression in regressions),
        runbooks=references,
        provenance=provenance,
    )
    if _total_bytes(evidence) > limits.max_total_bytes:
        raise DiagnosticEvidenceError(
            f"evidence package exceeds the total size bound: "
            f"{_total_bytes(evidence)} > {limits.max_total_bytes}"
        )
    return evidence


def _sanitize_event(
    event: Mapping[str, Any], canaries: Mapping[str, str] | None
) -> Mapping[str, Any]:
    if "message" in event and isinstance(event["message"], str):
        message = sanitize_message(redact_text(event["message"]))
        if canaries:
            for canary in canaries.values():
                message = message.replace(canary, REDACTED)
        return {**event, "message": message}
    return event


def _bounded_excerpt(text: str, limits: EvidenceLimits, canaries: Mapping[str, str] | None) -> str:
    redacted = sanitize_message(redact_text(text))
    if canaries:
        for canary in canaries.values():
            redacted = redacted.replace(canary, REDACTED)
    encoded = redacted.encode("utf-8")
    if len(encoded) > limits.max_excerpt_bytes:
        redacted = encoded[: limits.max_excerpt_bytes - 3].decode("utf-8", errors="ignore") + "..."
    return redacted


def _bound_metric_buckets(metrics: Mapping[str, Any], limits: EvidenceLimits) -> None:
    for signal, buckets in metrics.items():
        if isinstance(buckets, list | tuple) and len(buckets) > limits.max_metric_buckets:
            raise DiagnosticEvidenceError(
                f"too many metric buckets for {signal}: "
                f"{len(buckets)} > {limits.max_metric_buckets}"
            )


def _total_bytes(evidence: DiagnosticEvidence) -> int:
    return len(json.dumps(evidence.manifest(), sort_keys=True).encode("utf-8")) + sum(
        len(json.dumps(getattr(evidence, section), sort_keys=True).encode("utf-8"))
        for section in SECTION_ORDER
    )


def _digest(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    assert _DIGEST.fullmatch(digest)
    return digest
