"""Typed platform ports (PLAT-002): owned paths, secrets, processes, services."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from morpheus.core.discovery import UtilizationSnapshot
from morpheus.core.paths import OwnedPathResolver


class OwnedPathPort(Protocol):
    """Enforce Morpheus-owned filesystem boundaries on the native platform."""

    def assert_owned(self, resolver: OwnedPathResolver, path: Path) -> None:
        """Raise if ``path`` is not a real directory or file inside the owned root."""
        ...


class SecretStorePort(Protocol):
    """Protect secrets without ever returning stored values."""

    def store(self, name: str, value: bytes) -> None:
        """Persist a secret under a bounded name with platform-native protection."""
        ...

    def exists(self, name: str) -> bool:
        """Report whether a named secret exists without revealing it."""
        ...

    def verify(self, name: str, value: bytes) -> bool:
        """Return whether ``value`` matches the stored secret, in constant time."""
        ...

    def remove(self, name: str) -> None:
        """Delete a named secret and its residual artifacts."""
        ...


class ProcessSupervisionPort(Protocol):
    """Supervise and terminate process trees without leaving children behind."""

    def alive(self, pid: int) -> bool:
        """Return whether the process identifier still exists."""
        ...

    def terminate_tree(self, pid: int) -> None:
        """Terminate the process and its entire native process tree."""
        ...


class ServiceLifecyclePort(Protocol):
    """Manage named services through the native service manager."""

    def status(self, name: str) -> str:
        """Return the native service status text without raising on absence."""
        ...

    def start(self, name: str) -> None:
        """Start a bounded service name; raise when the operation is not allowed."""
        ...

    def stop(self, name: str) -> None:
        """Stop a bounded service name; raise when the operation is not allowed."""
        ...


class DurableReplacementPort(Protocol):
    """Atomically replace a destination with staged content under the owned root."""

    def replace(self, resolver: OwnedPathResolver, destination: Path, staged: Path) -> None:
        """Durably swap ``staged`` over ``destination``; both must be owned paths."""
        ...


class HardwareTelemetryPort(Protocol):
    """Snapshot volatile hardware utilization through the read-only allowlist."""

    def snapshot(self) -> UtilizationSnapshot: ...
