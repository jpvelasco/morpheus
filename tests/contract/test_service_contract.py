"""Contract gates: backend service lifecycle, health gating, and durability (PLAT-003)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from morpheus.core.packages import PackageVersion, build_package, package_digest, package_file_name
from morpheus.core.service import (
    SERVICE_FAILED,
    SERVICE_HEALTHY,
    SERVICE_NONE,
    BackendServiceStore,
    ServiceError,
    ServiceHealth,
)

pytestmark = pytest.mark.contract
PLATFORM = "linux-x86_64"


class RecordingProbe:
    """Records every probe for evidence of the starting -> healthy/failed transitions."""

    def __init__(self, healthy_for: set[str] | None = None) -> None:
        self.healthy_for = healthy_for or set()
        self.calls: list[tuple[str, PackageVersion]] = []

    def probe(self, service_name: str, version: PackageVersion) -> ServiceHealth:
        self.calls.append((service_name, version))
        healthy = str(version) in self.healthy_for
        return ServiceHealth(healthy=healthy, summary="ok" if healthy else "boom")


def package(tmp_path: Path, *, name: str = "backend", version: str = "1.0.0") -> Path:
    source = tmp_path / "staging"
    source.mkdir(exist_ok=True)
    (source / "app").mkdir(exist_ok=True)
    (source / "app" / "main.py").write_bytes(b"def main():\n    return 0\n")
    destination = tmp_path / "artifacts"
    destination.mkdir(exist_ok=True)
    parsed = PackageVersion.parse(version)
    return build_package(
        source,
        destination / package_file_name(name, parsed, PLATFORM),
        name=name,
        version=parsed,
        platform=PLATFORM,
    )


def store(tmp_path: Path, *, root: str = "root", **overrides) -> BackendServiceStore:
    fields = {"owned_root": tmp_path / root, "platform_tag": PLATFORM}
    fields.update(overrides)
    owned = fields["owned_root"]
    owned.mkdir(exist_ok=True)
    return BackendServiceStore(**fields)


def test_install_gate_verifies_then_health_gates(tmp_path) -> None:
    """Install gate: verify (digest + scan + platform) before any extraction; probe first."""
    probe = RecordingProbe(healthy_for={"1.0.0"})
    manager = store(tmp_path, root="good", probe=probe)
    artifact = package(tmp_path)
    state = manager.install("backend", artifact, expected_artifact_digest=package_digest(artifact))
    assert state.status == SERVICE_HEALTHY
    assert state.current == PackageVersion(1, 0, 0)
    assert probe.calls == [("backend", PackageVersion(1, 0, 0))]
    installed_dir = tmp_path / "good" / "services" / "backend" / "versions" / "1.0.0"
    assert (installed_dir / "app" / "main.py").read_bytes() == b"def main():\n    return 0\n"
    assert (tmp_path / "good" / "services" / "backend" / "state.json").is_file()

    manager = store(tmp_path, root="bad-digest", probe=RecordingProbe())
    with pytest.raises(ServiceError, match="digest"):
        manager.install("backend", artifact, expected_artifact_digest="0" * 64)

    manager = store(tmp_path, root="bad-health", probe=RecordingProbe())
    with pytest.raises(ServiceError, match="health gate"):
        manager.install("backend", artifact)
    assert manager.status("backend").status == SERVICE_NONE
    assert not (tmp_path / "bad-health" / "services" / "backend" / "versions" / "1.0.0").exists()


def test_restart_gate_health_gates_an_installed_service(tmp_path) -> None:
    """Restart gate: a healthy probe confirms the restart; a failure leaves failed state."""
    probe = RecordingProbe(healthy_for={"1.0.0"})
    manager = store(tmp_path, probe=probe)
    manager.install("backend", package(tmp_path))
    assert manager.restart("backend").status == SERVICE_HEALTHY
    assert manager.restart("backend").status == SERVICE_HEALTHY
    assert len(probe.calls) == 3

    manager = store(tmp_path, root="failing", probe=RecordingProbe(healthy_for={"1.0.0"}))
    manager.install("backend", package(tmp_path))
    manager._probe = RecordingProbe()
    with pytest.raises(ServiceError, match="health gate"):
        manager.restart("backend")
    assert manager.status("backend").status == SERVICE_FAILED


def test_upgrade_gate_promotes_or_rolls_back_with_evidence(tmp_path) -> None:
    """Upgrade gate: success promotes previous/current; failure rolls back and discards."""
    probe = RecordingProbe(healthy_for={"1.0.0", "1.1.0"})
    manager = store(tmp_path, root="promote", probe=probe)
    manager.install("backend", package(tmp_path))
    state = manager.upgrade("backend", package(tmp_path, version="1.1.0"))
    assert state.current == PackageVersion(1, 1, 0)
    assert state.previous == PackageVersion(1, 0, 0)
    assert (tmp_path / "promote" / "services" / "backend" / "versions" / "1.1.0").is_dir()

    manager = store(tmp_path, root="rollback", probe=RecordingProbe(healthy_for={"1.0.0"}))
    manager.install("backend", package(tmp_path))
    with pytest.raises(ServiceError, match="rolled back"):
        manager.upgrade("backend", package(tmp_path, version="1.1.0"))
    state = manager.status("backend")
    assert state.status == SERVICE_HEALTHY
    assert state.current == PackageVersion(1, 0, 0)
    assert state.previous is None
    assert not (tmp_path / "rollback" / "services" / "backend" / "versions" / "1.1.0").exists()

    manager = store(tmp_path, root="stale", probe=RecordingProbe(healthy_for={"1.0.0", "1.1.0"}))
    manager.install("backend", package(tmp_path))
    with pytest.raises(ServiceError, match="newer"):
        manager.upgrade("backend", package(tmp_path, version="1.0.0"))


def test_rollback_gate_swaps_and_re_verifies(tmp_path) -> None:
    """Rollback gate: returns to the recorded previous version and probes it."""
    probe = RecordingProbe(healthy_for={"1.0.0", "1.1.0"})
    manager = store(tmp_path, root="swaps", probe=probe)
    manager.install("backend", package(tmp_path))
    manager.upgrade("backend", package(tmp_path, version="1.1.0"))
    state = manager.rollback("backend")
    assert state.current == PackageVersion(1, 0, 0)
    assert state.previous == PackageVersion(1, 1, 0)
    assert probe.calls[-1] == ("backend", PackageVersion(1, 0, 0))

    manager = store(tmp_path, root="single", probe=RecordingProbe(healthy_for={"1.0.0"}))
    manager.install("backend", package(tmp_path))
    with pytest.raises(ServiceError, match="no previous"):
        manager.rollback("backend")


def test_uninstall_gate_removes_evidence_cleanly(tmp_path) -> None:
    """Uninstall gate: service dir and version trees are gone; state returns to none."""
    manager = store(tmp_path, probe=RecordingProbe(healthy_for={"1.0.0"}))
    manager.install("backend", package(tmp_path))
    manager.uninstall("backend")
    assert manager.status("backend").status == SERVICE_NONE
    assert manager.list() == ()
    service_dir = tmp_path / "root" / "services" / "backend"
    assert not (service_dir / "versions").exists()
    with pytest.raises(ServiceError, match="not installed"):
        manager.uninstall("backend")


def test_lifecycle_is_durable_across_store_instances(tmp_path) -> None:
    """Durability gate: state and artifacts survive re-instantiation of the store."""
    probe = RecordingProbe(healthy_for={"1.0.0", "1.1.0"})
    store(tmp_path, probe=probe).install("backend", package(tmp_path))
    store(tmp_path, probe=probe).upgrade("backend", package(tmp_path, version="1.1.0"))
    state = store(tmp_path, probe=probe).status("backend")
    assert state.status == SERVICE_HEALTHY
    assert state.current == PackageVersion(1, 1, 0)
    assert state.previous == PackageVersion(1, 0, 0)
    service_dir = tmp_path / "root" / "services" / "backend"
    with (service_dir / "state.json").open(encoding="utf-8") as handle:
        raw = json.load(handle)
    assert raw["schema_version"] == 1


def test_ownership_bounds_reject_forged_or_foreign_content(tmp_path) -> None:
    """Ownership gate: names are bounded, versions immutable, foreign platform rejected."""
    manager = store(tmp_path, probe=RecordingProbe(healthy_for={"1.0.0"}))
    with pytest.raises(ServiceError, match="bounded"):
        manager.status("../escape")
    with pytest.raises(ServiceError, match="bounded"):
        manager.install("Not A Name", package(tmp_path))
    with pytest.raises(ServiceError, match="does not match"):
        manager.install("other", package(tmp_path))

    manager = store(
        tmp_path,
        root="win",
        platform_tag="win32-x86_64",
        probe=RecordingProbe(healthy_for={"1.0.0"}),
    )
    with pytest.raises(ServiceError, match="platform"):
        manager.install("backend", package(tmp_path))
