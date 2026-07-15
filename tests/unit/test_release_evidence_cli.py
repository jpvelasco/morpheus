from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

from morpheus.ops.evidence_cli import main


def test_cli_runs_command_and_records_redacted_evidence(tmp_path: Path) -> None:
    canary = "CANARY-cli-prompt-raw"
    canary_file = tmp_path / "canaries.json"
    canary_file.write_text(json.dumps({"prompt": canary}))
    canary_file.chmod(0o600)
    root = tmp_path / "artifacts" / "release-validation"

    exit_code = main(
        [
            "--root",
            str(root),
            "--run-id",
            "20260715T210000Z-cli",
            "--task",
            "EVID-001",
            "--requirement",
            "SEC-005",
            "--environment",
            "DEV",
            "--source-commit",
            "e" * 40,
            "--reviewer",
            "automated-test",
            "--canary-file",
            str(canary_file),
            "--tool",
            "fixture=1.0",
            "--",
            sys.executable,
            "-c",
            "import os; print(os.environ['MORPHEUS_EVIDENCE_CANARY_PROMPT'])",
        ]
    )

    assert exit_code == 0
    run = root / "20260715T210000Z-cli"
    assert (run / "logs/stdout.log").read_text() == "[REDACTED]\n"
    manifest = json.loads((run / "manifest.json").read_text())
    assert manifest["status"] == "pass"
    assert manifest["tools"]["fixture"] == "1.0"
    assert manifest["tools"]["evidence-runner"] == "1"
    result = json.loads((run / "results/command.json").read_text())
    assert result == {
        "argument_count": 3,
        "executable": Path(sys.executable).name,
        "exit_code": 0,
        "timed_out": False,
    }
    for path in run.rglob("*"):
        if path.is_file():
            assert canary not in path.read_text(errors="ignore")


def test_cli_records_failure_and_imports_safe_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "report.txt"
    artifact.write_text("safe report")

    exit_code = main(
        [
            "--root",
            str(tmp_path / "evidence"),
            "--run-id",
            "20260715T210000Z-fail",
            "--task",
            "EVID-001",
            "--environment",
            "VM",
            "--source-commit",
            "f" * 40,
            "--reviewer",
            "automated-test",
            "--artifact",
            f"{artifact}=reports/report.txt",
            "--",
            sys.executable,
            "-c",
            "raise SystemExit(7)",
        ]
    )

    assert exit_code == 7
    run = tmp_path / "evidence" / "20260715T210000Z-fail"
    assert (run / "reports/report.txt").read_text() == "safe report"
    assert json.loads((run / "manifest.json").read_text())["status"] == "fail"


def test_cli_requires_private_canary_file_and_host_authorization(tmp_path: Path) -> None:
    canary_file = tmp_path / "canaries.json"
    canary_file.write_text('{"secret":"CANARY-secret"}')
    canary_file.chmod(0o644)
    common = [
        "--root",
        str(tmp_path / "evidence"),
        "--task",
        "EVID-002",
        "--source-commit",
        "a" * 40,
        "--reviewer",
        "automated-test",
    ]

    with pytest.raises(ValueError, match="permissions"):
        main(
            [
                *common,
                "--run-id",
                "20260715T210000Z-permissions",
                "--environment",
                "DEV",
                "--canary-file",
                str(canary_file),
                "--",
                os.devnull,
            ]
        )

    with pytest.raises(ValueError, match="authorization"):
        main(
            [
                *common,
                "--run-id",
                "20260715T210000Z-auth",
                "--environment",
                "HOST-RO",
                "--",
                os.devnull,
            ]
        )


@pytest.mark.parametrize(
    ("command", "timeout", "expected_status", "expected_exit"),
    [
        ([sys.executable, "-c", "import time; time.sleep(1)"], "0.01", "fail", 124),
        (["/definitely/not/a/command"], None, "blocked", 125),
    ],
)
def test_cli_records_timeout_and_unavailable_command(
    tmp_path: Path,
    command: list[str],
    timeout: str | None,
    expected_status: str,
    expected_exit: int,
) -> None:
    arguments = [
        "--root",
        str(tmp_path / "evidence"),
        "--run-id",
        f"20260715T210000Z-{expected_status}",
        "--task",
        "EVID-001",
        "--environment",
        "VM",
        "--source-commit",
        "b" * 40,
        "--reviewer",
        "automated-test",
    ]
    if timeout is not None:
        arguments.extend(["--timeout", timeout])
    arguments.extend(["--", *command])

    assert main(arguments) == expected_exit
    run = tmp_path / "evidence" / f"20260715T210000Z-{expected_status}"
    manifest = json.loads((run / "manifest.json").read_text())
    result = json.loads((run / "results/command.json").read_text())
    assert manifest["status"] == expected_status
    assert result["exit_code"] == expected_exit
    assert result["timed_out"] is (expected_exit == 124)


def test_cli_rejects_leaking_artifact_and_hashes_candidate(tmp_path: Path) -> None:
    canary = "CANARY-cli-artifact-leak"
    canary_file = tmp_path / "canaries.json"
    canary_file.write_text(json.dumps({"document": canary}))
    canary_file.chmod(0o600)
    artifact = tmp_path / "leaking-report.txt"
    artifact.write_text(canary)
    candidate = tmp_path / "candidate.whl"
    candidate.write_bytes(b"safe-candidate")
    digest = "sha256:" + hashlib.sha256(candidate.read_bytes()).hexdigest()
    state_digest = "sha256:" + "c" * 64

    exit_code = main(
        [
            "--root",
            str(tmp_path / "evidence"),
            "--run-id",
            "20260715T210000Z-rejection",
            "--task",
            "EVID-002",
            "--environment",
            "DEV",
            "--source-commit",
            "c" * 40,
            "--reviewer",
            "automated-test",
            "--canary-file",
            str(canary_file),
            "--artifact",
            f"{artifact}=reports/report.txt",
            "--candidate",
            f"{candidate}=dist/candidate.whl",
            "--pre-state-digest",
            state_digest,
            "--post-state-digest",
            state_digest,
            "--",
            sys.executable,
            "-c",
            "raise SystemExit(0)",
        ]
    )

    assert exit_code == 1
    run = tmp_path / "evidence" / "20260715T210000Z-rejection"
    manifest = json.loads((run / "manifest.json").read_text())
    assert manifest["status"] == "fail"
    assert manifest["candidate_checksums"] == {"dist/candidate.whl": digest}
    assert manifest["pre_state_digest"] == state_digest
    assert (run / "results/artifact-rejection.json").is_file()
    assert not (run / "reports/report.txt").exists()


def test_cli_autogenerates_commit_based_run_id(tmp_path: Path) -> None:
    root = tmp_path / "evidence"
    assert (
        main(
            [
                "--root",
                str(root),
                "--task",
                "EVID-001",
                "--environment",
                "DEV",
                "--reviewer",
                "automated-test",
                "--",
                sys.executable,
                "-c",
                "raise SystemExit(0)",
            ]
        )
        == 0
    )
    runs = list(root.iterdir())
    assert len(runs) == 1
    manifest = json.loads((runs[0] / "manifest.json").read_text())
    assert len(manifest["source_commit"]) == 40


@pytest.mark.parametrize("binding", ["missing-separator", "=empty-name", "empty-value="])
def test_cli_rejects_invalid_tool_binding(tmp_path: Path, binding: str) -> None:
    with pytest.raises(ValueError, match="NAME=VALUE"):
        main(
            [
                "--root",
                str(tmp_path / "evidence"),
                "--run-id",
                "20260715T210000Z-binding",
                "--task",
                "EVID-001",
                "--environment",
                "DEV",
                "--source-commit",
                "d" * 40,
                "--reviewer",
                "automated-test",
                "--tool",
                binding,
                "--",
                os.devnull,
            ]
        )
