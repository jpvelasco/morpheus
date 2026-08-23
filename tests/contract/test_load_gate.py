from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml
from _posix_tools import NEEDS_USABLE_BASH, USABLE_BASH

MORPHEUS_OWNED_REQUIREMENTS = frozenset({"PERF-001"})
pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[2]
LOAD = ROOT / "validation/load"


def test_LOAD_001_workload_is_versioned_bounded_and_reproducible() -> None:
    workload = json.loads((LOAD / "workload.json").read_text(encoding="utf-8"))

    assert workload["schema_version"] == 1
    assert workload["model"] == "morpheus-fixture-model"
    assert sum(workload["request_mix"].values()) == 1
    assert workload["fixture_delay_ms"] > 0
    for profile in ("dev", "qualification", "soak"):
        settings = workload["profiles"][profile]
        assert settings["vus"] >= 1
        assert settings["warmup_duration"]
        assert settings["measurement_duration"]
        assert settings["graceful_stop"]
        assert settings["max_p99_ms"] > workload["fixture_delay_ms"]
    assert workload["profiles"]["soak"]["measurement_duration"] == "24h"


def test_LOAD_001_k6_client_has_fixed_internal_targets_mix_checks_and_abort_limits() -> None:
    source = (LOAD / "workload.js").read_text(encoding="utf-8")

    for value in (
        "http://fixture:8000",
        "http://telemetry:7410",
        "morpheus_waiting_ms",
        "morpheus_iterations",
        "abortOnFail: true",
        "morpheus_fixture_delay_ms",
        "data: [DONE]",
        "handleSummary",
    ):
        assert value in source
    assert "TARGET_URL" not in source
    assert "sleep(" not in source


@NEEDS_USABLE_BASH
def test_LOAD_001_runner_is_pinned_hardened_and_accepts_only_an_owned_internal_network() -> None:
    bash = USABLE_BASH
    assert bash is not None
    runner = LOAD / "run.sh"
    subprocess.run([bash, "-n", runner], check=True)  # noqa: S603 - fixed checked-in script
    source = runner.read_text(encoding="utf-8")

    assert 'select(.id == "load-test")' in source
    assert "docker network inspect" in source
    assert ".Internal == true" in source
    assert '.["io.morpheus.project"] == $project' in source
    for hardening in (
        "--read-only",
        "--cap-drop ALL",
        "no-new-privileges:true",
        "--pids-limit",
        "--memory",
        "--user",
    ):
        assert hardening in source
    assert '--network "${network}"' in source
    assert "LOAD_API_KEY_FILE" in source
    assert "TARGET_API_KEY" not in source
    assert "trap cleanup EXIT" in source
    assert "--cidfile" in source
    assert '--label "io.morpheus.project=${project}"' in source
    assert '--label "io.morpheus.component=load-runner"' in source
    assert "docker container inspect" in source
    assert "docker stop" in source


def test_LOAD_003_summarizer_and_PERF_002_snapshot_are_closed_artifact_writers() -> None:
    summary = (LOAD / "summarize.py").read_text(encoding="utf-8")
    snapshot = (LOAD / "resource_snapshot.py").read_text(encoding="utf-8")
    compile(summary, str(LOAD / "summarize.py"), "exec")
    compile(snapshot, str(LOAD / "resource_snapshot.py"), "exec")

    assert "assess_load_overhead" in summary
    assert "sha256" in summary
    assert "parse_k6_summary" in summary
    assert "DockerResourceObserver" in snapshot
    assert "assess_resource_budget" in snapshot
    assert "assess_resource_growth" in snapshot
    assert '"growth_assessment"' in snapshot
    assert "get_secret_value" not in summary + snapshot
    assert "artifacts" in summary + snapshot


def test_LOAD_002_disposable_stack_is_internal_hardened_bounded_and_labeled() -> None:
    compose = yaml.safe_load((LOAD / "compose.yaml").read_text(encoding="utf-8"))

    assert compose["networks"]["load_internal"]["internal"] is True
    assert compose["networks"]["load_internal"]["labels"]["io.morpheus.project"]
    for name in ("fixture", "api", "dashboard", "telemetry"):
        service = compose["services"][name]
        assert service["read_only"] is True
        assert service["cap_drop"] == ["ALL"]
        assert service["security_opt"] == ["no-new-privileges:true"]
        assert "ports" not in service
        assert service["networks"] == ["load_internal"]
        assert service["deploy"]["resources"]["limits"]["memory"]
        assert service["labels"]["io.morpheus.project"]
        assert service["labels"]["io.morpheus.component"] == name


@NEEDS_USABLE_BASH
def test_LOAD_001_dev_rehearsal_refuses_existing_resources_and_always_cleans_up() -> None:
    bash = USABLE_BASH
    assert bash is not None
    rehearsal = LOAD / "dev_rehearsal.sh"
    subprocess.run([bash, "-n", rehearsal], check=True)  # noqa: S603 - fixed checked-in script
    source = rehearsal.read_text(encoding="utf-8")

    assert "docker ps -a" in source
    assert "trap cleanup EXIT" in source
    assert "down --volumes --rmi local --remove-orphans" in source
    assert "WORKLOAD_PROFILE=dev" in source
    assert "resource_snapshot.py" in source
    assert "summarize.py" in source
    assert "coder-model" not in source
    assert "open-webui" not in source


@NEEDS_USABLE_BASH
def test_SOAK_002_runner_requires_verified_candidate_exact_duration_and_parallel_monitor() -> None:
    bash = USABLE_BASH
    assert bash is not None
    soak = LOAD / "soak.sh"
    subprocess.run([bash, "-n", soak], check=True)  # noqa: S603 - fixed checked-in script
    source = soak.read_text(encoding="utf-8")

    assert "SOAK_CONFIRM_DURATION" in source
    assert "!= 24h" in source
    assert "verify_candidate.py" in source
    assert "WORKLOAD_PROFILE=soak" in source
    assert "resource_snapshot.py" in source
    assert "resource_monitor_pid=$!" in source
    assert "load_pid=$!" in source
    assert "wait -n -p completed_pid" in source
    assert 'wait "${resource_monitor_pid}"' in source
    assert "LOAD_PHASE=proxied" in source
    assert "docker compose" not in source
