from __future__ import annotations

import hashlib
import json
import os
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from morpheus.core.benchstore import BenchmarkStore
from morpheus.core.paths import OwnedPathResolver
from morpheus.core.redaction import redact
from morpheus.core.support_matrix import (
    BenchmarkRunRef,
    EvidenceRunRef,
    SupportProfile,
    derive_support_profile,
)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True).encode() + b"\n"


class SupportBundleBuilder:
    def __init__(self, *, owned_root: Path | None = None) -> None:
        self._owned_root = owned_root

    def build(
        self,
        destination: Path,
        *,
        version: str,
        configuration: dict[str, Any],
        health: dict[str, Any],
        errors: list[dict[str, Any]],
    ) -> Path:
        destination = OwnedPathResolver(self._owned_root or destination.parent).resolve(destination)
        safe_errors = [
            {
                key: value
                for key, value in error.items()
                if key in {"code", "safe_summary", "occurred_at", "request_id"}
            }
            for error in errors[-100:]
        ]
        files = {
            "configuration.json": _json_bytes(redact(configuration)),
            "errors.json": _json_bytes(redact(safe_errors)),
            "health.json": _json_bytes(redact(health)),
        }
        manifest = {
            "format": 1,
            "version": version,
            "files": {name: hashlib.sha256(content).hexdigest() for name, content in files.items()},
        }
        files["manifest.json"] = _json_bytes(manifest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for name, content in sorted(files.items()):
                bundle.writestr(name, content)
        os.replace(temporary, destination)
        return destination


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return default


class SupportReportService:
    """Assembles the evidence-bounded support posture from retained runs.

    The report is read-only: it never invokes live probes, never mutates
    evidence, and can only claim what retained PASS runs support.
    """

    def __init__(self, *, evidence_root: Path, benchmark_store: BenchmarkStore) -> None:
        self._evidence_root = OwnedPathResolver(evidence_root).root
        self._benchmark_store = benchmark_store

    def report(self, *, named_targets: Mapping[str, str]) -> SupportProfile:
        evidence_runs: list[EvidenceRunRef] = []
        if self._evidence_root.is_dir():
            evidence_runs = self._collect_evidence_runs()
        benchmark_runs = tuple(
            BenchmarkRunRef(
                run_id=run.run_id,
                status=run.status,
                machine_id=run.identity.machine_id,
                engine_id=run.identity.engine_id,
            )
            for run in self._benchmark_store.list_runs(limit=100)
        )
        return derive_support_profile(
            evidence_runs=tuple(evidence_runs),
            benchmark_runs=benchmark_runs,
            named_targets=dict(named_targets),
        )

    def _collect_evidence_runs(self) -> list[EvidenceRunRef]:
        evidence_runs: list[EvidenceRunRef] = []
        for directory in sorted(self._evidence_root.iterdir()):
            if not directory.is_dir():
                continue
            manifest_path = directory / "manifest.json"
            manifest = _read_json(manifest_path, None)
            if not isinstance(manifest, dict):
                continue
            digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            run_id = manifest.get("run_id")
            if not isinstance(run_id, str):
                continue
            evidence_runs.append(
                EvidenceRunRef(
                    run_id=run_id,
                    digest=digest,
                    status=str(manifest.get("status", "unknown")),
                    environment=str(manifest.get("environment", "unknown")),
                    machine_profile=_read_json(directory / "machine_profile.json", {}),
                    deployment=_read_json(directory / "deployment.json", {}),
                    regressions=tuple(_read_json(directory / "regressions.json", [])),
                    runbooks=tuple(_read_json(directory / "runbooks.json", [])),
                )
            )
        return evidence_runs
