from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[2]
OVERLAYS = sorted((ROOT / "deploy").glob("compose.*.yaml"))


def services() -> list[tuple[Path, str, dict[str, object]]]:
    result = []
    for path in OVERLAYS:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        for name, service in document.get("services", {}).items():
            result.append((path, name, service))
    return result


def test_SEC_005_every_upstream_image_is_digest_pinned_and_locked() -> None:
    lock = json.loads((ROOT / "deploy/images.lock.json").read_text(encoding="utf-8"))
    locked = {item["digest"] for item in lock["images"]}
    for path, name, service in services():
        image = service.get("image")
        if image is None:
            continue
        assert "@sha256:" in image, f"{path.name}:{name} is not pinned"
        assert image.rsplit("@", 1)[1] in locked, f"{path.name}:{name} is not in images.lock.json"


def test_INV_002_optional_services_are_labeled_and_profile_gated() -> None:
    for path, name, service in services():
        labels = service.get("labels", {})
        assert labels.get("io.morpheus.project") == "${MORPHEUS_PROJECT_ID:-morpheus}", name
        assert service.get("profiles"), f"{path.name}:{name} must be opt-in"


def test_SEC_007_optional_ports_are_loopback_and_docker_socket_is_absent() -> None:
    for path, name, service in services():
        for port in service.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), f"{path.name}:{name} exposes a host port"
        for volume in service.get("volumes", []):
            assert "/var/run/docker.sock" not in str(volume)


def test_VOICE_004_cpu_profile_has_no_gpu_device_request() -> None:
    voice = yaml.safe_load((ROOT / "deploy/compose.voice.yaml").read_text(encoding="utf-8"))
    for service in voice["services"].values():
        assert "gpus" not in service
        assert "devices" not in service


def test_FLOW_002_workflow_templates_have_no_credentials_or_host_specific_values() -> None:
    for template in (ROOT / "deploy/config/n8n/templates").glob("*.json"):
        value = template.read_text(encoding="utf-8").lower()
        assert "api_key" not in value
        assert "127.0.0.1" not in value
        assert "qwen36-27b-nvfp4" not in value
