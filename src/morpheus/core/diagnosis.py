"""Grounded AI-assisted diagnosis core (AID-002/003/004).

Pure, dependency-free handling of provider output for Morpheus
diagnostics: a strict structured parser that can never turn model output
into an executable operation, deterministic grounding evaluation that
labels every material claim, and typed advisory proposals that reference
known runbooks or ordinary typed Morpheus policy plans only. No secret,
prompt, or response content is ever modeled here; provider selection and
transport live behind typed adapters.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from morpheus.core.diagnostic_evidence import (
    SECTION_ORDER,
    DiagnosticEvidence,
)
from morpheus.core.runbooks import known_runbook_reference

GROUNDING_CONFIDENCE_THRESHOLD = 0.7
PLAN_KINDS = ("install", "repair", "update", "rollback")
_CITATION_TYPES = ("evidence", "runbook")
_FINDING_KINDS = ("observation", "inference")
_PROPOSAL_TYPES = ("runbook", "policy_plan")


class DiagnosisMode(str, Enum):
    DISABLED = "disabled"
    LOCAL = "local"
    EXTERNAL = "external"


class DiagnosisError(Exception):
    """A provider, consent, cost, or grounding failure."""


class ProviderTimeoutError(DiagnosisError):
    """The provider did not answer within the configured timeout."""


class MalformedOutputError(DiagnosisError):
    """Provider output did not match the structured findings schema."""


class ProviderRefusalError(DiagnosisError):
    """The provider refused to answer."""


class ConsentRequiredError(DiagnosisError):
    """Evidence cannot leave the host without explicit consent."""


class CostExceededError(DiagnosisError):
    """The request would exceed the configured cost budget."""


class InjectionDetectedError(DiagnosisError):
    """Provider output cited unknown evidence or proposed an unsafe action."""


class ProviderUnavailableError(DiagnosisError):
    """The configured provider could not be reached or used."""


class ConfidenceOutOfRangeError(MalformedOutputError):
    """A finding confidence is outside the unit interval."""


@dataclass(frozen=True, slots=True)
class DiagnosisConfig:
    mode: DiagnosisMode
    provider_name: str
    timeout_ms: int = 30_000
    max_cost: int = 0
    cost_per_1k_tokens: float = 0.0
    retention: str = "none"
    data_destination: str = "none"
    endpoint: str = ""
    consent_required: bool = True
    consent_granted: bool = False
    canaries: Mapping[str, str] = field(default_factory=dict)

    def capabilities(self) -> dict[str, Any]:
        """Non-secret provider capabilities shown before evidence leaves the host."""
        return {
            "mode": self.mode.value,
            "provider_name": self.provider_name,
            "data_destination": self.data_destination,
            "retention": self.retention,
            "timeout_ms": self.timeout_ms,
            "max_cost": self.max_cost,
            "consent_required": self.consent_required,
            "consent_granted": self.consent_granted,
        }


@dataclass(frozen=True, slots=True)
class Citation:
    kind: str
    section: str | None = None
    index: int | None = None
    runbook: str | None = None

    def to_json(self) -> dict[str, Any]:
        if self.kind == "runbook":
            return {"type": "runbook", "id": self.runbook}
        return {"type": "evidence", "section": self.section, "index": self.index}


@dataclass(frozen=True, slots=True)
class Finding:
    kind: str
    text: str
    confidence: float
    citations: tuple[Citation, ...] = ()
    missing_evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProposedCheck:
    type: str
    id: str | None = None
    kind: str | None = None

    def to_json(self) -> dict[str, Any]:
        if self.type == "runbook":
            return {"type": "runbook", "id": self.id}
        return {"type": "policy_plan", "kind": self.kind}


@dataclass(frozen=True, slots=True)
class GroundedDiagnosis:
    summary: str
    findings: tuple[Finding, ...] = ()
    likely_causes: tuple[str, ...] = ()
    proposed_checks: tuple[ProposedCheck, ...] = ()
    missing_evidence: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "findings": [
                {
                    "kind": finding.kind,
                    "text": finding.text,
                    "confidence": finding.confidence,
                    "citations": [citation.to_json() for citation in finding.citations],
                    "missing_evidence": list(finding.missing_evidence),
                }
                for finding in self.findings
            ],
            "likely_causes": list(self.likely_causes),
            "proposed_checks": [check.to_json() for check in self.proposed_checks],
            "missing_evidence": list(self.missing_evidence),
        }


@dataclass(frozen=True, slots=True)
class DiagnosisOutcome:
    """Result of a diagnosis run; provider failure is never an exception."""

    status: str
    diagnosis: GroundedDiagnosis | None = None
    grounding: dict[str, str] | None = None
    reason: str | None = None

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status}
        if self.diagnosis is not None:
            payload["diagnosis"] = self.diagnosis.to_json()
        if self.grounding is not None:
            payload["grounding"] = self.grounding
        if self.reason is not None:
            payload["reason"] = self.reason
        return payload


def parse_grounded_diagnosis(raw: str | Mapping[str, Any]) -> GroundedDiagnosis:
    """Strictly parse structured provider output into a grounded diagnosis.

    Any unrecognized field, citation, or proposal type raises
    :class:`MalformedOutputError` or :class:`InjectionDetectedError`; the
    parser never interprets free text as an operation.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise MalformedOutputError("provider output is not valid JSON") from error
    if not isinstance(raw, Mapping):
        raise MalformedOutputError("provider output must be a JSON object")
    if not isinstance(raw.get("summary"), str) or not raw["summary"]:
        raise MalformedOutputError("provider output is missing a summary")

    findings: list[Finding] = []
    raw_findings = raw.get("findings", [])
    if not isinstance(raw_findings, list):
        raise MalformedOutputError("provider output findings must be a list")
    for raw_finding in raw_findings:
        findings.append(_parse_finding(raw_finding))

    likely_causes = _parse_string_list(raw.get("likely_causes", []), "likely_causes")
    missing_evidence = _parse_string_list(raw.get("missing_evidence", []), "missing_evidence")
    proposed_checks = _parse_proposed_checks(raw.get("proposed_checks", []))

    return GroundedDiagnosis(
        summary=raw["summary"],
        findings=tuple(findings),
        likely_causes=likely_causes,
        proposed_checks=proposed_checks,
        missing_evidence=missing_evidence,
    )


def evaluate_grounding(
    diagnosis: GroundedDiagnosis, evidence: DiagnosticEvidence
) -> dict[Finding, str]:
    """Deterministically label every finding grounded or unsupported.

    A finding with confidence at or above the threshold must cite an
    existing evidence item or known runbook; anything else is labeled
    unsupported. Citations beyond the evidence bounds are an injection
    attempt and raise :class:`InjectionDetectedError`.
    """
    section_lengths = {section: _section_length(evidence, section) for section in SECTION_ORDER}
    verdicts: dict[Finding, str] = {}
    for finding in diagnosis.findings:
        if finding.confidence >= GROUNDING_CONFIDENCE_THRESHOLD:
            if not finding.citations:
                verdicts[finding] = "unsupported"
                continue
            for citation in finding.citations:
                if citation.kind == "runbook":
                    continue
                if citation.section not in section_lengths:
                    raise InjectionDetectedError(
                        f"citation references unknown evidence section {citation.section!r}"
                    )
                if (
                    citation.index is None
                    or not 0 <= citation.index < section_lengths[citation.section]
                ):
                    raise InjectionDetectedError(
                        f"citation index {citation.index} out of bounds for {citation.section}"
                    )
            verdicts[finding] = "grounded"
        else:
            verdicts[finding] = "unsupported"
    return verdicts


def reject_unsafe_proposals(diagnosis: GroundedDiagnosis) -> tuple[ProposedCheck, ...]:
    """Return the typed advisory proposals; free-form actions never parse."""
    return diagnosis.proposed_checks


def _parse_finding(raw: Any) -> Finding:
    if not isinstance(raw, Mapping):
        raise MalformedOutputError("each finding must be an object")
    kind = raw.get("kind")
    if kind not in _FINDING_KINDS:
        raise MalformedOutputError(f"unknown finding kind {kind!r}")
    text = raw.get("text")
    if not isinstance(text, str) or not text:
        raise MalformedOutputError("finding is missing text")
    confidence = raw.get("confidence")
    if not isinstance(confidence, int | float) or isinstance(confidence, bool):
        raise MalformedOutputError("finding is missing a numeric confidence")
    if not 0.0 <= confidence <= 1.0:
        raise ConfidenceOutOfRangeError(f"finding confidence {confidence} is outside 0..1")

    citations: list[Citation] = []
    raw_citations = raw.get("citations", [])
    if not isinstance(raw_citations, list):
        raise MalformedOutputError("finding citations must be a list")
    for raw_citation in raw_citations:
        citations.append(_parse_citation(raw_citation))
    missing = _parse_string_list(raw.get("missing_evidence", []), "finding missing_evidence")
    return Finding(
        kind=kind,
        text=text,
        confidence=float(confidence),
        citations=tuple(citations),
        missing_evidence=missing,
    )


def _parse_citation(raw: Any) -> Citation:
    if not isinstance(raw, Mapping):
        raise MalformedOutputError("each citation must be an object")
    citation_type = raw.get("type")
    if citation_type not in _CITATION_TYPES:
        raise InjectionDetectedError(f"unknown citation type {citation_type!r}")
    if citation_type == "runbook":
        runbook = raw.get("id")
        if not _known_runbook(runbook):
            raise InjectionDetectedError(f"unknown runbook citation {runbook!r}")
        return Citation(kind="runbook", runbook=runbook)
    section = raw.get("section")
    index = raw.get("index")
    if section not in SECTION_ORDER:
        raise InjectionDetectedError(f"unknown evidence section {section!r}")
    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        raise MalformedOutputError("evidence citation needs a non-negative index")
    return Citation(kind="evidence", section=section, index=index)


def _parse_proposed_checks(raw: Any) -> tuple[ProposedCheck, ...]:
    if not isinstance(raw, list):
        raise MalformedOutputError("proposed checks must be a list")
    checks: list[ProposedCheck] = []
    for raw_check in raw:
        if not isinstance(raw_check, Mapping):
            raise MalformedOutputError("each proposed check must be an object")
        check_type = raw_check.get("type")
        if check_type not in _PROPOSAL_TYPES:
            raise InjectionDetectedError(f"unsafe proposal type {check_type!r}")
        if check_type == "runbook":
            runbook = raw_check.get("id")
            if not _known_runbook(runbook):
                raise InjectionDetectedError(f"unknown runbook proposal {runbook!r}")
            checks.append(ProposedCheck(type="runbook", id=runbook))
            continue
        kind = raw_check.get("kind")
        if kind not in PLAN_KINDS:
            raise InjectionDetectedError(f"unsafe policy plan kind {kind!r}")
        checks.append(ProposedCheck(type="policy_plan", kind=kind))
    return tuple(checks)


def _parse_string_list(raw: Any, label: str) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise MalformedOutputError(f"{label} must be a list")
    if not all(isinstance(item, str) and item for item in raw):
        raise MalformedOutputError(f"{label} must contain only non-empty strings")
    return tuple(raw)


def _section_length(evidence: DiagnosticEvidence, section: str) -> int:
    value = getattr(evidence, section)
    if isinstance(value, Mapping):
        return len(value)
    return len(value)


def _known_runbook(identifier: object) -> bool:
    if not isinstance(identifier, str):
        return False
    try:
        known_runbook_reference(identifier)
    except ValueError:
        return False
    return True
