"""Phase 12 acceptance: privacy-reviewed export of a fixture-backed discovery lane."""

from __future__ import annotations

from pathlib import Path

import pytest

from morpheus.core.discovery import normalize_capabilities
from morpheus.core.export import (
    export_discovery_result,
    privacy_violations,
)


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
        self.disk_total = 2000
        self.disk_free = 1000


@pytest.fixture
def exported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, object]:
    import morpheus.adapters.host.collectors as collectors
    from morpheus.adapters.host.collectors import PortableHostCollector

    sources = _Sources()

    class _Completed:
        def __init__(self, stdout: str) -> None:
            self.stdout = stdout
            self.returncode = 0

    class _Usage:
        def __init__(self, total: int, free: int) -> None:
            self.total = total
            self.free = free

    def fake_run(command: list[str], **kwargs: object) -> object:
        assert kwargs == {
            "check": False,
            "capture_output": True,
            "text": True,
            "timeout": 5,
        }
        if command[:1] == ["nvidia-smi"]:
            return _Completed(sources.nvidia)
        return _Completed(sources.docker)

    monkeypatch.setattr("morpheus.adapters.host.collectors.platform.system", lambda: sources.system)
    monkeypatch.setattr(
        "morpheus.adapters.host.collectors.platform.machine", lambda: sources.machine
    )
    monkeypatch.setattr(
        "morpheus.adapters.host.collectors.platform.release", lambda: sources.release
    )
    monkeypatch.setattr("morpheus.adapters.host.collectors.os.cpu_count", lambda: sources.cpu_count)
    monkeypatch.setattr("morpheus.adapters.host.collectors.subprocess.run", fake_run)
    monkeypatch.setattr(
        "morpheus.adapters.host.collectors.shutil.disk_usage", lambda path: _Usage(2000, 1000)
    )

    meminfo = tmp_path / "meminfo"
    meminfo.write_text(sources.meminfo, encoding="utf-8")
    cpuinfo = tmp_path / "cpuinfo"
    cpuinfo.write_text(sources.cpuinfo, encoding="utf-8")
    loadavg = tmp_path / "loadavg"
    loadavg.write_text(sources.loadavg, encoding="utf-8")
    monkeypatch.setattr(collectors, "_MEMINFO", meminfo)
    monkeypatch.setattr(collectors, "_CPUINFO", cpuinfo)
    monkeypatch.setattr(collectors, "_LOADAVG", loadavg)
    monkeypatch.setattr(collectors.os, "name", "posix")
    monkeypatch.setattr(collectors.os.path, "abspath", lambda value: value)
    monkeypatch.setattr(collectors.os.path, "sep", "/")

    collector = PortableHostCollector(storage_categories={"system": tmp_path})
    result = collector.collect()
    capabilities = normalize_capabilities(result.profile, source_states=result.source_state)
    return export_discovery_result(result, capabilities)


def test_export_is_read_only_repeatable_and_private(exported: dict[str, object]) -> None:
    assert privacy_violations(exported) == ()
    assert exported["profile"]["platform"] == "linux"
    assert exported["profile"]["os_version"] == "6.8.0-45-generic"
    assert exported["utilization"]["load_average_1m"] == 0.5
    assert exported["capability_profile"]["accelerator_count"] == 1


def test_export_document_contains_no_secret_values(exported: dict[str, object]) -> None:
    import json

    blob = json.dumps(exported)
    for token in ("api_key", "token", "password", "Authorization", "Bearer "):
        assert token not in blob


def test_export_document_is_stable_json(exported: dict[str, object]) -> None:
    import json

    document = json.dumps(exported, indent=2, sort_keys=True)
    reparsed = json.loads(document)
    assert reparsed == exported
