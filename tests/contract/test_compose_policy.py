from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[2]


def test_release_images_are_digest_pinned_and_ports_are_loopback_only() -> None:
    compose = yaml.safe_load((ROOT / "deploy/compose.yaml").read_text(encoding="utf-8"))
    for name, service in compose["services"].items():
        image = service.get("image")
        if image:
            assert "@sha256:" in image, f"{name} image is not digest pinned"
        for port in service.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), f"{name} publishes a non-loopback port"


def test_every_service_has_project_ownership_label() -> None:
    compose = yaml.safe_load((ROOT / "deploy/compose.yaml").read_text(encoding="utf-8"))
    for name, service in compose["services"].items():
        labels = service.get("labels", {})
        assert labels.get("io.morpheus.project") == "${MORPHEUS_PROJECT_ID:-morpheus}", name


def test_external_network_is_never_owned() -> None:
    compose = yaml.safe_load((ROOT / "deploy/compose.yaml").read_text(encoding="utf-8"))
    network = compose["networks"]["ai_default"]
    assert network == {"external": True, "name": "${MORPHEUS_EXTERNAL_DOCKER_NETWORK:-ai_default}"}


def test_python_services_acknowledge_the_container_bind_address() -> None:
    compose = yaml.safe_load((ROOT / "deploy/compose.yaml").read_text(encoding="utf-8"))
    for name in ("api", "telemetry"):
        environment = compose["services"][name]["environment"]
        assert environment["MORPHEUS_BIND_ADDRESS"] == "0.0.0.0"  # noqa: S104
        assert environment["MORPHEUS_ALLOW_LAN"] == "true"
        # Host lab paths must never leak into containers via env_file alone.
        assert environment["MORPHEUS_DATA_DIR"] == "/var/lib/morpheus"


def test_tmpfs_entries_are_single_absolute_mount_specifications() -> None:
    for path in sorted((ROOT / "deploy").glob("compose*.yaml")):
        compose = yaml.safe_load(path.read_text(encoding="utf-8"))
        for name, service in compose.get("services", {}).items():
            for tmpfs in service.get("tmpfs", []):
                assert str(tmpfs).startswith("/"), f"{path.name}:{name}:{tmpfs}"
                assert not str(tmpfs).startswith("mode="), f"{path.name}:{name}:{tmpfs}"


def test_runtime_image_prepares_the_nonroot_data_directory() -> None:
    dockerfile = (ROOT / "deploy/Dockerfile").read_text(encoding="utf-8")
    ownership = "install -d -o morpheus -g morpheus -m 0750 /var/lib/morpheus"
    assert ownership in dockerfile
    assert dockerfile.index(ownership) < dockerfile.index("USER morpheus")


def test_telemetry_overrides_the_backend_image_health_port() -> None:
    compose = yaml.safe_load((ROOT / "deploy/compose.yaml").read_text(encoding="utf-8"))
    healthcheck = " ".join(compose["services"]["telemetry"]["healthcheck"]["test"])
    assert "127.0.0.1:7410/healthz" in healthcheck
    assert "127.0.0.1:7400/healthz" not in healthcheck


def test_CONT_002_core_services_accept_an_explicit_private_environment_file() -> None:
    compose = yaml.safe_load((ROOT / "deploy/compose.yaml").read_text(encoding="utf-8"))
    expected = [{"path": "${MORPHEUS_ENV_FILE:-../.env}", "required": False}]

    assert compose["services"]["api"]["env_file"] == expected
    assert compose["services"]["telemetry"]["env_file"] == expected


def test_CONT_002_api_keeps_its_container_port_when_the_host_port_changes() -> None:
    compose = yaml.safe_load((ROOT / "deploy/compose.yaml").read_text(encoding="utf-8"))

    assert compose["services"]["api"]["environment"]["MORPHEUS_API_PORT"] == "7400"
    assert compose["services"]["telemetry"]["environment"]["MORPHEUS_TELEMETRY_PORT"] == "7410"


def test_runtime_agent_overlay_mounts_only_the_authenticated_unix_socket_directory() -> None:
    compose = yaml.safe_load((ROOT / "deploy/compose.agent.yaml").read_text(encoding="utf-8"))
    api = compose["services"]["api"]
    assert api["group_add"] == ["${MORPHEUS_AGENT_GID:?MORPHEUS_AGENT_GID is required}"]
    assert api["environment"]["MORPHEUS_RUNTIME_AGENT_SOCKET"] == ("/run/morpheus-agent/agent.sock")
    assert api["volumes"] == [
        {
            "type": "bind",
            "source": "${MORPHEUS_AGENT_SOCKET_DIR:?MORPHEUS_AGENT_SOCKET_DIR is required}",
            "target": "/run/morpheus-agent",
            "read_only": True,
        }
    ]
    assert "/var/run/docker.sock" not in str(api)


def test_quality_workflow_runs_the_frontend_gate_in_a_pinned_container() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8"))
    frontend = workflow["jobs"]["frontend"]
    commands = "\n".join(step.get("run", "") for step in frontend["steps"])
    assert "docker run" in commands
    assert "node:22.17.1-alpine3.22@sha256:" in commands
    for command in (
        "npm ci --ignore-scripts",
        "npm run format-check",
        "npm run typecheck",
        "npm test",
        "npm run build",
    ):
        assert command in commands
