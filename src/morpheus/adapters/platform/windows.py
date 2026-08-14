"""Windows native platform adapters for PLAT-002."""

from __future__ import annotations

import contextlib
import ctypes
import os
import shutil
import subprocess  # nosec B404
from pathlib import Path
from typing import Any, ClassVar

from morpheus.adapters.platform.base import (
    assert_owned_resolved,
    bounded_service_name,
    constant_time_equal,
    restrict_private_file,
)
from morpheus.core.discovery import UtilizationSnapshot
from morpheus.core.paths import OwnedPathError, OwnedPathResolver

_ENTROPY = b"morpheus-secret-store-v1"


def _native_tool(name: str) -> str:
    resolved = shutil.which(name)
    if resolved is None:
        raise RuntimeError(f"native tool not found: {name}")
    return resolved


def _windll() -> Any:
    return getattr(ctypes, "windll", None)


def _dpapi_protect(value: bytes) -> bytes:
    """Encrypt bytes with the current Windows user scope (DPAPI)."""
    from ctypes import (
        POINTER,
        byref,
        c_int,
        c_ubyte,
        c_uint32,
        c_void_p,
        c_wchar_p,
        create_string_buffer,
    )

    windll = _windll()
    if windll is None:
        raise RuntimeError("DPAPI is unavailable on this platform")

    class _DataBlob(ctypes.Structure):
        _fields_: ClassVar[list[tuple[str, type]]] = [
            ("cbData", c_uint32),
            ("pbData", POINTER(c_ubyte)),
        ]

    payload = create_string_buffer(value)
    entropy = create_string_buffer(_ENTROPY)
    source = _DataBlob(len(value), ctypes.cast(payload, POINTER(c_ubyte)))
    entropy_blob = _DataBlob(len(_ENTROPY), ctypes.cast(entropy, POINTER(c_ubyte)))
    target = _DataBlob()

    protect = windll.crypt32.CryptProtectData
    protect.argtypes = [
        POINTER(_DataBlob),
        c_wchar_p,
        POINTER(_DataBlob),
        c_void_p,
        c_void_p,
        c_uint32,
        POINTER(_DataBlob),
    ]
    protect.restype = c_int
    if not protect(byref(source), None, byref(entropy_blob), None, None, 0, byref(target)):
        raise RuntimeError("DPAPI protection failed")
    protected = ctypes.string_at(target.pbData, target.cbData)
    windll.kernel32.LocalFree(target.pbData)
    return protected


def _dpapi_unprotect(value: bytes) -> bytes:
    """Decrypt bytes previously protected for the current Windows user."""
    from ctypes import (
        POINTER,
        byref,
        c_int,
        c_ubyte,
        c_uint32,
        c_void_p,
        c_wchar_p,
        create_string_buffer,
    )

    windll = _windll()
    if windll is None:
        raise RuntimeError("DPAPI is unavailable on this platform")

    class _DataBlob(ctypes.Structure):
        _fields_: ClassVar[list[tuple[str, type]]] = [
            ("cbData", c_uint32),
            ("pbData", POINTER(c_ubyte)),
        ]

    payload = create_string_buffer(value)
    entropy = create_string_buffer(_ENTROPY)
    source = _DataBlob(len(value), ctypes.cast(payload, POINTER(c_ubyte)))
    entropy_blob = _DataBlob(len(_ENTROPY), ctypes.cast(entropy, POINTER(c_ubyte)))
    target = _DataBlob()

    unprotect = windll.crypt32.CryptUnprotectData
    unprotect.argtypes = [
        POINTER(_DataBlob),
        c_wchar_p,
        POINTER(_DataBlob),
        c_void_p,
        c_void_p,
        c_uint32,
        POINTER(_DataBlob),
    ]
    unprotect.restype = c_int
    if not unprotect(byref(source), None, byref(entropy_blob), None, None, 0, byref(target)):
        raise RuntimeError("DPAPI unprotection failed")
    plain = ctypes.string_at(target.pbData, target.cbData)
    windll.kernel32.LocalFree(target.pbData)
    return plain


class WindowsOwnedPath:
    """Reject symbolic links and junction escapes from the owned root."""

    def assert_owned(self, resolver: OwnedPathResolver, path: Path) -> None:
        resolved = assert_owned_resolved(resolver, path)
        if resolved.is_junction():
            raise OwnedPathError("Morpheus-owned path must not be a junction")


class WindowsSecretStore:
    """DPAPI-protected secret store; values are never returned."""

    def __init__(self, store_dir: Path) -> None:
        self._store_dir = store_dir
        store_dir.mkdir(parents=True, exist_ok=True)

    def _entry(self, name: str) -> Path:
        bounded_service_name(name)
        return self._store_dir / f"{name}.secret"

    def store(self, name: str, value: bytes) -> None:
        entry = self._entry(name)
        entry.write_bytes(_dpapi_protect(value))
        restrict_private_file(entry)

    def exists(self, name: str) -> bool:
        return self._entry(name).is_file()

    def verify(self, name: str, value: bytes) -> bool:
        if not self.exists(name):
            return False
        return constant_time_equal(_dpapi_unprotect(self._entry(name).read_bytes()), value)

    def remove(self, name: str) -> None:
        with contextlib.suppress(FileNotFoundError):
            self._entry(name).unlink()


class WindowsProcessSupervision:
    """Terminate the whole process tree with taskkill /T /F."""

    def alive(self, pid: int) -> bool:
        result = subprocess.run(  # noqa: S603  # nosec B603
            [_native_tool("tasklist"), "/FI", f"PID eq {pid}", "/NH"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return str(pid) in result.stdout

    def terminate_tree(self, pid: int) -> None:
        result = subprocess.run(  # noqa: S603  # nosec B603
            [_native_tool("taskkill"), "/PID", str(pid), "/T", "/F"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0 and result.returncode != 128:
            raise RuntimeError(f"cannot terminate process tree {pid}: {result.stderr.strip()}")


class WindowsServiceLifecycle:
    """Bounded service names through the Windows service control manager."""

    def _sc(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603  # nosec B603
            [_native_tool("sc"), *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def status(self, name: str) -> str:
        name = bounded_service_name(name)
        result = self._sc("query", name)
        return result.stdout.strip() or f"service {name} not found"

    def start(self, name: str) -> None:
        name = bounded_service_name(name)
        result = self._sc("start", name)
        if result.returncode != 0:
            raise RuntimeError(f"cannot start service {name}: {result.stdout.strip()}")

    def stop(self, name: str) -> None:
        name = bounded_service_name(name)
        result = self._sc("stop", name)
        if result.returncode != 0:
            raise RuntimeError(f"cannot stop service {name}: {result.stdout.strip()}")


class WindowsDurableReplacement:
    """Atomic rename over the destination; NTFS rename is already durable."""

    def replace(self, resolver: OwnedPathResolver, destination: Path, staged: Path) -> None:
        owned_staged = assert_owned_resolved(resolver, staged)
        owned_destination = assert_owned_resolved(resolver, destination)
        if not owned_staged.is_file():
            raise OwnedPathError("staged replacement must be a regular file")
        os.replace(owned_staged, owned_destination)


class WindowsHardwareTelemetry:
    """Snapshot volatile utilization through the read-only allowlist."""

    def snapshot(self) -> UtilizationSnapshot:
        from morpheus.adapters.host.collectors import PortableHostCollector

        return PortableHostCollector().collect().utilization
