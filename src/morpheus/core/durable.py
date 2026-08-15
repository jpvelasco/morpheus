"""Durable filesystem primitives shared by every owned-workspace writer.

Single canonical implementation of atomic replace, file/directory fsync,
and durable byte writing; modules that persist Morpheus-owned state must
go through these helpers so crash behavior is uniform and testable.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def fsync_file(path: Path) -> None:
    """Flush file data; Windows has no read-only fsync counterpart."""
    if os.name == "nt":
        return
    with path.open("rb") as stream:
        os.fsync(stream.fileno())


def fsync_directory(path: Path) -> None:
    """Flush directory metadata; Windows flushes it through file fsync."""
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_durable(destination: Path, data: bytes) -> None:
    """Create ``destination`` exclusively and flush its bytes."""
    with destination.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def atomic_replace(destination: Path, data: bytes) -> None:
    """Atomically write ``data`` at ``destination`` and flush the parent."""
    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb", delete=False, dir=parent, prefix=f".{destination.name}.tmp-"
    ) as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
        temporary = Path(stream.name)
    try:
        os.replace(temporary, destination)
        fsync_directory(parent)
    finally:
        temporary.unlink(missing_ok=True)


def write_json_atomic(destination: Path, payload: dict[str, Any]) -> None:
    """Atomically persist a canonical JSON document."""
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    atomic_replace(destination, data)
