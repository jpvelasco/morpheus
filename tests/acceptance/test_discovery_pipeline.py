"""Phase 12 acceptance: fixture-backed discovery pipeline end to end."""

from __future__ import annotations

from pathlib import Path

import pytest

from morpheus.adapters.host.collectors import PortableHostCollector
from morpheus.core.discovery import (
    CapabilityValue,
    DiscoveryResult,
    machine_fingerprint,
    normalize_capabilities,
)
from morpheus.core.records import decode_record, encode_record


class _Sources:
    def __init__(self) -> None:
        self.system = "linux"
        self.machine = "x86_64"
        self.release = "6.8.0-45-generic"
        self.cpu_count = 8
        self.meminfo = "MemTotal:       65536000 kB\nMemAvailable: 41943040 kB\n"
        self.cpuinfo = "flags\t\t: avx2 sse4_1\n"
        self.nvidia = (
            "index, name, uuid, bus_id, memory.total, memory.used, "
            "driver_version, utilization.gpu, temperature.gpu\n"
            "0, RTX 4070 Ti Super, GPU-abc, 00000000:01:00.0, 16384, 831, "
            "550.54.14, 42, 55\n"
        )
        self.docker = '{"Client": {"Version": "29.6.2"}, "Server": {"Version": "29.6.2"}}'
        self.loadavg = "0.5 0.4 0.3 1/200 42\n"
        self.disk_free = 1000
        self.disk_total = 2000


@pytest.fixture
def collector(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> PortableHostCollector:
    sources = _Sources()
    monkeypatch.setattr("morpheus.adapters.host.collectors.platform.system", lambda: sources.system)
    monkeypatch.setattr(
        "morpheus.adapters.host.collectors.platform.machine", lambda: sources.machine
    )
    monkeypatch.setattr(
        "morpheus.adapters.host.collectors.platform.release", lambda: sources.release
    )
    monkeypatch.setattr("morpheus.adapters.host.collectors.os.cpu_count", lambda: sources.cpu_count)

    def fake_run(command: list[str], **kwargs: object) -> object:
        assert kwargs == {
            "check": False,
            "capture_output": True,
            "text": True,
            "timeout": 5,
        }
        if command[:1] == ["nvidia-smi"]:
            return _Completed(sources.nvidia)
        assert command[:2] == ["docker", "version"]
        return _Completed(sources.docker)

    monkeypatch.setattr("morpheus.adapters.host.collectors.subprocess.run", fake_run)

    def fake_disk_usage(path: Path) -> object:
        return _Usage(sources.disk_total, sources.disk_free)

    monkeypatch.setattr("morpheus.adapters.host.collectors.shutil.disk_usage", fake_disk_usage)

    meminfo = tmp_path / "meminfo"
    meminfo.write_text(sources.meminfo, encoding="utf-8")
    cpuinfo = tmp_path / "cpuinfo"
    cpuinfo.write_text(sources.cpuinfo, encoding="utf-8")
    loadavg = tmp_path / "loadavg"
    loadavg.write_text(sources.loadavg, encoding="utf-8")
    monkeypatch.setattr("morpheus.adapters.host.collectors._MEMINFO", meminfo)
    monkeypatch.setattr("morpheus.adapters.host.collectors._CPUINFO", cpuinfo)
    monkeypatch.setattr("morpheus.adapters.host.collectors._LOADAVG", loadavg)
    monkeypatch.setattr("morpheus.adapters.host.collectors.os.name", "posix")
    monkeypatch.setattr("morpheus.adapters.host.collectors.os.path.abspath", lambda value: value)
    monkeypatch.setattr("morpheus.adapters.host.collectors.os.path.sep", "/")
    return PortableHostCollector(storage_categories={"system": tmp_path})


class _Completed:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout
        self.returncode = 0


class _Usage:
    def __init__(self, total: int, free: int) -> None:
        self.total = total
        self.used = total - free
        self.free = free


def test_discovery_pipeline_collects_fingerprint_normalizes_and_round_trips(
    collector: PortableHostCollector,
) -> None:
    result = collector.collect()
    assert isinstance(result, DiscoveryResult)
    profile = result.profile
    assert profile.machine_id == machine_fingerprint(profile)
    assert profile.platform == "linux"
    assert profile.architecture == "x86_64"
    assert profile.cpu_cores == 8
    assert profile.memory_bytes == 65_536_000 * 1024
    assert len(profile.accelerators) == 1
    assert profile.accelerators[0].memory_bytes == 16 * 1024**3
    assert profile.container_runtime == "docker"
    assert result.utilization.memory_available_bytes == 41_943_040 * 1024
    assert result.utilization.load_average_1m == 0.5
    assert dict(result.source_state)["accelerator"] == "known"

    capabilities = normalize_capabilities(profile, source_states=result.source_state)
    assert capabilities.accelerator_count == 1
    assert capabilities.missing_evidence == ()

    restored = decode_record(encode_record(profile))
    assert restored == profile


def test_discovery_pipeline_volatile_changes_do_not_change_identity(
    collector: PortableHostCollector,
) -> None:
    first = collector.collect()

    def busy_run(command: list[str], **kwargs: object) -> object:
        if command[:1] == ["nvidia-smi"]:
            return _Completed(
                "index, name, uuid, bus_id, memory.total, memory.used, "
                "driver_version, utilization.gpu, temperature.gpu\n"
                "0, RTX 4070 Ti Super, GPU-abc, 00000000:01:00.0, 16384, 9091, "
                "550.54.14, 97, 71\n"
            )
        return _Completed('{"Client": {"Version": "29.6.2"}, "Server": {"Version": "29.6.2"}}')

    import morpheus.adapters.host.collectors as collectors

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(collectors.subprocess, "run", busy_run)
    try:
        second = collector.collect()
    finally:
        monkeypatch.undo()
    assert second.profile.machine_id == first.profile.machine_id
    assert second.profile == first.profile
    assert (
        second.utilization.accelerators[0].memory_used_bytes
        != first.utilization.accelerators[0].memory_used_bytes
    )
    assert (
        second.utilization.accelerators[0].utilization_percent
        != first.utilization.accelerators[0].utilization_percent
    )


def test_discovery_pipeline_missing_tools_report_honest_unknown_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def missing_run(command: list[str], **kwargs: object) -> object:
        raise FileNotFoundError(command[0])

    monkeypatch.setattr("morpheus.adapters.host.collectors.subprocess.run", missing_run)
    monkeypatch.setattr("morpheus.adapters.host.collectors.os.name", "nt")
    monkeypatch.setattr("morpheus.adapters.host.collectors.os.path.abspath", lambda value: value)
    monkeypatch.setattr("morpheus.adapters.host.collectors.os.path.sep", "\\")
    monkeypatch.setattr(
        "morpheus.adapters.host.collectors.PortableHostCollector._memory_bytes",
        lambda self: (None, CapabilityValue.PERMISSION_DENIED),
    )
    monkeypatch.setattr(
        "morpheus.adapters.host.collectors.PortableHostCollector._cpu_facts",
        lambda self: (None, CapabilityValue.PERMISSION_DENIED, ()),
    )
    collector = PortableHostCollector(storage_categories={"system": tmp_path})
    result = collector.collect()
    capabilities = normalize_capabilities(result.profile, source_states=result.source_state)
    assert capabilities.memory_bytes is None
    assert capabilities.memory_state == "permission_denied"
    assert capabilities.accelerator_count is None
    assert capabilities.accelerator_state == "unsupported"
    assert "accelerator" in capabilities.missing_evidence
    assert "docker" not in capabilities.missing_evidence
    assert capabilities.container_runtime is None
