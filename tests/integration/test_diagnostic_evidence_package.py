"""Integration tests: bounded redacted diagnostic evidence package (AID-001).

Builds a full evidence run through the builder with adversarial canaries
and secret-shaped log/event content, then verifies the finalized package:
per-file digest inventory, provenance, no raw canaries, no secret-shaped
bytes, bounded size, and manifest consistency.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from morpheus.core.diagnostic_evidence import (
    DiagnosticProvenance,
    build_diagnostic_evidence,
)
from morpheus.ops.diagnostics import DiagnosticEvidenceBuilder

CANARIES = {
    "prompt": "canary-prompt-0001",
    "response": "canary-response-0002",
    "secret": "canary-secret-0003",
    "api_key": "sk-live-canary-0004",
    "session_secret": "canary-session-0005",
    "upstream_key": "canary-upstream-0006",
}

STARTED_AT = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)
ENDED_AT = datetime(2026, 8, 15, 12, 0, 5, tzinfo=UTC)


def _evidence() -> object:
    return build_diagnostic_evidence(
        health={
            "status": "degraded",
            "checks": [{"code": "storage", "status": "fail", "prompt": "what to check next?"}],
        },
        machine_profile={
            "os": "linux",
            "architecture": "x86_64",
            "accelerator": {"kind": "nvidia", "name": "RTX 4070 Ti Super"},
        },
        deployment={"version": "0.1.0", "source_commit": "0123456789abcdef"},
        metrics={"gpu_cache_usage": [{"start": "2026-08-15T11:00:00Z", "count": 2, "mean": 0.5}]},
        events=[
            {
                "recorded_at": "2026-08-15T11:59:00Z",
                "source": "api",
                "message": f"request failed with secret={CANARIES['session_secret']}",
            },
            {
                "recorded_at": "2026-08-15T11:59:01Z",
                "source": "agent",
                "message": f"heartbeat canary={CANARIES['api_key']}",
            },
        ],
        log_excerpts=[
            ("engine.log", f"engine started for prompt {CANARIES['prompt']}"),
            ("agent.log", f"Authorization: Bearer {CANARIES['secret']}"),
        ],
        regressions=[{"metric": "tokens_per_second", "change_pct": -12.5}],
        runbooks=["ubuntu-1-operator"],
        provenance=DiagnosticProvenance(
            morpheus_version="0.1.0",
            source_commit="0123456789abcdef",
            observed_at="2026-08-15T12:00:00Z",
        ),
        canaries=CANARIES,
    )


def test_builder_finalizes_a_redacted_provenanced_package(tmp_path: Path) -> None:
    builder = DiagnosticEvidenceBuilder(tmp_path)
    package = builder.build(
        evidence=_evidence(),
        run_id="diag-20260815-001",
        source_commit="0123456789abcdef",
        canaries=CANARIES,
        started_at=STARTED_AT,
        ended_at=ENDED_AT,
        safe_summary="Diagnostic evidence package assembled for local analysis",
        tool_versions={"morpheus": "0.1.0"},
    )

    manifest = package.manifest
    assert manifest["status"] == "pass"
    assert manifest["environment"] == "DEV"
    assert manifest["requirement_ids"] == ["AID-001"]
    assert manifest["source_commit"] == "0123456789abcdef"
    assert manifest["safe_summary"] == ("Diagnostic evidence package assembled for local analysis")
    assert package.digest.startswith("sha256:")
    assert package.size_bytes > 0
    assert package.sections == (
        "health",
        "machine_profile",
        "deployment",
        "metrics",
        "events",
        "log_excerpts",
        "regressions",
        "runbooks",
    )

    expected_files = {
        "health.json",
        "machine_profile.json",
        "deployment.json",
        "metrics.json",
        "events.json",
        "regressions.json",
        "runbooks.json",
        "evidence.json",
        "logs/engine.log",
        "logs/agent.log",
    }
    assert set(manifest["files"]) == expected_files


def test_package_contains_no_canaries_or_secret_shaped_bytes(tmp_path: Path) -> None:
    builder = DiagnosticEvidenceBuilder(tmp_path)
    package = builder.build(
        evidence=_evidence(),
        run_id="diag-20260815-002",
        source_commit="0123456789abcdef",
        canaries=CANARIES,
        started_at=STARTED_AT,
        ended_at=ENDED_AT,
        safe_summary="no canaries",
        tool_versions={"morpheus": "0.1.0"},
    )

    for member in package.root.rglob("*"):
        if not member.is_file():
            continue
        content = member.read_bytes()
        for canary in CANARIES.values():
            assert canary.encode() not in content, f"{member.name} leaked {canary}"
        for leaked in (b"sk-live-", b"Bearer "):
            assert leaked not in content, f"{member.name} leaked {leaked}"

    events = json.loads((package.root / "events.json").read_text(encoding="utf-8"))
    for event in events:
        assert "[REDACTED]" in event["message"]

    health = json.loads((package.root / "health.json").read_text(encoding="utf-8"))
    assert health["checks"][0]["prompt"] == "[REDACTED]"
