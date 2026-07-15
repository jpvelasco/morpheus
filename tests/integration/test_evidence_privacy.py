from __future__ import annotations

import json
import sqlite3
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from morpheus.ops.evidence import (
    CanaryGuard,
    CanaryLeakError,
    EvidenceRun,
    EvidenceRunSpec,
    EvidenceStatus,
)

pytestmark = pytest.mark.integration

CANARY_CLASSES = (
    "prompt",
    "response",
    "document",
    "audio",
    "secret",
    "api_key",
    "agent_key",
    "session_key",
    "upstream_key",
    "workflow_key",
)
CANARIES = {
    name: f"CANARY-{name}-privacy-fixture-{index:02d}" for index, name in enumerate(CANARY_CLASSES)
}


def test_every_canary_class_is_absent_from_all_evidence_shapes(tmp_path: Path) -> None:
    guard = CanaryGuard(CANARIES)
    run = EvidenceRun.create(
        tmp_path / "artifacts" / "release-validation",
        "20260715T200000Z-privacy",
        EvidenceRunSpec(
            task_ids=("EVID-002",),
            requirement_ids=("CFG-002", "TEL-003", "OPS-003", "SEC-005"),
            environment="DEV",
            source_commit="d" * 40,
            reviewer="privacy-test",
        ),
        guard=guard,
        started_at=datetime(2026, 7, 15, 20, tzinfo=UTC),
    )

    structured = dict(CANARIES)
    run.write_json("reports/structured.json", structured)
    run.write_text("logs/runtime.log", "\n".join(CANARIES.values()))
    run.write_text("metrics/snapshot.prom", f'label="{CANARIES["prompt"]}" 1\n')

    leak_sources: dict[str, Path] = {}
    for shape, (suffix, canary_class) in {
        "screenshot": (".png", "audio"),
        "trace": (".json", "response"),
        "report": (".html", "workflow_key"),
    }.items():
        path = tmp_path / f"{shape}{suffix}"
        path.write_bytes(b"shape-header\x00" + CANARIES[canary_class].encode())
        leak_sources[shape] = path

    database = tmp_path / "export.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE evidence (value TEXT NOT NULL)")
    connection.execute("INSERT INTO evidence VALUES (?)", (CANARIES["document"],))
    connection.commit()
    connection.close()
    leak_sources["database"] = database

    bundle = tmp_path / "support.zip"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("logs/service.log", CANARIES["secret"])
    leak_sources["support"] = bundle

    for shape, source in leak_sources.items():
        with pytest.raises(CanaryLeakError):
            run.import_artifact(source, f"rejected/{shape}{source.suffix}")

    manifest = run.finalize(
        EvidenceStatus.PASS,
        ended_at=datetime(2026, 7, 15, 20, 1, tzinfo=UTC),
        safe_summary="privacy canaries redacted or rejected",
        tool_versions={"privacy-scanner": "morpheus-evidence-v1"},
    )
    for evidence_file in run.path.rglob("*"):
        if not evidence_file.is_file():
            continue
        content = evidence_file.read_bytes()
        for canary in CANARIES.values():
            assert canary.encode() not in content

    manifest_value = json.loads(manifest.read_text())
    assert set(manifest_value["canary_identifiers"]) == set(CANARIES)
    identifiers = manifest_value["canary_identifiers"].values()
    assert all(value.startswith("sha256:") for value in identifiers)
