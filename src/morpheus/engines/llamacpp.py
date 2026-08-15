"""llama.cpp engine adapter (RUNM-002).

llama.cpp/llama-server is the common stable engine path; engines are
unvalidated and unadvertised as stable until their evidence lane passes.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

import httpx
from prometheus_client.parser import text_fd_to_metric_families

from morpheus.core.health import HealthState
from morpheus.core.metrics import MetricsSnapshot
from morpheus.engines.base import (
    CapabilityProbe,
    EngineCapabilities,
    EngineCommandError,
    EngineConfiguration,
    EngineRunner,
    EngineRuntime,
    LogRing,
    NativeEngineRunner,
    NativeProcessHandle,
    PortProbe,
    ProcessHandle,
    SocketPortProbe,
    SubprocessCapabilityProbe,
)

__all__ = [
    "KNOWN_GOOD_BUILDS",
    "STABLE_MINIMUM_BUILD",
    "CapabilityProbe",
    "EngineCapabilities",
    "EngineCommandError",
    "EngineConfiguration",
    "EngineRunner",
    "EngineRuntime",
    "LlamaCppCapabilities",
    "LlamaCppConfiguration",
    "LlamaCppEngine",
    "LogRing",
    "NativeEngineRunner",
    "NativeProcessHandle",
    "PortProbe",
    "ProcessHandle",
    "SocketPortProbe",
    "SubprocessCapabilityProbe",
    "parse_llamacpp_health",
    "parse_llamacpp_metrics",
    "parse_llamacpp_version",
]

_LLAMA_METRICS = {
    "llama:request_success_total": "request_success_total",
    "llama:request_failure_total": "request_failure_total",
    "llama:requests_processing": "requests_processing",
    "llama:prompt_tokens_total": "prompt_tokens_total",
    "llama:generation_tokens_total": "generation_tokens_total",
    "llama:kv_cache_usage_ratio": "kv_cache_usage_ratio",
}

_BUILD_PATTERN = re.compile(r"build\s*:?\s*(\d+)", re.IGNORECASE)
_VERSION_PATTERN = re.compile(r"version\s+([0-9.]+)", re.IGNORECASE)

# Builds with a completed Morpheus evidence lane. Everything else reports
# unsupported until Phase 18 retains the full physical qualification lane.
KNOWN_GOOD_BUILDS = frozenset({6139, 5973, 5154})
STABLE_MINIMUM_BUILD = 4000


@dataclass(frozen=True, slots=True)
class LlamaCppCapabilities:
    build: int
    version: str
    supported: bool
    streaming: bool = True
    tools: bool = True
    structured_output: bool = True
    parallel_slots: bool = True
    embedded_server: bool = True

    @property
    def display_name(self) -> str:
        return f"llama.cpp b{self.build} ({self.version})"


def parse_llamacpp_version(output: str) -> LlamaCppCapabilities:
    """Parse `llama-server --version` output into typed capabilities."""
    build_match = _BUILD_PATTERN.search(output)
    if build_match is None:
        raise ValueError("unrecognized llama.cpp version output")
    build = int(build_match.group(1))
    version_match = _VERSION_PATTERN.search(output)
    version = version_match.group(1) if version_match is not None else "0.0.0"
    supported = build in KNOWN_GOOD_BUILDS
    return LlamaCppCapabilities(build=build, version=version, supported=supported)


def _llamacpp_engine_capabilities(output: str) -> EngineCapabilities:
    parsed = parse_llamacpp_version(output)
    return EngineCapabilities(
        label=parsed.display_name,
        version=parsed.version,
        supported=parsed.supported,
        build=parsed.build,
    )


@dataclass(frozen=True, slots=True)
class LlamaCppConfiguration(EngineConfiguration):
    """Immutable engine configuration; rendering never mutates it."""

    model_path: Path
    host: str = "127.0.0.1"
    port: int = 8080
    threads: int = 4
    context_window: int = 4096
    parallel_slots: int = 1
    gpu_layers: int = 0
    seed: int = 0
    alias: str | None = None
    json_schema: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.model_path, Path) or not self.model_path.is_absolute():
            raise ValueError("model path must be absolute")
        if not self.host or any(character.isspace() for character in self.host):
            raise ValueError("host must be a non-empty string without whitespace")
        if not 1 <= self.port <= 65535:
            raise ValueError("port must be within 1..65535")
        if not 1 <= self.threads <= 128:
            raise ValueError("threads must be within 1..128")
        if not 256 <= self.context_window <= 1_048_576:
            raise ValueError("context window must be within 256..1048576")
        if not 1 <= self.parallel_slots <= 256:
            raise ValueError("parallel slots must be within 1..256")
        if self.gpu_layers < -1:
            raise ValueError("gpu layers must be -1 or a non-negative integer")
        if self.alias is not None and not self.alias:
            raise ValueError("alias must be a non-empty string when present")
        if self.json_schema is not None and not self.json_schema:
            raise ValueError("json schema must be a non-empty string when present")

    def render_arguments(self) -> tuple[str, ...]:
        arguments = [
            "--model",
            str(self.model_path),
            "--host",
            self.host,
            "--port",
            str(self.port),
            "--threads",
            str(self.threads),
            "--ctx-size",
            str(self.context_window),
            "--parallel",
            str(self.parallel_slots),
            "--n-gpu-layers",
            str(self.gpu_layers),
            "--seed",
            str(self.seed),
        ]
        if self.alias is not None:
            arguments.extend(("--alias", self.alias))
        if self.json_schema is not None:
            arguments.extend(("--json-schema", self.json_schema))
        return tuple(arguments)

    def render_digest(self) -> str:
        return hashlib.sha256("\0".join(self.render_arguments()).encode()).hexdigest()


def parse_llamacpp_health(text: str) -> HealthState:
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError) as error:
        raise ValueError("invalid llama.cpp health document") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("status"), str):
        raise ValueError("invalid llama.cpp health document")
    status = payload["status"]
    if status == "ok":
        return HealthState.READY
    if status in {"loading model", "no slot available"}:
        return HealthState.STARTING
    return HealthState.DEGRADED


def parse_llamacpp_metrics(text: str) -> MetricsSnapshot:
    values: dict[str, float] = {}
    found: set[str] = set()
    try:
        families = text_fd_to_metric_families(StringIO(text))
        for family in families:
            for sample in family.samples:
                output_name = _LLAMA_METRICS.get(sample.name)
                if output_name is None:
                    continue
                found.add(output_name)
                values[output_name] = values.get(output_name, 0.0) + float(sample.value)
    except (TypeError, ValueError) as error:
        raise ValueError("invalid Prometheus metrics") from error
    expected = frozenset(_LLAMA_METRICS.values())
    return MetricsSnapshot(
        values=values,
        available_signals=frozenset(found),
        missing_signals=expected.difference(found),
    )


class LlamaCppEngine(EngineRuntime):
    """Typed llama.cpp adapter: detect, render, preflight, run, observe."""

    def __init__(
        self,
        *,
        configuration: LlamaCppConfiguration,
        binary: Path,
        owned_root: Path,
        probe: CapabilityProbe | None = None,
        runner: EngineRunner | None = None,
        port_probe: PortProbe | None = None,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        super().__init__(
            name="llamacpp",
            configuration=configuration,
            binary=binary,
            owned_root=owned_root,
            probe=probe,
            runner=runner,
            port_probe=port_probe,
            client=client,
            timeout_seconds=timeout_seconds,
            version_parser=_llamacpp_engine_capabilities,
            health_parser=parse_llamacpp_health,
            metrics_parser=parse_llamacpp_metrics,
        )

    def preflight(
        self,
        *,
        expected_binary_digest: str | None = None,
        minimum_build: int | None = STABLE_MINIMUM_BUILD,
    ) -> tuple[str, ...]:
        return super().preflight(
            expected_binary_digest=expected_binary_digest,
            minimum_build=minimum_build,
        )
