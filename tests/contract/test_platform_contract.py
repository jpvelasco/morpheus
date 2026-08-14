"""PLAT-002 contracts: every platform surface is typed, bounded, and honest."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from morpheus.adapters.platform import PlatformPorts, platform_ports
from morpheus.core.paths import OwnedPathError, OwnedPathResolver

BUNDLES = [
    pytest.param("win32", id="windows"),
    pytest.param("darwin", id="macos"),
    pytest.param("linux", id="linux"),
]


def _secret_store(bundle: PlatformPorts, tmp_path: Path):
    return bundle.secret_store(tmp_path / "secrets")


@pytest.mark.parametrize("platform", BUNDLES)
class TestTypedSurface:
    def test_bundle_exposes_all_six_ports(self, platform: str) -> None:
        bundle = platform_ports(platform)
        for name in (
            "owned_path",
            "secret_store",
            "process_supervision",
            "service_lifecycle",
            "durable_replacement",
            "telemetry",
        ):
            assert hasattr(bundle, name)
        assert callable(bundle.secret_store)

    def test_secret_store_surface_never_retrieves_values(
        self, platform: str, tmp_path: Path
    ) -> None:
        store = _secret_store(platform_ports(platform), tmp_path)
        surface = [name for name in dir(store) if not name.startswith("_")]
        for name in surface:
            assert not any(
                token in name.lower() for token in ("retrieve", "read_value", "fetch", "get_value")
            ), f"{name} looks like a value retrieval channel"

    def test_secret_roundtrip_and_cleanup(self, platform: str, tmp_path: Path) -> None:
        from morpheus.adapters.platform.windows import _windll

        store = _secret_store(platform_ports(platform), tmp_path)
        if platform == "win32" and _windll() is None:
            with pytest.raises(RuntimeError):
                store.store("contract-key", b"v")
            return
        store.store("contract-key", b"v")
        assert store.exists("contract-key")
        assert store.verify("contract-key", b"v")
        assert not store.verify("contract-key", b"x")
        store.remove("contract-key")
        assert not store.exists("contract-key")
        assert not list(tmp_path.rglob("*.secret")), "remove must clean residual artifacts"

    def test_secret_rejects_bounded_name_violations(self, platform: str, tmp_path: Path) -> None:
        store = _secret_store(platform_ports(platform), tmp_path)
        with pytest.raises(ValueError):
            store.store("../up", b"x")

    def test_owned_path_rejects_escapes(self, platform: str, tmp_path: Path) -> None:
        resolver = OwnedPathResolver(tmp_path)
        outside = tmp_path.parent / "outside"
        outside.mkdir(exist_ok=True)
        with pytest.raises(OwnedPathError):
            platform_ports(platform).owned_path.assert_owned(resolver, outside / "file")

    def test_replacement_rejects_escaping_staged(self, platform: str, tmp_path: Path) -> None:
        resolver = OwnedPathResolver(tmp_path)
        destination = tmp_path / "current"
        destination.write_text("old")
        staged = tmp_path.parent / "staged-out"
        staged.write_text("x")
        with pytest.raises(OwnedPathError):
            platform_ports(platform).durable_replacement.replace(resolver, destination, staged)

    def test_replacement_swaps_atomically(self, platform: str, tmp_path: Path) -> None:
        resolver = OwnedPathResolver(tmp_path)
        destination = tmp_path / "current"
        destination.write_text("old")
        staged = tmp_path / "staged"
        staged.write_text("new")
        platform_ports(platform).durable_replacement.replace(resolver, destination, staged)
        assert destination.read_text() == "new"
        assert not staged.exists()

    def test_process_supervision_accepts_pid_and_probes(self, platform: str) -> None:
        supervision = platform_ports(platform).process_supervision
        assert hasattr(supervision, "alive")
        assert hasattr(supervision, "terminate_tree")

    def test_service_lifecycle_bounds_names(self, platform: str) -> None:
        lifecycle = platform_ports(platform).service_lifecycle
        with pytest.raises(ValueError):
            lifecycle.status("a;b")


class TestSelectionHonesty:
    def test_linux_selection_is_posix(self) -> None:
        from morpheus.adapters.platform.posix import PosixOwnedPath

        assert isinstance(platform_ports("linux").owned_path, PosixOwnedPath)

    def test_unknown_platforms_do_not_select_windows(self) -> None:
        bundle = platform_ports("freebsd")
        assert type(bundle.owned_path).__name__ == "PosixOwnedPath"


class TestTelemetryLane:
    def test_snapshot_is_utilization_shaped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import morpheus.adapters.host.collectors as collectors

        snapshot = SimpleNamespace(captured_at="now", memory_used_bytes=1, load_average=0.5)
        fake = SimpleNamespace(collect=lambda: SimpleNamespace(utilization=snapshot))
        monkeypatch.setattr(collectors, "PortableHostCollector", lambda: fake)
        for platform in ("win32", "darwin", "linux"):
            assert platform_ports(platform).telemetry.snapshot() is snapshot
