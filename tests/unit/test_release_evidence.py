from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from morpheus.ops.evidence import (
    CanaryGuard,
    CanaryLeakError,
    EvidenceRun,
    EvidenceRunSpec,
    EvidenceStatus,
)

STARTED = datetime(2026, 7, 15, 19, 30, tzinfo=UTC)


def spec() -> EvidenceRunSpec:
    return EvidenceRunSpec(
        task_ids=("EVID-001", "EVID-002"),
        requirement_ids=("CFG-002", "TEL-003", "OPS-003", "SEC-005"),
        environment="DEV",
        source_commit="a" * 40,
        authorization_ref=None,
        reviewer="release-reviewer",
    )


def test_evidence_run_redacts_canaries_and_finalizes_manifest(tmp_path: Path) -> None:
    canaries = {
        "prompt": "CANARY-PROMPT-raw-value",
        "api_key": "sk-CANARY-api-key",
        "session_key": "CANARY-session-secret",
    }
    guard = CanaryGuard(canaries)
    run = EvidenceRun.create(
        tmp_path,
        "20260715T193000Z-aaaaaaaa",
        spec(),
        guard=guard,
        started_at=STARTED,
    )

    run.write_json(
        "results/summary.json",
        {
            "api_key": canaries["api_key"],
            "prompt": canaries["prompt"],
            "safe_summary": f"handled {canaries['session_key']}",
            "request_id": guard.identifier("session_key"),
        },
    )
    run.write_text("logs/probe.log", f"input={canaries['prompt']}\nstatus=ok\n")
    manifest_path = run.finalize(
        EvidenceStatus.PASS,
        ended_at=STARTED + timedelta(seconds=12),
        safe_summary="all evidence checks passed",
        tool_versions={"python": "3.12.11", "docker": "29.1.3"},
        candidate_checksums={"dist/app.whl": "sha256:" + "b" * 64},
        pre_state_digest="sha256:" + "c" * 64,
        post_state_digest="sha256:" + "c" * 64,
    )

    manifest = json.loads(manifest_path.read_text())
    assert manifest["status"] == "pass"
    assert manifest["task_ids"] == ["EVID-001", "EVID-002"]
    assert manifest["environment"] == "DEV"
    assert manifest["started_at"] == "2026-07-15T19:30:00Z"
    assert manifest["ended_at"] == "2026-07-15T19:30:12Z"
    assert manifest["tools"] == {"docker": "29.1.3", "python": "3.12.11"}
    assert manifest["canary_identifiers"] == {
        name: guard.identifier(name) for name in sorted(canaries)
    }
    assert set(manifest["files"]) == {"logs/probe.log", "results/summary.json"}

    summary = (run.path / "results/summary.json").read_text()
    log = (run.path / "logs/probe.log").read_text()
    assert "[REDACTED]" in summary
    assert "[REDACTED]" in log
    for raw_canary in canaries.values():
        assert raw_canary not in summary
        assert raw_canary not in log
        assert raw_canary not in manifest_path.read_text()
    assert not list(run.path.rglob("*.tmp"))

    for relative, metadata in manifest["files"].items():
        content = (run.path / relative).read_bytes()
        assert metadata == {
            "sha256": hashlib.sha256(content).hexdigest(),
            "size": len(content),
        }


@pytest.mark.parametrize("status", list(EvidenceStatus))
def test_all_explicit_evidence_statuses_are_supported(
    tmp_path: Path, status: EvidenceStatus
) -> None:
    run = EvidenceRun.create(
        tmp_path,
        f"20260715T193000Z-{status.value}",
        spec(),
        guard=CanaryGuard({}),
        started_at=STARTED,
    )
    manifest = json.loads(
        run.finalize(
            status,
            ended_at=STARTED,
            safe_summary=f"run is {status.value}",
            tool_versions={},
        ).read_text()
    )
    assert manifest["status"] == status.value


@pytest.mark.parametrize(
    "relative_path",
    [
        "../escape.log",
        "/tmp/escape.log",  # noqa: S108 - intentionally unsafe test input
        "results/../../escape.log",
        ".",
        "manifest.json",
    ],
)
def test_evidence_run_rejects_unsafe_or_reserved_paths(tmp_path: Path, relative_path: str) -> None:
    run = EvidenceRun.create(
        tmp_path,
        "20260715T193000Z-paths",
        spec(),
        guard=CanaryGuard({}),
        started_at=STARTED,
    )
    with pytest.raises(ValueError, match="evidence path"):
        run.write_text(relative_path, "safe")


def test_evidence_run_cannot_be_reopened_or_written_after_finalize(tmp_path: Path) -> None:
    run_id = "20260715T193000Z-lifecycle"
    run = EvidenceRun.create(tmp_path, run_id, spec(), guard=CanaryGuard({}), started_at=STARTED)
    run.finalize(
        EvidenceStatus.BLOCKED,
        ended_at=STARTED,
        safe_summary="prerequisite unavailable",
        tool_versions={},
    )

    with pytest.raises(FileExistsError):
        EvidenceRun.create(tmp_path, run_id, spec(), guard=CanaryGuard({}), started_at=STARTED)
    with pytest.raises(RuntimeError, match="finalized"):
        run.write_text("logs/late.log", "too late")
    with pytest.raises(RuntimeError, match="finalized"):
        run.finalize(
            EvidenceStatus.PASS,
            ended_at=STARTED,
            safe_summary="too late",
            tool_versions={},
        )


def test_imported_artifact_with_raw_or_archived_canary_is_rejected(tmp_path: Path) -> None:
    raw = "CANARY-private-document"
    run = EvidenceRun.create(
        tmp_path,
        "20260715T193000Z-artifacts",
        spec(),
        guard=CanaryGuard({"document": raw}),
        started_at=STARTED,
    )
    screenshot = tmp_path / "screenshot.png"
    screenshot.write_bytes(b"fake-png\x00" + raw.encode())
    bundle = tmp_path / "support.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("nested/report.json", json.dumps({"document": raw}))

    with pytest.raises(CanaryLeakError, match="document"):
        run.import_artifact(screenshot, "screenshots/page.png")
    with pytest.raises(CanaryLeakError, match="document"):
        run.import_artifact(bundle, "support/support.zip")

    assert not (run.path / "screenshots/page.png").exists()
    assert not (run.path / "support/support.zip").exists()


def test_safe_artifact_is_copied_and_inventoried(tmp_path: Path) -> None:
    source = tmp_path / "trace.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("trace.json", '{"status":"ok"}')
    run = EvidenceRun.create(
        tmp_path,
        "20260715T193000Z-safe-artifact",
        spec(),
        guard=CanaryGuard({"response": "CANARY-private-response"}),
        started_at=STARTED,
    )

    destination = run.import_artifact(source, "traces/trace.zip")
    manifest = json.loads(
        run.finalize(
            EvidenceStatus.PASS,
            ended_at=STARTED,
            safe_summary="safe artifact accepted",
            tool_versions={},
        ).read_text()
    )

    assert destination.read_bytes() == source.read_bytes()
    assert "traces/trace.zip" in manifest["files"]


@pytest.mark.parametrize(
    "values",
    [
        {"task_ids": ()},
        {"requirement_ids": ("",)},
        {"environment": "PRODUCTION"},
        {"source_commit": "not-a-commit"},
    ],
)
def test_evidence_spec_rejects_invalid_metadata(values: dict[str, object]) -> None:
    defaults: dict[str, object] = {
        "task_ids": ("EVID-001",),
        "requirement_ids": (),
        "environment": "DEV",
        "source_commit": "a" * 40,
    }
    defaults.update(values)
    with pytest.raises(ValueError):
        EvidenceRunSpec(**defaults)  # type: ignore[arg-type]


def test_canary_guard_rejects_ambiguous_registry_and_unknown_class() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        CanaryGuard({"secret": ""})
    with pytest.raises(ValueError, match="unique"):
        CanaryGuard({"first": "same", "second": "same"})
    with pytest.raises(KeyError, match="unknown canary"):
        CanaryGuard({"secret": "value"}).identifier("missing")


def test_evidence_run_rejects_invalid_identity_timestamp_and_source(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="run ID"):
        EvidenceRun.create(
            tmp_path,
            "../unsafe",
            spec(),
            guard=CanaryGuard({}),
            started_at=STARTED,
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        EvidenceRun.create(
            tmp_path,
            "valid-run-id",
            spec(),
            guard=CanaryGuard({}),
            started_at=datetime(2026, 7, 15),  # noqa: DTZ001 - intentionally naive input
        )

    run = EvidenceRun.create(
        tmp_path,
        "20260715T193000Z-import-source",
        spec(),
        guard=CanaryGuard({}),
        started_at=STARTED,
    )
    with pytest.raises(ValueError, match="regular file"):
        run.import_artifact(tmp_path, "reports/source")
    run.write_text("logs/once.log", "safe")
    with pytest.raises(FileExistsError):
        run.write_text("logs/once.log", "replacement")


@pytest.mark.parametrize(
    "finalize_values",
    [
        {"ended_at": STARTED - timedelta(seconds=1)},
        {"pre_state_digest": "invalid"},
        {"post_state_digest": "invalid"},
        {"candidate_checksums": {"artifact": "invalid"}},
    ],
)
def test_evidence_finalize_rejects_invalid_time_or_digest(
    tmp_path: Path, finalize_values: dict[str, object]
) -> None:
    run = EvidenceRun.create(
        tmp_path,
        f"20260715T193000Z-finalize-{len(list(tmp_path.iterdir()))}",
        spec(),
        guard=CanaryGuard({}),
        started_at=STARTED,
    )
    values: dict[str, object] = {
        "ended_at": STARTED,
        "safe_summary": "invalid metadata should fail",
        "tool_versions": {},
    }
    values.update(finalize_values)
    with pytest.raises(ValueError):
        run.finalize(EvidenceStatus.FAIL, **values)  # type: ignore[arg-type]


def test_finalize_fails_closed_on_caller_injected_canary(tmp_path: Path) -> None:
    raw = "CANARY-injected-after-create"
    run = EvidenceRun.create(
        tmp_path,
        "20260715T193000Z-injected",
        spec(),
        guard=CanaryGuard({"secret": raw}),
        started_at=STARTED,
    )
    injected = run.path / "caller-created.log"
    injected.write_text(raw)

    with pytest.raises(CanaryLeakError):
        run.finalize(
            EvidenceStatus.PASS,
            ended_at=STARTED,
            safe_summary="must fail",
            tool_versions={},
        )
    assert not (run.path / "manifest.json").exists()


def test_streamed_evidence_is_bounded_and_redacts_split_canary(tmp_path: Path) -> None:
    raw = b"CANARY-split-across-command-chunks"
    run = EvidenceRun.create(
        tmp_path,
        "20260715T193000Z-streamed",
        spec(),
        guard=CanaryGuard({"prompt": raw.decode()}),
        started_at=STARTED,
    )
    with run.open_redacted_stream("logs/long-running.log") as stream:
        stream.write(b"x" * (2 * 1024 * 1024))
        stream.write(raw[:11])
        stream.write(raw[11:23])
        stream.write(raw[23:] + b"\ncomplete\n")

    content = (run.path / "logs/long-running.log").read_bytes()
    assert raw not in content
    assert content.endswith(b"[REDACTED]\ncomplete\n")
    assert len(content) == 2 * 1024 * 1024 + len(b"[REDACTED]\ncomplete\n")
