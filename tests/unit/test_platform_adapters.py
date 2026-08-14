"""Unit tests for the PLAT-002 native platform adapters."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from morpheus.adapters.platform import platform_ports
from morpheus.adapters.platform.base import (
    assert_owned_resolved,
    bounded_service_name,
    constant_time_equal,
    restrict_private_file,
)
from morpheus.adapters.platform.darwin import DarwinServiceLifecycle
from morpheus.adapters.platform.posix import (
    PosixDurableReplacement,
    PosixOwnedPath,
    PosixProcessSupervision,
    PosixSecretStore,
    PosixServiceLifecycle,
)
from morpheus.adapters.platform.windows import (
    WindowsDurableReplacement,
    WindowsOwnedPath,
    WindowsProcessSupervision,
    WindowsSecretStore,
    WindowsServiceLifecycle,
    _windll,
)
from morpheus.core.paths import OwnedPathError, OwnedPathResolver


def _resolver(root: Path) -> OwnedPathResolver:
    return OwnedPathResolver(root)


class TestBaseHelpers:
    def test_bounded_service_name_accepts_valid_names(self) -> None:
        assert bounded_service_name("morpheus-api") == "morpheus-api"
        assert bounded_service_name("a") == "a"

    @pytest.mark.parametrize(
        "name",
        ["", "with space", "semi;colon", "dollar$", "sla/sh", "../up", "-lead", "x" * 65],
    )
    def test_bounded_service_name_rejects_unsafe_names(self, name: str) -> None:
        with pytest.raises(ValueError):
            bounded_service_name(name)

    def test_constant_time_equal(self) -> None:
        assert constant_time_equal(b"same", b"same")
        assert not constant_time_equal(b"a", b"b")

    def test_owned_resolved_rejects_symlink(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        resolver = _resolver(tmp_path)
        target = tmp_path / "target"
        target.write_text("x")
        monkeypatch.setattr(Path, "is_symlink", lambda self: True)
        with pytest.raises(OwnedPathError):
            assert_owned_resolved(resolver, target)

    def test_owned_resolved_accepts_plain_owned_file(self, tmp_path: Path) -> None:
        resolver = _resolver(tmp_path)
        owned = tmp_path / "owned.txt"
        owned.write_text("x")
        assert assert_owned_resolved(resolver, owned) == owned

    @pytest.mark.skipif(os.name != "posix", reason="POSIX mode semantics")
    def test_restrict_private_file_narrows_mode(self, tmp_path: Path) -> None:
        private = tmp_path / "private"
        private.write_bytes(b"x")
        os.chmod(private, 0o644)
        restrict_private_file(private)
        assert private.stat().st_mode & 0o777 == 0o600


class TestPosixOwnedPath:
    def test_accepts_owned_path(self, tmp_path: Path) -> None:
        owned = tmp_path / "file"
        owned.write_text("x")
        PosixOwnedPath().assert_owned(_resolver(tmp_path), owned)

    def test_rejects_escape(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "is_symlink", lambda self: False)
        outside = tmp_path.parent / "outside"
        outside.mkdir(exist_ok=True)
        with pytest.raises(OwnedPathError):
            PosixOwnedPath().assert_owned(_resolver(tmp_path), outside / "file")


class TestSecretStores:
    def test_posix_secret_roundtrip(self, tmp_path: Path) -> None:
        store = PosixSecretStore(tmp_path / "secrets")
        store.store("api-key", b"secret")
        assert store.exists("api-key")
        assert store.verify("api-key", b"secret")
        assert not store.verify("api-key", b"other")
        store.remove("api-key")
        assert not store.exists("api-key")
        assert not store.verify("api-key", b"secret")

    def test_posix_secret_rejects_bad_name(self, tmp_path: Path) -> None:
        store = PosixSecretStore(tmp_path / "secrets")
        with pytest.raises(ValueError):
            store.store("../bad", b"x")

    def test_windows_secret_raises_when_dpapi_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("morpheus.adapters.platform.windows._windll", lambda: None)
        store = WindowsSecretStore(tmp_path / "secrets")
        with pytest.raises(RuntimeError):
            store.store("api-key", b"secret")

    @pytest.mark.skipif(_windll() is None, reason="requires Windows DPAPI")
    def test_windows_secret_roundtrip_with_real_dpapi(self, tmp_path: Path) -> None:
        store = WindowsSecretStore(tmp_path / "secrets")
        store.store("api-key", b"secret")
        assert store.exists("api-key")
        assert store.verify("api-key", b"secret")
        assert not store.verify("api-key", b"other")
        store.remove("api-key")
        assert not store.exists("api-key")


class TestWindowsOwnedPath:
    def test_rejects_junction(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        owned = tmp_path / "file"
        owned.write_text("x")
        monkeypatch.setattr(Path, "is_symlink", lambda self: False)
        monkeypatch.setattr(Path, "is_junction", lambda self: True)
        with pytest.raises(OwnedPathError):
            WindowsOwnedPath().assert_owned(_resolver(tmp_path), owned)

    def test_accepts_plain_owned_path(self, tmp_path: Path) -> None:
        owned = tmp_path / "file"
        owned.write_text("x")
        WindowsOwnedPath().assert_owned(_resolver(tmp_path), owned)


def _run_script(
    stdout: str = "", stderr: str = "", returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class TestProcessSupervision:
    def _fake_native_tools(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("morpheus.adapters.platform.windows._native_tool", lambda name: name)

    def test_windows_alive_from_tasklist(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._fake_native_tools(monkeypatch)
        monkeypatch.setattr(
            "morpheus.adapters.platform.windows.subprocess.run",
            lambda *a, **k: _run_script("   1234 services.exe"),
        )
        assert WindowsProcessSupervision().alive(1234)
        monkeypatch.setattr(
            "morpheus.adapters.platform.windows.subprocess.run",
            lambda *a, **k: _run_script("no tasks"),
        )
        assert not WindowsProcessSupervision().alive(1234)

    def test_windows_terminate_tree(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[list[str]] = []
        self._fake_native_tools(monkeypatch)
        monkeypatch.setattr(
            "morpheus.adapters.platform.windows.subprocess.run",
            lambda args, **k: calls.append(list(args)) or _run_script(),
        )
        WindowsProcessSupervision().terminate_tree(1234)
        assert calls == [["taskkill", "/PID", "1234", "/T", "/F"]]

    def test_windows_terminate_tree_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._fake_native_tools(monkeypatch)
        monkeypatch.setattr(
            "morpheus.adapters.platform.windows.subprocess.run",
            lambda args, **k: _run_script(stderr="access denied", returncode=5),
        )
        with pytest.raises(RuntimeError):
            WindowsProcessSupervision().terminate_tree(1234)

    def test_windows_terminate_tree_missing_pid_is_ok(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._fake_native_tools(monkeypatch)
        monkeypatch.setattr(
            "morpheus.adapters.platform.windows.subprocess.run",
            lambda args, **k: _run_script(returncode=128),
        )
        WindowsProcessSupervision().terminate_tree(99999)

    def test_posix_alive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import morpheus.adapters.platform.posix as module

        def raise_error(error: type[BaseException]) -> object:
            def _raise(*args: object) -> None:
                raise error()

            return _raise

        monkeypatch.setattr(module, "os", SimpleNamespace(kill=lambda pid, sig: None))
        assert PosixProcessSupervision().alive(1234)
        monkeypatch.setattr(module, "os", SimpleNamespace(kill=raise_error(ProcessLookupError)))
        assert not PosixProcessSupervision().alive(1234)
        monkeypatch.setattr(module, "os", SimpleNamespace(kill=raise_error(PermissionError)))
        assert PosixProcessSupervision().alive(1234)

    def test_posix_terminate_tree(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import morpheus.adapters.platform.posix as module

        def raise_error(error: type[BaseException]) -> object:
            def _raise(*args: object) -> None:
                raise error()

            return _raise

        calls: list[tuple[str, int]] = []
        monkeypatch.setattr(
            module, "os", SimpleNamespace(killpg=lambda pid, sig: calls.append(("pg", pid)))
        )
        PosixProcessSupervision().terminate_tree(1234)
        assert calls == [("pg", 1234)]

        monkeypatch.setattr(
            module,
            "os",
            SimpleNamespace(
                killpg=raise_error(ProcessLookupError),
                kill=lambda pid, sig: calls.append(("kill", pid)),
            ),
        )
        PosixProcessSupervision().terminate_tree(1234)
        assert calls[-1] == ("kill", 1234)


class TestServiceLifecycle:
    def _fake_native_tools(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("morpheus.adapters.platform.windows._native_tool", lambda name: name)

    def test_windows_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._fake_native_tools(monkeypatch)
        monkeypatch.setattr(
            "morpheus.adapters.platform.windows.subprocess.run",
            lambda args, **k: _run_script(stdout="SERVICE_NAME: foo"),
        )
        assert "SERVICE_NAME: foo" in WindowsServiceLifecycle().status("foo")

    def test_windows_start_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._fake_native_tools(monkeypatch)
        monkeypatch.setattr(
            "morpheus.adapters.platform.windows.subprocess.run",
            lambda args, **k: _run_script(returncode=1062),
        )
        with pytest.raises(RuntimeError):
            WindowsServiceLifecycle().start("foo")

    def test_windows_bad_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(ValueError):
            WindowsServiceLifecycle().status("a;b")

    def test_posix_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "morpheus.adapters.platform.posix.subprocess.run",
            lambda args, **k: _run_script(stdout="● foo.service"),
        )
        assert "foo.service" in PosixServiceLifecycle().status("foo")

    def test_posix_stop_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "morpheus.adapters.platform.posix.subprocess.run",
            lambda args, **k: _run_script(stderr="denied", returncode=1),
        )
        with pytest.raises(RuntimeError):
            PosixServiceLifecycle().stop("foo")

    def test_darwin_status_readonly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "morpheus.adapters.platform.darwin.subprocess.run",
            lambda args, **k: _run_script(stdout="state = running"),
        )
        assert "running" in DarwinServiceLifecycle().status("foo")

    def test_darwin_lifecycle_mutations_denied(self) -> None:
        with pytest.raises(RuntimeError):
            DarwinServiceLifecycle().start("foo")
        with pytest.raises(RuntimeError):
            DarwinServiceLifecycle().stop("foo")


class TestDurableReplacement:
    def test_posix_replace_swaps_content(self, tmp_path: Path) -> None:
        resolver = _resolver(tmp_path)
        destination = tmp_path / "current"
        destination.write_text("old")
        staged = tmp_path / "staged"
        staged.write_text("new")
        PosixDurableReplacement().replace(resolver, destination, staged)
        assert destination.read_text() == "new"
        assert not staged.exists()

    def test_windows_replace_swaps_content(self, tmp_path: Path) -> None:
        resolver = _resolver(tmp_path)
        destination = tmp_path / "current"
        destination.write_text("old")
        staged = tmp_path / "staged"
        staged.write_text("new")
        WindowsDurableReplacement().replace(resolver, destination, staged)
        assert destination.read_text() == "new"

    @pytest.mark.parametrize(
        "adapter",
        [PosixDurableReplacement(), WindowsDurableReplacement()],
    )
    def test_replace_rejects_escaping_staged(self, tmp_path: Path, adapter: object) -> None:
        resolver = _resolver(tmp_path)
        destination = tmp_path / "current"
        destination.write_text("old")
        staged = tmp_path.parent / "outside-stage"
        staged.write_text("x")
        with pytest.raises(OwnedPathError):
            adapter.replace(resolver, destination, staged)

    @pytest.mark.parametrize(
        "adapter",
        [PosixDurableReplacement(), WindowsDurableReplacement()],
    )
    def test_replace_rejects_directory_staged(self, tmp_path: Path, adapter: object) -> None:
        resolver = _resolver(tmp_path)
        destination = tmp_path / "current"
        destination.write_text("old")
        staged = tmp_path / "staged-dir"
        staged.mkdir()
        with pytest.raises(OwnedPathError):
            adapter.replace(resolver, destination, staged)


class TestTelemetryPorts:
    @pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
    def test_snapshot_uses_portable_collector(
        self, platform: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import morpheus.adapters.host.collectors as collectors

        sentinel = SimpleNamespace(utilization="util")
        fake = SimpleNamespace(collect=lambda: SimpleNamespace(utilization=sentinel))
        monkeypatch.setattr(collectors, "PortableHostCollector", lambda: fake)
        bundle = platform_ports(platform)
        assert bundle.telemetry.snapshot() is sentinel


class TestSelection:
    def test_win32_bundle(self) -> None:
        bundle = platform_ports("win32")
        assert isinstance(bundle.owned_path, WindowsOwnedPath)
        assert isinstance(bundle.process_supervision, WindowsProcessSupervision)
        assert isinstance(bundle.service_lifecycle, WindowsServiceLifecycle)
        assert isinstance(bundle.durable_replacement, WindowsDurableReplacement)
        assert isinstance(bundle.secret_store(Path("x")), WindowsSecretStore)

    def test_darwin_bundle(self) -> None:
        bundle = platform_ports("darwin")
        from morpheus.adapters.platform.darwin import (
            DarwinDurableReplacement,
            DarwinOwnedPath,
            DarwinProcessSupervision,
            DarwinSecretStore,
            DarwinServiceLifecycle,
        )

        assert isinstance(bundle.owned_path, DarwinOwnedPath)
        assert isinstance(bundle.process_supervision, DarwinProcessSupervision)
        assert isinstance(bundle.service_lifecycle, DarwinServiceLifecycle)
        assert isinstance(bundle.durable_replacement, DarwinDurableReplacement)
        assert isinstance(bundle.secret_store(Path("x")), DarwinSecretStore)

    def test_posix_bundle(self) -> None:
        bundle = platform_ports("linux")
        assert isinstance(bundle.owned_path, PosixOwnedPath)
        assert isinstance(bundle.process_supervision, PosixProcessSupervision)
        assert isinstance(bundle.service_lifecycle, PosixServiceLifecycle)
        assert isinstance(bundle.durable_replacement, PosixDurableReplacement)
        assert isinstance(bundle.secret_store(Path("x")), PosixSecretStore)
