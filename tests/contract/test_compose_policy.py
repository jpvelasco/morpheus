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
