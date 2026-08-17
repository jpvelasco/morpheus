from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from morpheus.agent import host
from morpheus.agent.host import SystemHostInspector
from morpheus.agent.protocol import AgentOperation


def test_RUN_004_host_summary_uses_bounded_memory_and_disk_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        host,
        "_memory_summary",
        lambda: {"total_bytes": 1000, "available_bytes": 600},
    )
    monkeypatch.setattr(
        host.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(total=2000, used=750, free=1250),
    )
    if os.name == "nt":
        # The /proc process state is a Linux-only observation source.
        monkeypatch.setattr(host, "_load_average_1m", lambda: 0.5)
        monkeypatch.setattr(host, "_uptime_seconds", lambda: 42.0)

    result = SystemHostInspector(project_id="morpheus", data_dir=tmp_path).inspect(
        AgentOperation.HOST_SUMMARY
    )

    assert result["memory"] == {"total_bytes": 1000, "available_bytes": 600}
    assert result["disk"] == {
        "total_bytes": 2000,
        "used_bytes": 750,
        "free_bytes": 1250,
    }
    assert result["process"]["load_average_1m"] >= 0
    assert result["process"]["uptime_seconds"] > 0
    assert datetime.fromisoformat(result["clock"]["observed_at"]).tzinfo is not None


def test_RUN_004_gpu_summary_parses_only_complete_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    observed: list[str] = []

    def run(command: list[str], **kwargs: object) -> SimpleNamespace:
        observed.extend(command)
        assert kwargs == {"check": True, "capture_output": True, "text": True, "timeout": 5}
        return SimpleNamespace(stdout="0, GPU, GPU-1, 32607, 831, 42, 55\nmalformed,row\n")

    monkeypatch.setattr(host.subprocess, "run", run)
    result = SystemHostInspector(project_id="morpheus", data_dir=tmp_path).inspect(
        AgentOperation.GPU_SUMMARY
    )

    assert observed[0] == "nvidia-smi"
    assert result == {
        "gpus": [
            {
                "index": 0,
                "name": "GPU",
                "uuid": "GPU-1",
                "memory_total_mib": 32607,
                "memory_used_mib": 831,
                "utilization_percent": 42,
                "temperature_c": 55,
            }
        ]
    }


def test_INV_002_service_summary_uses_only_project_label(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    container_id = "a" * 64

    def run(command: list[str], **kwargs: object) -> SimpleNamespace:
        assert kwargs["timeout"] == 5
        if command[:2] == ["docker", "ps"]:
            assert "label=io.morpheus.project=project-1" in command
            return SimpleNamespace(stdout=container_id + "\n")
        assert command[-1] == container_id
        return SimpleNamespace(
            stdout=json.dumps(
                {
                    "id": container_id,
                    "name": "/morpheus-api",
                    "image_id": "sha256:" + "b" * 64,
                    "configured_image": "morpheus/backend:0.1.0-commit",
                    "labels": {
                        "io.morpheus.project": "project-1",
                        "io.morpheus.component": "api",
                        "org.opencontainers.image.revision": "c" * 40,
                        "org.opencontainers.image.version": "0.1.0",
                    },
                    "state": "running",
                    "health": "healthy",
                }
            )
        )

    monkeypatch.setattr(host.subprocess, "run", run)
    result = SystemHostInspector(project_id="project-1", data_dir=tmp_path).inspect(
        AgentOperation.MORPHEUS_SERVICES
    )
    assert result == {
        "containers": [
            {
                "id": container_id,
                "name": "morpheus-api",
                "image_id": "sha256:" + "b" * 64,
                "configured_image": "morpheus/backend:0.1.0-commit",
                "state": "running",
                "health": "healthy",
                "project": "project-1",
                "component": "api",
                "source_commit": "c" * 40,
                "release_version": "0.1.0",
            }
        ]
    }


def test_agent_inspector_rejects_an_untyped_operation(tmp_path: Path) -> None:
    inspector = SystemHostInspector(project_id="morpheus", data_dir=tmp_path)
    with pytest.raises(ValueError, match="unsupported"):
        inspector.inspect("shell")  # type: ignore[arg-type]


def test_SEC_002_agent_rejects_a_protected_container_with_a_forged_label(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    container_id = "a" * 64

    def run(command: list[str], **kwargs: object) -> SimpleNamespace:
        if command[:2] == ["docker", "ps"]:
            return SimpleNamespace(stdout=container_id + "\n")
        return SimpleNamespace(
            stdout=json.dumps(
                {
                    "id": container_id,
                    "name": "/coder-model",
                    "image_id": "sha256:" + "b" * 64,
                    "configured_image": "external/inference:stable",
                    "labels": {
                        "io.morpheus.project": "project-1",
                        "io.morpheus.component": "forged",
                    },
                    "state": "running",
                    "health": "healthy",
                }
            )
        )

    monkeypatch.setattr(host.subprocess, "run", run)
    inspector = SystemHostInspector(project_id="project-1", data_dir=tmp_path)

    with pytest.raises(PermissionError, match="not authorized"):
        inspector.inspect(AgentOperation.MORPHEUS_SERVICES)


def test_RUN_004_memory_parser_converts_kib_to_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = "MemTotal:       1000 kB\nMemFree: 100 kB\nMemAvailable: 600 kB\n"
    monkeypatch.setattr(Path, "read_text", lambda self, **kwargs: fixture)
    assert host._memory_summary() == {
        "total_bytes": 1_024_000,
        "available_bytes": 614_400,
    }
