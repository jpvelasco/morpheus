from __future__ import annotations

import math
import re
from typing import Any

from morpheus.core.performance import ContainerResourceSample, LoadMetrics

_SIZE_UNITS = {
    "B": 1,
    "kB": 1000,
    "MB": 1000**2,
    "GB": 1000**3,
    "KiB": 1024,
    "MiB": 1024**2,
    "GiB": 1024**3,
}


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"k6 summary {field} must be an object")
    return value


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"k6 summary {field} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"k6 summary {field} must be finite")
    return result


def parse_k6_summary(document: object) -> LoadMetrics:
    try:
        metrics = _mapping(_mapping(document, "document").get("metrics"), "metrics")

        def metric(name: str, value: str) -> float:
            entry = _mapping(metrics.get(name), name)
            values = _mapping(entry.get("values"), f"{name}.values")
            return _number(values.get(value), f"{name}.{value}")

        count = metric("http_reqs", "count")
        if not count.is_integer():
            raise ValueError("k6 summary request count must be an integer")
        return LoadMetrics(
            median_waiting_ms=metric("http_req_waiting", "med"),
            iterations_per_second=metric("iterations", "rate"),
            checks_rate=metric("checks", "rate"),
            failed_rate=metric("http_req_failed", "rate"),
            request_count=int(count),
        )
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, ValueError) and str(error).startswith("k6 summary"):
            raise
        raise ValueError("k6 summary is invalid") from error


def _string(document: dict[str, Any], field: str) -> str:
    value = document.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Docker stats {field} must be a non-empty string")
    return value


def _memory_bytes(value: str) -> int:
    usage = value.split("/", 1)[0].strip()
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(B|kB|MB|GB|KiB|MiB|GiB)", usage)
    if match is None:
        raise ValueError("Docker stats memory usage is invalid")
    return round(float(match.group(1)) * _SIZE_UNITS[match.group(2)])


def parse_docker_stats(document: object, *, component: str) -> ContainerResourceSample:
    if not isinstance(document, dict):
        raise ValueError("Docker stats document must be an object")
    container_id = _string(document, "ID")
    if re.fullmatch(r"[0-9a-f]{12,64}", container_id) is None:
        raise ValueError("Docker stats container ID is invalid")
    cpu = _string(document, "CPUPerc")
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?%", cpu) is None:
        raise ValueError("Docker stats CPU is invalid")
    pids = _string(document, "PIDs")
    if not pids.isdecimal():
        raise ValueError("Docker stats PIDs is invalid")
    return ContainerResourceSample(
        component=component,
        container_id=container_id,
        memory_bytes=_memory_bytes(_string(document, "MemUsage")),
        cpu_percent=float(cpu.removesuffix("%")),
        pids=int(pids),
    )
