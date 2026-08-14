"""Shared, platform-neutral helpers for the native platform adapters."""

from __future__ import annotations

import hmac
import os
import re
import stat
from pathlib import Path

from morpheus.core.paths import OwnedPathError, OwnedPathResolver

_SERVICE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def bounded_service_name(name: str) -> str:
    if not _SERVICE_NAME.fullmatch(name):
        raise ValueError("service name must be a bounded identifier")
    return name


def constant_time_equal(left: bytes, right: bytes) -> bool:
    return hmac.compare_digest(left, right)


def assert_owned_resolved(resolver: OwnedPathResolver, path: Path) -> Path:
    """Resolve a candidate against the owned root and reject link-based escapes."""
    resolved = resolver.resolve(path)
    if resolved.is_symlink():
        raise OwnedPathError("Morpheus-owned path must not be a symbolic link")
    return resolved


def restrict_private_file(path: Path) -> None:
    """Apply owner-only access to a private file; never widen permissions."""
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return
    private = mode & 0o700
    if private != mode:
        os.chmod(path, private)


def fsync_directory(directory: Path) -> None:
    """Durably flush a directory entry on platforms that permit it."""
    if os.name != "posix":
        return
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
