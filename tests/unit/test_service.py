"""Unit tests: backend service lifecycle (PLAT-003)."""

from __future__ import annotations

from pathlib import Path

import pytest

from morpheus.core.packages import PackageVersion, build_package, package_file_name
from morpheus.core.service import (
    SERVICE_FAILED,
    SERVICE_HEALTHY,
    SERVICE_NONE,
    BackendServiceState,
    BackendServiceStore,
    ServiceError,
    ServiceHealth,
)

PLATFORM = "linux-x86_64"


class FakeProbe:
    def __init__(
        self, healthy_for: set[str] | None = None, unhealthy_for: set[str] | None = None
    ) -> None:
        self.healthy_for = healthy_for or set()
        self.unhealthy_for = unhealthy_for or set()
        self.calls: list[tuple[str, PackageVersion]] = []

    def probe(self, service_name: str, version: PackageVersion) -> ServiceHealth:
        self.calls.append((service_name, version))
        healthy = str(version) in self.healthy_for and str(version) not in self.unhealthy_for
        return ServiceHealth(healthy=healthy, summary="ok" if healthy else "boom")


def package(
    tmp_path: Path,
    *,
    name: str = "backend",
    version: str = "1.0.0",
    platform: str = PLATFORM,
    files: dict[str, bytes] | None = None,
) -> Path:
    source = tmp_path / "staging"
    source.mkdir(exist_ok=True)
    for relative, data in (files or {"app/main.py": b"main"}).items():
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    destination = tmp_path / "artifacts"
    destination.mkdir(exist_ok=True)
    parsed = PackageVersion.parse(version)
    return build_package(
        source,
        destination / package_file_name(name, parsed, platform),
        name=name,
        version=parsed,
        platform=platform,
    )


def store(tmp_path: Path, *, root: str = "root", **overrides) -> BackendServiceStore:
    fields = {"owned_root": tmp_path / root, "platform_tag": PLATFORM}
    fields.update(overrides)
    root_path = fields["owned_root"]
    root_path.mkdir(exist_ok=True)
    return BackendServiceStore(**fields)


def test_install_verifies_extracts_and_health_gates(tmp_path) -> None:
    probe = FakeProbe(healthy_for={"1.0.0"})
    manager = store(tmp_path, probe=probe)
    state = manager.install("backend", package(tmp_path))
    assert state.status == SERVICE_HEALTHY
    assert state.current == PackageVersion(1, 0, 0)
    assert state.previous is None
    assert probe.calls == [("backend", PackageVersion(1, 0, 0))]
    assert (tmp_path / "root" / "services" / "backend" / "versions" / "1.0.0").is_dir()


def test_install_failure_discards_version_and_resets_state(tmp_path) -> None:
    probe = FakeProbe(healthy_for=set())
    manager = store(tmp_path, probe=probe)
    with pytest.raises(ServiceError, match="health gate"):
        manager.install("backend", package(tmp_path))
    assert not (tmp_path / "root" / "services" / "backend" / "versions" / "1.0.0").exists()
    state = manager.status("backend")
    assert state.status == SERVICE_NONE
    assert state.current is None


def test_install_rejects_second_install_and_mismatched_package(tmp_path) -> None:
    manager = store(tmp_path, probe=FakeProbe(healthy_for={"1.0.0"}))
    manager.install("backend", package(tmp_path))
    with pytest.raises(ServiceError, match="already installed"):
        manager.install("backend", package(tmp_path))

    manager = store(tmp_path, probe=FakeProbe(healthy_for={"1.0.0"}))
    with pytest.raises(ServiceError, match="does not match"):
        manager.install("other", package(tmp_path))

    manager = store(tmp_path, probe=FakeProbe(healthy_for={"1.0.0"}))
    with pytest.raises(ServiceError, match="platform"):
        manager.install("backend", package(tmp_path, platform="win32-x86_64"))


def test_install_verifies_artifact_digest(tmp_path) -> None:
    from morpheus.core.packages import package_digest

    artifact = package(tmp_path)
    manager = store(tmp_path, probe=FakeProbe(healthy_for={"1.0.0"}))
    assert (
        manager.install(
            "backend", artifact, expected_artifact_digest=package_digest(artifact)
        ).status
        == SERVICE_HEALTHY
    )

    manager = store(tmp_path, probe=FakeProbe(healthy_for={"1.0.0"}))
    with pytest.raises(ServiceError, match="digest"):
        manager.install("backend", artifact, expected_artifact_digest="0" * 64)


def test_restart_is_health_gated(tmp_path) -> None:
    manager = store(tmp_path, probe=FakeProbe(healthy_for={"1.0.0"}))
    manager.install("backend", package(tmp_path))
    assert manager.restart("backend").status == SERVICE_HEALTHY

    manager = store(tmp_path, probe=FakeProbe(healthy_for=set()))
    with pytest.raises(ServiceError, match="health gate"):
        manager.restart("backend")
    with pytest.raises(ServiceError, match="not installed"):
        manager.restart("missing")


def test_upgrade_requires_newer_version(tmp_path) -> None:
    manager = store(tmp_path, probe=FakeProbe(healthy_for={"1.0.0", "1.1.0"}))
    manager.install("backend", package(tmp_path))
    with pytest.raises(ServiceError, match="newer"):
        manager.upgrade("backend", package(tmp_path, version="1.0.0"))
    with pytest.raises(ServiceError, match="newer"):
        manager.upgrade("backend", package(tmp_path, version="0.9.0"))
    with pytest.raises(ServiceError, match="install it first"):
        store(tmp_path, root="fresh", probe=FakeProbe(healthy_for={"1.1.0"})).upgrade(
            "backend", package(tmp_path, version="1.1.0")
        )


def test_upgrade_promotes_healthy_candidate(tmp_path) -> None:
    manager = store(tmp_path, probe=FakeProbe(healthy_for={"1.0.0", "1.1.0"}))
    manager.install("backend", package(tmp_path))
    state = manager.upgrade("backend", package(tmp_path, version="1.1.0"))
    assert state.status == SERVICE_HEALTHY
    assert state.current == PackageVersion(1, 1, 0)
    assert state.previous == PackageVersion(1, 0, 0)
    assert (tmp_path / "root" / "services" / "backend" / "versions" / "1.1.0").is_dir()


def test_upgrade_failure_rolls_back_and_discards_candidate(tmp_path) -> None:
    manager = store(tmp_path, probe=FakeProbe(healthy_for={"1.0.0"}))
    manager.install("backend", package(tmp_path))
    with pytest.raises(ServiceError, match="rolled back"):
        manager.upgrade("backend", package(tmp_path, version="1.1.0"))
    state = manager.status("backend")
    assert state.status == SERVICE_HEALTHY
    assert state.current == PackageVersion(1, 0, 0)
    assert state.previous is None
    assert not (tmp_path / "root" / "services" / "backend" / "versions" / "1.1.0").exists()


def test_rollback_swaps_versions_and_is_health_gated(tmp_path) -> None:
    manager = store(tmp_path, probe=FakeProbe(healthy_for={"1.0.0", "1.1.0"}))
    manager.install("backend", package(tmp_path))
    manager.upgrade("backend", package(tmp_path, version="1.1.0"))
    state = manager.rollback("backend")
    assert state.status == SERVICE_HEALTHY
    assert state.current == PackageVersion(1, 0, 0)
    assert state.previous == PackageVersion(1, 1, 0)

    manager = store(tmp_path, root="no-previous", probe=FakeProbe(healthy_for={"1.1.0"}))
    manager.install("backend", package(tmp_path, version="1.1.0"))
    with pytest.raises(ServiceError, match="no previous"):
        manager.rollback("backend")

    manager = store(tmp_path, root="rollback-fail", probe=FakeProbe(healthy_for={"1.1.0", "1.2.0"}))
    manager.install("backend", package(tmp_path, version="1.1.0"))
    manager.upgrade("backend", package(tmp_path, version="1.2.0"))
    manager = store(
        tmp_path,
        root="rollback-fail",
        probe=FakeProbe(healthy_for={"1.2.0"}, unhealthy_for={"1.1.0"}),
    )
    with pytest.raises(ServiceError, match="health gate"):
        manager.rollback("backend")


def test_uninstall_removes_service_and_state(tmp_path) -> None:
    manager = store(tmp_path, probe=FakeProbe(healthy_for={"1.0.0"}))
    manager.install("backend", package(tmp_path))
    manager.uninstall("backend")
    state = manager.status("backend")
    assert state.status == SERVICE_NONE
    assert state.current is None
    assert not (tmp_path / "root" / "services" / "backend" / "versions").exists()
    with pytest.raises(ServiceError, match="not installed"):
        manager.uninstall("backend")


def test_state_is_durable_across_store_reinstantiations(tmp_path) -> None:
    probe = FakeProbe(healthy_for={"1.0.0", "1.1.0"})
    first = store(tmp_path, probe=probe)
    first.install("backend", package(tmp_path))
    first.upgrade("backend", package(tmp_path, version="1.1.0"))
    second = store(tmp_path, probe=probe)
    state = second.status("backend")
    assert state.current == PackageVersion(1, 1, 0)
    assert state.previous == PackageVersion(1, 0, 0)
    assert second.list() == (state,)


def test_invalid_service_names_are_rejected(tmp_path) -> None:
    manager = store(tmp_path, probe=FakeProbe())
    with pytest.raises(ServiceError, match="bounded"):
        manager.status("Bad Name")
    with pytest.raises(ServiceError, match="bounded"):
        manager.install("bad/name", package(tmp_path))


def test_state_schema_is_versioned_and_typed(tmp_path) -> None:
    assert BackendServiceState.from_json(
        BackendServiceState(
            name="backend",
            status=SERVICE_HEALTHY,
            current=PackageVersion(1, 0, 0),
            previous=None,
        ).to_json()
    ) == BackendServiceState(
        name="backend",
        status=SERVICE_HEALTHY,
        current=PackageVersion(1, 0, 0),
        previous=None,
    )
    with pytest.raises(ServiceError, match="incompatible"):
        BackendServiceState.from_json({"schema_version": 99})
    with pytest.raises(ServiceError, match="status"):
        BackendServiceState.from_json(
            {
                "schema_version": 1,
                "name": "backend",
                "status": "on-fire",
                "current": None,
                "previous": None,
            }
        )
    assert SERVICE_FAILED in {SERVICE_HEALTHY, SERVICE_NONE, SERVICE_FAILED}
