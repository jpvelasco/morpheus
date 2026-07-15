from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "validation" / "vm" / "ubuntu-26.04-amd64.json"
USER_DATA_PATH = ROOT / "validation" / "vm" / "cloud-init" / "user-data.yaml.in"
META_DATA_PATH = ROOT / "validation" / "vm" / "cloud-init" / "meta-data.yaml"
CLONE_PATH = ROOT / "validation" / "vm" / "clone.sh"


@pytest.mark.contract
def test_vm_manifest_pins_an_official_image_and_isolated_guest() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    image = manifest["image"]
    assert image["url"].startswith("https://cloud-images.ubuntu.com/releases/resolute/release/")
    assert image["url"].endswith("ubuntu-26.04-server-cloudimg-amd64.img")
    assert re.fullmatch(r"[0-9a-f]{64}", image["sha256"])
    assert re.fullmatch(r"[0-9]{8}", image["release_build"])

    guest = manifest["guest"]
    assert guest == {
        "name": "morpheus-validation-base",
        "vcpus": 12,
        "memory_mib": 32768,
        "disk_gib": 160,
        "firmware": "uefi",
        "cloud_init_transport": "virtio",
        "network": "default",
        "storage_pool": "default",
        "graphics": "none",
        "gpu": False,
        "host_shares": False,
        "host_docker_socket": False,
        "autostart": False,
        "template_identity_cleaned": True,
        "concurrent_clones": True,
    }


@pytest.mark.contract
def test_cloud_init_is_secret_free_and_installs_declared_prerequisites() -> None:
    text = USER_DATA_PATH.read_text(encoding="utf-8")
    config = yaml.safe_load(text)

    assert config["ssh_pwauth"] is False
    assert config["disable_root"] is True
    assert config["package_update"] is True
    assert config["package_upgrade"] is False
    assert config["timezone"] == "Etc/UTC"
    assert text.count("__SSH_PUBLIC_KEY__") == 1
    assert "PRIVATE KEY" not in text
    assert "password:" not in text.lower()

    packages = set(config["packages"])
    assert {
        "ca-certificates",
        "chrony",
        "curl",
        "docker.io",
        "docker-compose-v2",
        "docker-buildx",
        "git",
        "jq",
        "make",
        "openssh-server",
        "openssl",
        "pipx",
        "qemu-guest-agent",
        "rsync",
    } <= packages

    users = {user["name"]: user for user in config["users"] if isinstance(user, dict)}
    validation_user = users["operator"]
    assert validation_user["lock_passwd"] is True
    assert validation_user["ssh_authorized_keys"] == ["__SSH_PUBLIC_KEY__"]

    files = {item["path"]: item["content"] for item in config["write_files"]}
    apt_policy = files["/etc/apt/apt.conf.d/20auto-upgrades"]
    assert 'APT::Periodic::Update-Package-Lists "0";' in apt_policy
    assert 'APT::Periodic::Unattended-Upgrade "0";' in apt_policy

    commands = [" ".join(command) for command in config["runcmd"]]
    assert "systemctl disable --now apt-daily.timer apt-daily-upgrade.timer" in commands
    assert "systemctl enable --now chrony.service" in commands

    template_seal = files["/usr/local/sbin/morpheus-validation-template-seal"]
    assert "cloud-init clean --logs --machine-id --seed --configs ssh_config" in template_seal
    assert "docker buildx version" in template_seal
    assert "systemctl poweroff" in template_seal


@pytest.mark.contract
def test_cloud_init_identity_is_explicit() -> None:
    metadata = yaml.safe_load(META_DATA_PATH.read_text(encoding="utf-8"))

    assert metadata == {
        "instance-id": "morpheus-validation-base-20260715",
        "local-hostname": "morpheus-validation-base",
    }


@pytest.mark.contract
def test_clone_helper_protects_the_sealed_base_and_force_copies_the_disk() -> None:
    script = CLONE_PATH.read_text(encoding="utf-8")

    assert "set -euo pipefail" in script
    assert "^morpheus-validation-[a-z0-9]" in script
    assert '[[ "${base_state}" == "shut off" ]]' in script
    assert "--force-copy vda" in script
    assert "--disk readonly=off" in script
    assert "cloud-localds" in script
    assert 'seed_volume="${scenario}-seed.iso"' in script
    assert "virsh attach-disk" in script
    assert '[[ "${base_path}" != "${clone_path}" ]]' in script
    assert "--replace" not in script
    assert "--preserve-data" not in script


@pytest.mark.contract
def test_clone_cloud_init_regenerates_identity_without_package_changes() -> None:
    metadata = (ROOT / "validation" / "vm" / "cloud-init" / "clone-meta-data.yaml.in").read_text(
        encoding="utf-8"
    )
    user_data = yaml.safe_load(
        (ROOT / "validation" / "vm" / "cloud-init" / "clone-user-data.yaml").read_text(
            encoding="utf-8"
        )
    )

    assert metadata == ("instance-id: __SCENARIO_NAME__\nlocal-hostname: __SCENARIO_NAME__\n")
    assert user_data["preserve_hostname"] is False
    assert user_data["ssh_deletekeys"] is True
    assert set(user_data["ssh_genkeytypes"]) == {"ed25519", "ecdsa", "rsa"}
    assert user_data["package_update"] is False
    assert user_data["package_upgrade"] is False
