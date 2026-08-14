"""POSIX (Linux and macOS) native platform adapters for PLAT-002."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess  # nosec B404
from pathlib import Path

from morpheus.adapters.platform.base import (
    assert_owned_resolved,
    bounded_service_name,
    constant_time_equal,
    fsync_directory,
    restrict_private_file,
)
from morpheus.core.discovery import UtilizationSnapshot
from morpheus.core.paths import OwnedPathError, OwnedPathResolver

_SYSTEMCTL = ["systemctl", "--no-pager"]
_LAUNCHCTL = ["/bin/launchctl", "print"]


class PosixOwnedPath:
    """Reject symbolic links and enforce the owned boundary with POSIX semantics."""

    def assert_owned(self, resolver: OwnedPathResolver, path: Path) -> None:
        assert_owned_resolved(resolver, path)


class PosixSecretStore:
    """Owner-only private store; protection is OS account isolation on POSIX."""

    def __init__(self, store_dir: Path) -> None:
        self._store_dir = store_dir
        store_dir.mkdir(parents=True, exist_ok=True)
        restrict_private_file(store_dir)

    def _entry(self, name: str) -> Path:
        bounded_service_name(name)
        return self._store_dir / f"{name}.secret"

    def store(self, name: str, value: bytes) -> None:
        entry = self._entry(name)
        entry.write_bytes(value)
        restrict_private_file(entry)

    def exists(self, name: str) -> bool:
        return self._entry(name).is_file()

    def verify(self, name: str, value: bytes) -> bool:
        if not self.exists(name):
            return False
        return constant_time_equal(self._entry(name).read_bytes(), value)

    def remove(self, name: str) -> None:
        with contextlib.suppress(FileNotFoundError):
            self._entry(name).unlink()


class PosixProcessSupervision:
    """Terminate the whole process group and probe existence without noise."""

    def alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def terminate_tree(self, pid: int) -> None:
        killpg = getattr(os, "killpg", None)
        if killpg is None:
            os.kill(pid, getattr(signal, "SIGKILL", 9))
            return
        try:
            killpg(pid, getattr(signal, "SIGKILL", 9))
        except ProcessLookupError:
            os.kill(pid, getattr(signal, "SIGKILL", 9))
        except PermissionError:
            os.kill(pid, getattr(signal, "SIGKILL", 9))


class PosixServiceLifecycle:
    """Bounded service names through systemctl on Linux."""

    def status(self, name: str) -> str:
        name = bounded_service_name(name)
        result = subprocess.run(  # noqa: S603  # nosec B603
            [*_SYSTEMCTL, "status", name],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip() or f"service {name} not found"

    def start(self, name: str) -> None:
        name = bounded_service_name(name)
        result = subprocess.run(  # noqa: S603  # nosec B603
            [*_SYSTEMCTL, "start", name],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"cannot start service {name}: {result.stderr.strip()}")

    def stop(self, name: str) -> None:
        name = bounded_service_name(name)
        result = subprocess.run(  # noqa: S603  # nosec B603
            [*_SYSTEMCTL, "stop", name],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"cannot stop service {name}: {result.stderr.strip()}")


class PosixDurableReplacement:
    """Atomic rename plus a durable directory flush on POSIX."""

    def replace(self, resolver: OwnedPathResolver, destination: Path, staged: Path) -> None:
        owned_staged = assert_owned_resolved(resolver, staged)
        owned_destination = assert_owned_resolved(resolver, destination)
        if not owned_staged.is_file():
            raise OwnedPathError("staged replacement must be a regular file")
        os.replace(owned_staged, owned_destination)
        fsync_directory(owned_destination.parent)


class PosixHardwareTelemetry:
    """Snapshot volatile utilization through the read-only allowlist."""

    def snapshot(self) -> UtilizationSnapshot:
        from morpheus.adapters.host.collectors import PortableHostCollector

        return PortableHostCollector().collect().utilization
