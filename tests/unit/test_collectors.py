from __future__ import annotations

import ctypes
import json
from pathlib import Path

import pytest

from morpheus.adapters.host import collectors
from morpheus.adapters.host.collectors import PortableHostCollector
from morpheus.core.discovery import CapabilityValue


class _FileProbe:
    def __init__(self, *, exists: bool, content: str = "", error: bool = False) -> None:
        self._exists = exists
        self._content = content
        self._error = error

    def is_file(self) -> bool:
        return self._exists

    def read_text(self, **kwargs: object) -> str:
        if self._error:
            raise OSError("read denied")
        return self._content


def _probe(**kwargs: object) -> _FileProbe:
    return _FileProbe(**kwargs)  # type: ignore[arg-type]


def test_collector_unknown_platform_is_reported_honestly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(collectors.platform, "system", lambda: "custom-os")
    monkeypatch.setattr(collectors.platform, "machine", lambda: "")
    monkeypatch.setattr(collectors.platform, "release", lambda: "")
    monkeypatch.setattr(collectors.os, "cpu_count", lambda: None)
    monkeypatch.setattr(collectors.os, "name", "posix")
    monkeypatch.setattr(collectors, "_MEMINFO", _probe(exists=False))
    monkeypatch.setattr(collectors, "_CPUINFO", _probe(exists=False))
    monkeypatch.setattr(
        collectors.PortableHostCollector,
        "_storage_facts",
        lambda self: ((), CapabilityValue.PERMISSION_DENIED),
    )
    collector = PortableHostCollector(storage_categories={"system": tmp_path})
    result = collector.collect()
    assert result.profile.platform == "unknown"
    assert result.profile.architecture == "unknown"
    assert result.profile.os_version == "unknown"
    assert result.profile.cpu_cores is None
    states = dict(result.source_state)
    assert states["cpu"] == "permission_denied"
    assert states["memory"] == "unsupported"


def test_collector_meminfo_missing_key_is_permission_denied(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(collectors.os, "name", "posix")
    monkeypatch.setattr(
        collectors, "_MEMINFO", _probe(exists=True, content="MemFree: 100 kB\n")
    )
    collector = PortableHostCollector(storage_categories={"system": tmp_path})
    memory_bytes, state = collector._memory_bytes()
    assert memory_bytes is None
    assert state is CapabilityValue.PERMISSION_DENIED


def test_collector_memory_read_failure_is_permission_denied(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(collectors.os, "name", "posix")
    monkeypatch.setattr(collectors, "_MEMINFO", _probe(exists=True, error=True))
    collector = PortableHostCollector(storage_categories={"system": tmp_path})
    memory_bytes, state = collector._memory_bytes()
    assert memory_bytes is None
    assert state is CapabilityValue.PERMISSION_DENIED


def test_collector_windows_memory_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ctypes, "windll", None, raising=False)
    value, state = PortableHostCollector()._memory_bytes()
    assert value is None and state is CapabilityValue.UNSUPPORTED


def test_collector_storage_failure_is_permission_denied(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail_usage(path: Path) -> object:
        raise OSError("no access")

    monkeypatch.setattr(collectors.shutil, "disk_usage", fail_usage)
    collector = PortableHostCollector(storage_categories={"system": tmp_path})
    storage, state = collector._storage_facts()
    assert storage == ()
    assert state is CapabilityValue.PERMISSION_DENIED


def test_collector_empty_storage_categories_is_permission_denied() -> None:
    collector = PortableHostCollector(storage_categories={})
    storage, state = collector._storage_facts()
    assert storage == ()
    assert state is CapabilityValue.PERMISSION_DENIED


def test_collector_accelerator_tool_missing_is_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_run(command: list[str], **kwargs: object) -> object:
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(collectors.subprocess, "run", missing_run)
    facts, drivers, utilization, state = PortableHostCollector()._accelerator_facts()
    assert facts == () and drivers == () and utilization == ()
    assert state is CapabilityValue.UNSUPPORTED


def test_collector_accelerator_permission_error_is_permission_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def denied_run(command: list[str], **kwargs: object) -> object:
        raise PermissionError(command[0])

    monkeypatch.setattr(collectors.subprocess, "run", denied_run)
    _, _, _, state = PortableHostCollector()._accelerator_facts()
    assert state is CapabilityValue.PERMISSION_DENIED


def test_collector_accelerator_failure_returns_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Failed:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(collectors.subprocess, "run", lambda *a, **k: Failed())
    _, _, _, state = PortableHostCollector()._accelerator_facts()
    assert state is CapabilityValue.UNSUPPORTED


def test_collector_accelerator_rows_with_unknown_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Completed:
        returncode = 0
        stdout = (
            "index, name, uuid, bus_id, memory.total, memory.used, "
            "driver_version, utilization.gpu, temperature.gpu\n"
            "0, GPU, GPU-x, N/A, N/A, N/A, N/A, N/A, N/A\n"
        )

    monkeypatch.setattr(collectors.subprocess, "run", lambda *a, **k: Completed())
    facts, drivers, utilization, state = PortableHostCollector()._accelerator_facts()
    assert state is CapabilityValue.KNOWN
    assert len(facts) == 1
    assert facts[0].memory_bytes is None
    assert facts[0].topology == ()
    assert drivers == ()
    assert utilization[0].memory_used_bytes is None
    assert utilization[0].utilization_percent is None


def test_collector_container_missing_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_run(command: list[str], **kwargs: object) -> object:
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(collectors.subprocess, "run", missing_run)
    runtime, state = PortableHostCollector()._container_facts()
    assert runtime is None
    assert state is CapabilityValue.UNAVAILABLE


def test_collector_container_failure_and_bad_output_are_permission_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Failed:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(collectors.subprocess, "run", lambda *a, **k: Failed())
    _, state = PortableHostCollector()._container_facts()
    assert state is CapabilityValue.PERMISSION_DENIED

    class Garbage:
        returncode = 0
        stdout = "not json"

    monkeypatch.setattr(collectors.subprocess, "run", lambda *a, **k: Garbage())
    _, state = PortableHostCollector()._container_facts()
    assert state is CapabilityValue.PERMISSION_DENIED


def test_collector_container_without_server_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Completed:
        returncode = 0
        stdout = json.dumps({"Client": {"Version": "29.6.2"}})

    monkeypatch.setattr(collectors.subprocess, "run", lambda *a, **k: Completed())
    runtime, state = PortableHostCollector()._container_facts()
    assert runtime is None
    assert state is CapabilityValue.UNAVAILABLE


def test_collector_utilization_survives_missing_volatile_sources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(collectors.os, "name", "posix")
    monkeypatch.setattr(collectors, "_MEMINFO", _probe(exists=False))
    monkeypatch.setattr(collectors, "_LOADAVG", _probe(exists=False))
    collector = PortableHostCollector(storage_categories={"system": tmp_path})
    snapshot = collector._utilization(None, (), ())
    assert snapshot.load_average_1m is None
    assert snapshot.memory_available_bytes is None
    assert snapshot.free_bytes_by_storage == ()


def test_collector_utilization_read_failures_are_quiet(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(collectors.os, "name", "posix")
    monkeypatch.setattr(collectors, "_MEMINFO", _probe(exists=True, error=True))
    monkeypatch.setattr(collectors, "_LOADAVG", _probe(exists=True, error=True))
    collector = PortableHostCollector(storage_categories={"system": tmp_path})
    snapshot = collector._utilization(None, (), ())
    assert snapshot.memory_available_bytes is None
    assert snapshot.load_average_1m is None