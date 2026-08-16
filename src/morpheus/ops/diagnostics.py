"""Diagnostic evidence package builder (AID-001).

Persists an assembled diagnostic evidence package as a canary-guarded
evidence run: per-section JSON, redacted log excerpts, the evidence
manifest with per-section digests and provenance, and a final manifest
with a per-file SHA-256 inventory. The package is written under an
owned root and never contains prompts, responses, secrets, raw
credentials, or unrestricted host data.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from morpheus.core.diagnostic_evidence import DiagnosticEvidence
from morpheus.core.runbooks import known_runbook_reference
from morpheus.ops.evidence import (
    CanaryGuard,
    EvidenceRun,
    EvidenceRunSpec,
    EvidenceStatus,
)

_EVIDENCE_TASK = ("AID-001",)
_EVIDENCE_ENVIRONMENT = "DEV"


class DiagnosticEvidenceError(RuntimeError):
    """The evidence package could not be built or finalized."""


@dataclass(frozen=True, slots=True)
class DiagnosticEvidencePackage:
    run_id: str
    root: Path
    manifest: dict[str, Any]
    digest: str
    size_bytes: int
    sections: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "root": str(self.root),
            "manifest": self.manifest,
            "digest": self.digest,
            "size_bytes": self.size_bytes,
            "sections": list(self.sections),
        }


class DiagnosticEvidenceBuilder:
    """Builds a bounded, redacted evidence run from assembled evidence."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def build(
        self,
        *,
        evidence: DiagnosticEvidence,
        run_id: str,
        source_commit: str,
        canaries: Mapping[str, str],
        started_at: datetime,
        ended_at: datetime,
        safe_summary: str,
        tool_versions: Mapping[str, str],
    ) -> DiagnosticEvidencePackage:
        guard = CanaryGuard(canaries)
        spec = EvidenceRunSpec(
            task_ids=_EVIDENCE_TASK,
            requirement_ids=_EVIDENCE_TASK,
            environment=_EVIDENCE_ENVIRONMENT,
            source_commit=source_commit,
        )
        try:
            run = EvidenceRun.create(self._root, run_id, spec, guard=guard, started_at=started_at)
        except ValueError as error:
            raise DiagnosticEvidenceError(str(error)) from error
        run.write_json("health.json", dict(evidence.health))
        run.write_json("machine_profile.json", dict(evidence.machine_profile))
        run.write_json("deployment.json", dict(evidence.deployment))
        run.write_json("metrics.json", dict(evidence.metrics))
        run.write_json("events.json", list(evidence.events))
        run.write_json("regressions.json", list(evidence.regressions))
        run.write_json(
            "runbooks.json",
            [known_runbook_reference(identifier).to_json() for identifier in evidence.runbooks],
        )
        for name, text in evidence.log_excerpts:
            run.write_text(f"logs/{name}", text)
        run.write_json("evidence.json", evidence.manifest())
        try:
            manifest_path = run.finalize(
                EvidenceStatus.PASS,
                ended_at=ended_at,
                safe_summary=safe_summary,
                tool_versions=dict(tool_versions),
            )
        except (ValueError, OSError) as error:
            raise DiagnosticEvidenceError(str(error)) from error
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload = manifest_path.read_bytes()
        return DiagnosticEvidencePackage(
            run_id=run_id,
            root=run.path,
            manifest=manifest,
            digest=f"sha256:{hashlib.sha256(payload).hexdigest()}",
            size_bytes=sum(item.stat().st_size for item in run.path.rglob("*") if item.is_file()),
            sections=evidence.sections,
        )
