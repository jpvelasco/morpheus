"""macOS native platform adapters for PLAT-002 (honest unsupported lanes)."""

from __future__ import annotations

import contextlib
import os
import subprocess  # nosec B404
from pathlib import Path

from morpheus.adapters.platform.base import (
    assert_owned_resolved,
    bounded_service_name,
    constant_time_equal,
    restrict_private_file,
)
from morpheus.core.discovery import UtilizationSnapshot
from morpheus.core.paths import OwnedPathResolver

_LAUNCHCTL = ["/bin/launchctl", "print"]


class DarwinOwnedPath:
    """Reject symbolic links from the owned root with POSIX semantics."""

    def assert_owned(self, resolver: OwnedPathResolver, path: Path) -> None:
        assert_owned_resolved(resolver, path)


class DarwinSecretStore:
    """Owner-only private store; Keychain integration is a future lane."""

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


class DarwinProcessSupervision:
    """Terminate the whole process group; identical to POSIX semantics."""

    def alive(self, pid: int) -> bool:
        from morpheus.adapters.platform.posix import PosixProcessSupervision

        return PosixProcessSupervision().alive(pid)

    def terminate_tree(self, pid: int) -> None:
        from morpheus.adapters.platform.posix import PosixProcessSupervision

        PosixProcessSupervision().terminate_tree(pid)


class DarwinServiceLifecycle:
    """Read-only launchd inspection; start and stop are not granted."""

    def status(self, name: str) -> str:
        name = bounded_service_name(name)
        uid = getattr(os, "getuid", lambda: -1)()
        result = subprocess.run(  # noqa: S603  # nosec B603
            [*_LAUNCHCTL, f"gui/{uid}/{name}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip() or f"service {name} not found"

    def start(self, name: str) -> None:
        raise RuntimeError("launchd start is not granted to Morpheus")

    def stop(self, name: str) -> None:
        raise RuntimeError("launchd stop is not granted to Morpheus")


class DarwinDurableReplacement:
    """Atomic rename plus a durable directory flush."""

    def replace(self, resolver: OwnedPathResolver, destination: Path, staged: Path) -> None:
        from morpheus.adapters.platform.posix import PosixDurableReplacement

        PosixDurableReplacement().replace(resolver, destination, staged)


class DarwinHardwareTelemetry:
    """Snapshot volatile utilization through the read-only allowlist."""

    def snapshot(self) -> UtilizationSnapshot:
        from morpheus.adapters.host.collectors import PortableHostCollector

        return PortableHostCollector().collect().utilization
