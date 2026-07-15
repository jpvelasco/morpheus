from __future__ import annotations

import json
import re
import shutil

# The isolated runtime agent exposes only the fixed commands below.
import subprocess  # nosec B404
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from morpheus.agent.protocol import AgentOperation


class SystemHostInspector:
    def __init__(self, *, project_id: str, data_dir: Path) -> None:
        self._project_id = project_id
        self._data_dir = data_dir

    def inspect(self, operation: AgentOperation) -> dict[str, Any]:
        if operation is AgentOperation.HOST_SUMMARY:
            return self._host_summary()
        if operation is AgentOperation.GPU_SUMMARY:
            return self._gpu_summary()
        if operation is AgentOperation.MORPHEUS_SERVICES:
            return self._morpheus_services()
        raise ValueError("unsupported agent operation")

    def _host_summary(self) -> dict[str, Any]:
        memory = _memory_summary()
        disk = shutil.disk_usage(self._data_dir.resolve().parent)
        return {
            "memory": memory,
            "disk": {"total_bytes": disk.total, "used_bytes": disk.used, "free_bytes": disk.free},
            "process": {
                "load_average_1m": _load_average_1m(),
                "uptime_seconds": _uptime_seconds(),
            },
            "clock": {"observed_at": datetime.now(UTC).isoformat()},
        }

    def _gpu_summary(self) -> dict[str, Any]:
        command = [
            "nvidia-smi",
            "--query-gpu=index,name,uuid,memory.total,memory.used,utilization.gpu,temperature.gpu",
            "--format=csv,noheader,nounits",
        ]
        # The executable and every flag are fixed by this allowlisted operation.
        result = subprocess.run(  # noqa: S603  # nosec B603
            command, check=True, capture_output=True, text=True, timeout=5
        )
        gpus = []
        for line in result.stdout.splitlines():
            fields = [item.strip() for item in line.split(",")]
            if len(fields) != 7:
                continue
            gpus.append(
                {
                    "index": int(fields[0]),
                    "name": fields[1],
                    "uuid": fields[2],
                    "memory_total_mib": int(fields[3]),
                    "memory_used_mib": int(fields[4]),
                    "utilization_percent": int(fields[5]),
                    "temperature_c": int(fields[6]),
                }
            )
        return {"gpus": gpus}

    def _morpheus_services(self) -> dict[str, Any]:
        command = [
            "docker",
            "ps",
            "--quiet",
            "--no-trunc",
            "--filter",
            f"label=io.morpheus.project={self._project_id}",
        ]
        # Only the validated installation-time project identifier is interpolated.
        result = subprocess.run(  # noqa: S603  # nosec B603
            command, check=True, capture_output=True, text=True, timeout=5
        )
        container_ids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if any(not re.fullmatch(r"[0-9a-f]{64}", container_id) for container_id in container_ids):
            raise ValueError("Docker returned an invalid container identifier")
        containers = [self._owned_container_summary(container_id) for container_id in container_ids]
        return {"containers": containers}

    def _owned_container_summary(self, container_id: str) -> dict[str, Any]:
        template = (
            '{"id":{{json .Id}},"name":{{json .Name}},"image_id":{{json .Image}},'
            '"configured_image":{{json .Config.Image}},"labels":{{json .Config.Labels}},'
            '"state":{{json .State.Status}},"health":'
            "{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}}}"
        )
        command = ["docker", "container", "inspect", "--format", template, container_id]
        result = subprocess.run(  # noqa: S603  # nosec B603
            command, check=True, capture_output=True, text=True, timeout=5
        )
        value = json.loads(result.stdout)
        labels = value.get("labels") if isinstance(value, dict) else None
        if not isinstance(labels, dict) or labels.get("io.morpheus.project") != self._project_id:
            raise ValueError("Docker ownership label changed during inspection")
        return {
            "id": value.get("id"),
            "name": str(value.get("name", "")).removeprefix("/"),
            "image_id": value.get("image_id"),
            "configured_image": value.get("configured_image"),
            "state": value.get("state"),
            "health": value.get("health"),
            "project": labels.get("io.morpheus.project"),
            "component": labels.get("io.morpheus.component"),
            "source_commit": labels.get("org.opencontainers.image.revision"),
            "release_version": labels.get("org.opencontainers.image.version"),
        }


def _memory_summary() -> dict[str, int]:
    values: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        key, raw = line.split(":", 1)
        if key in {"MemTotal", "MemAvailable"}:
            values[key] = int(raw.strip().split()[0]) * 1024
    return {"total_bytes": values["MemTotal"], "available_bytes": values["MemAvailable"]}


def _load_average_1m() -> float:
    return float(Path("/proc/loadavg").read_text(encoding="utf-8").split()[0])


def _uptime_seconds() -> float:
    return time.clock_gettime(time.CLOCK_BOOTTIME)
