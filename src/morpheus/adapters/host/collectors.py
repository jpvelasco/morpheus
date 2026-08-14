"""Portable read-only host discovery collector using only allowlisted sources."""

from __future__ import annotations

import ctypes
import json
import os
import platform
import shutil
import subprocess  # nosec B404
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from morpheus.core.discovery import (
    AcceleratorUtilization,
    CapabilityValue,
    DiscoveryResult,
    UtilizationSnapshot,
    fingerprint_profile,
    parse_cpu_features,
    parse_docker_version_json,
    parse_meminfo_bytes,
    parse_nvidia_smi_csv,
)
from morpheus.core.records import (
    AcceleratorFacts,
    DriverFacts,
    HostProfile,
    StorageFacts,
)

_NVIDIA_GPU_QUERY = [
    "nvidia-smi",
    "--query-gpu=index,name,uuid,bus_id,memory.total,memory.used,"
    "driver_version,utilization.gpu,temperature.gpu",
    "--format=csv,noheader,nounits",
]
_DOCKER_VERSION = ["docker", "version", "--format", "{{json .}}"]
_MEMINFO = Path("/proc/meminfo")
_CPUINFO = Path("/proc/cpuinfo")
_LOADAVG = Path("/proc/loadavg")
_MIB = 1024 * 1024


def _parse_int(value: str | None) -> int | None:
    if value is None or value == "N/A":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _mib_to_bytes(value: str | None) -> int | None:
    parsed = _parse_int(value)
    if parsed is None or parsed < 1:
        return None
    return parsed * _MIB


class PortableHostCollector:
    """Collect stable and volatile host evidence through an allowlist only."""

    def __init__(self, *, storage_categories: Mapping[str, Path] | None = None) -> None:
        if storage_categories is None:
            storage_categories = {"system": Path(os.path.abspath(os.sep))}
        self._storage_categories = dict(storage_categories)

    def collect(self) -> DiscoveryResult:
        sources: dict[str, CapabilityValue] = {}
        memory_bytes, memory_state = self._memory_bytes()
        sources["memory"] = memory_state
        cpu_cores, cpu_state, cpu_features = self._cpu_facts()
        sources["cpu"] = cpu_state
        storage, storage_state = self._storage_facts()
        sources["storage"] = storage_state
        accelerators, drivers, utilization, accelerator_state = self._accelerator_facts()
        sources["accelerator"] = accelerator_state
        sources["driver"] = accelerator_state
        container_runtime, container_state = self._container_facts()
        sources["container"] = container_state
        profile = fingerprint_profile(
            HostProfile(
                profile_version=1,
                machine_id="pending",
                platform=self._platform_name(),
                architecture=self._architecture(),
                cpu_cores=cpu_cores,
                cpu_features=cpu_features,
                memory_bytes=memory_bytes,
                accelerators=accelerators,
                storage=storage,
                os_version=self._os_version(),
                container_runtime=container_runtime,
                driver_versions=drivers,
            )
        )
        utilization_snapshot = self._utilization(memory_bytes, storage, utilization)
        return DiscoveryResult(
            profile=profile,
            utilization=utilization_snapshot,
            source_states=tuple(sorted((name, state.value) for name, state in sources.items())),
        )

    def _platform_name(self) -> str:
        name = platform.system().lower()
        if name not in {"linux", "windows", "darwin"}:
            return "unknown"
        return name

    def _architecture(self) -> str:
        return platform.machine().lower().replace(" ", "-") or "unknown"

    def _os_version(self) -> str:
        return platform.release() or "unknown"

    def _cpu_facts(self) -> tuple[int | None, CapabilityValue, tuple[str, ...]]:
        cores = os.cpu_count()
        if os.name == "posix" and _CPUINFO.is_file():
            try:
                features = parse_cpu_features(_CPUINFO.read_text(encoding="utf-8"))
            except OSError:
                return cores, CapabilityValue.PERMISSION_DENIED, ()
            return cores, CapabilityValue.KNOWN, features
        if cores is None:
            return None, CapabilityValue.PERMISSION_DENIED, ()
        return cores, CapabilityValue.KNOWN, ()

    def _memory_bytes(self) -> tuple[int | None, CapabilityValue]:
        if os.name == "posix" and _MEMINFO.is_file():
            try:
                values = parse_meminfo_bytes(_MEMINFO.read_text(encoding="utf-8"))
            except OSError:
                return None, CapabilityValue.PERMISSION_DENIED
            if "MemTotal" not in values:
                return None, CapabilityValue.PERMISSION_DENIED
            return values["MemTotal"], CapabilityValue.KNOWN
        if os.name == "nt":
            return _windows_memory_bytes()
        return None, CapabilityValue.UNSUPPORTED

    def _storage_facts(self) -> tuple[tuple[StorageFacts, ...], CapabilityValue]:
        entries: list[StorageFacts] = []
        try:
            for category, root in self._storage_categories.items():
                usage = shutil.disk_usage(root)
                entries.append(StorageFacts(category=category, total_bytes=usage.total))
        except OSError:
            return (), CapabilityValue.PERMISSION_DENIED
        if not entries:
            return (), CapabilityValue.PERMISSION_DENIED
        return tuple(entries), CapabilityValue.KNOWN

    def _accelerator_facts(
        self,
    ) -> tuple[
        tuple[AcceleratorFacts, ...],
        tuple[DriverFacts, ...],
        tuple[AcceleratorUtilization, ...],
        CapabilityValue,
    ]:
        try:
            result = subprocess.run(  # noqa: S603  # nosec B603
                _NVIDIA_GPU_QUERY, check=False, capture_output=True, text=True, timeout=5
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return (), (), (), CapabilityValue.UNSUPPORTED
        except PermissionError:
            return (), (), (), CapabilityValue.PERMISSION_DENIED
        if result.returncode != 0:
            return (), (), (), CapabilityValue.UNSUPPORTED
        rows = parse_nvidia_smi_csv(result.stdout)
        accelerators: list[AcceleratorFacts] = []
        utilization: list[AcceleratorUtilization] = []
        driver_versions: set[str] = set()
        for row in rows:
            values = dict(row)
            driver_version = values.get("driver_version")
            if driver_version and driver_version != "N/A":
                driver_versions.add(driver_version)
            device_id = values.get("uuid") or "unknown"
            bus_id = values.get("bus_id")
            topology: tuple[str, ...] = ()
            if bus_id and bus_id != "N/A":
                topology = ("pcie-" + bus_id.replace(":", "-"),)
            accelerators.append(
                AcceleratorFacts(
                    vendor="nvidia",
                    name=values.get("name") or "unknown",
                    device_id=device_id,
                    memory_bytes=_mib_to_bytes(values.get("memory.total")),
                    topology=topology,
                    capabilities=("cuda",),
                    state="available",
                )
            )
            utilization.append(
                AcceleratorUtilization(
                    device_id=device_id,
                    memory_used_bytes=_mib_to_bytes(values.get("memory.used")),
                    utilization_percent=_parse_int(values.get("utilization.gpu")),
                )
            )
        drivers = tuple(
            DriverFacts(kind="nvidia-cuda", version=version) for version in sorted(driver_versions)
        )
        return tuple(accelerators), drivers, tuple(utilization), CapabilityValue.KNOWN

    def _container_facts(self) -> tuple[str | None, CapabilityValue]:
        try:
            result = subprocess.run(  # noqa: S603  # nosec B603
                _DOCKER_VERSION, check=False, capture_output=True, text=True, timeout=5
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None, CapabilityValue.UNAVAILABLE
        except PermissionError:
            return None, CapabilityValue.PERMISSION_DENIED
        if result.returncode != 0:
            return None, CapabilityValue.PERMISSION_DENIED
        try:
            versions = parse_docker_version_json(result.stdout)
        except json.JSONDecodeError:
            return None, CapabilityValue.PERMISSION_DENIED
        if "server" not in versions:
            return None, CapabilityValue.UNAVAILABLE
        return "docker", CapabilityValue.KNOWN

    def _utilization(
        self,
        memory_bytes: int | None,
        storage: tuple[StorageFacts, ...],
        accelerators: tuple[AcceleratorUtilization, ...],
    ) -> UtilizationSnapshot:
        available = None
        if os.name == "posix" and _MEMINFO.is_file():
            try:
                values = parse_meminfo_bytes(_MEMINFO.read_text(encoding="utf-8"))
                available = values.get("MemAvailable")
            except OSError:
                available = None
        elif os.name == "nt" and memory_bytes is not None:
            available = _windows_available_bytes()
        free_by_storage: list[tuple[str, int]] = []
        for entry in storage:
            root = self._storage_categories.get(entry.category)
            if root is None:
                continue
            try:
                usage = shutil.disk_usage(root)
                free_by_storage.append((entry.category, usage.free))
            except OSError:
                continue
        load_average: float | None = None
        if os.name == "posix" and _LOADAVG.is_file():
            try:
                load_average = float(_LOADAVG.read_text(encoding="utf-8").split()[0])
            except (OSError, ValueError):
                load_average = None
        return UtilizationSnapshot(
            observed_at=datetime.now(UTC),
            load_average_1m=load_average,
            memory_available_bytes=available,
            free_bytes_by_storage=tuple(free_by_storage),
            accelerators=accelerators,
        )


class _MemoryStatusEx(ctypes.Structure):
    _fields_: ClassVar[list[tuple[str, Any]]] = [
        ("length", ctypes.c_ulong),
        ("memory_load", ctypes.c_ulong),
        ("total_phys", ctypes.c_ulonglong),
        ("available_phys", ctypes.c_ulonglong),
        ("total_page_file", ctypes.c_ulonglong),
        ("available_page_file", ctypes.c_ulonglong),
        ("total_virtual", ctypes.c_ulonglong),
        ("available_virtual", ctypes.c_ulonglong),
        ("available_extended_virtual", ctypes.c_ulonglong),
    ]


def _windows_memory_bytes() -> tuple[int | None, CapabilityValue]:
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return None, CapabilityValue.UNSUPPORTED
    kernel32 = getattr(windll, "kernel32", None)
    if kernel32 is None or not hasattr(kernel32, "GlobalMemoryStatusEx"):
        return None, CapabilityValue.PERMISSION_DENIED
    status = _MemoryStatusEx()
    status.length = ctypes.sizeof(_MemoryStatusEx)
    if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None, CapabilityValue.PERMISSION_DENIED
    return int(status.total_phys), CapabilityValue.KNOWN


def _windows_available_bytes() -> int | None:
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return None
    kernel32 = getattr(windll, "kernel32", None)
    if kernel32 is None or not hasattr(kernel32, "GlobalMemoryStatusEx"):
        return None
    status = _MemoryStatusEx()
    status.length = ctypes.sizeof(_MemoryStatusEx)
    if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return int(status.available_phys)


__all__ = ["PortableHostCollector", "_windows_memory_bytes"]
