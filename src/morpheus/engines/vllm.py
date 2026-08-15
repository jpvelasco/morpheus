"""vLLM engine adapter (RUNM-002).

vLLM is a stable engine tier only on qualified Linux NVIDIA targets; it is
unvalidated and unadvertised as stable until the physical evidence lane
passes.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from morpheus.adapters.metrics.vllm import parse_vllm_metrics
from morpheus.core.health import HealthState
from morpheus.engines.base import (
    CapabilityProbe,
    EngineCapabilities,
    EngineCommandError,
    EngineConfiguration,
    EngineRunner,
    EngineRuntime,
    PortProbe,
)

_VERSION_PATTERN = re.compile(r"vllm,\s*version\s+([0-9.]+)", re.IGNORECASE)
_VERSION_PATTERN_ALT = re.compile(r"vllm\s+version\s+([0-9.]+)\s*$", re.IGNORECASE)

# Versions with a completed Morpheus evidence lane; others report
# unsupported until Phase 18 retains the full physical qualification lane.
KNOWN_GOOD_VERSIONS = frozenset({"0.9.2"})
STABLE_MINIMUM_VERSION = "0.7.0"


def _version_at_least(version: str, minimum: str) -> bool:
    def parts(value: str) -> tuple[int, ...]:
        return tuple(int(part) for part in re.split(r"[.-]", value) if part.isdigit())

    return parts(version) >= parts(minimum)


@dataclass(frozen=True, slots=True)
class VllmCapabilities:
    version: str
    supported: bool
    streaming: bool = True
    tools: bool = True
    structured_output: bool = True
    parallel: bool = True
    nvidia_linux_only: bool = True

    @property
    def display_name(self) -> str:
        return f"vllm {self.version}"


def parse_vllm_version(output: str) -> VllmCapabilities:
    """Parse `vllm --version` output into typed capabilities."""
    match = _VERSION_PATTERN.search(output) or _VERSION_PATTERN_ALT.search(output)
    if match is None:
        raise ValueError("unrecognized vllm version output")
    version = match.group(1)
    return VllmCapabilities(version=version, supported=version in KNOWN_GOOD_VERSIONS)


def _vllm_engine_capabilities(output: str) -> EngineCapabilities:
    parsed = parse_vllm_version(output)
    return EngineCapabilities(
        label=parsed.display_name,
        version=parsed.version,
        supported=parsed.supported,
        build=None,
    )


@dataclass(frozen=True, slots=True)
class VllmConfiguration(EngineConfiguration):
    """Immutable vLLM configuration; rendering never mutates it."""

    model_path: Path
    host: str = "127.0.0.1"
    port: int = 8000
    served_model_name: str = "morpheus-managed"
    max_model_len: int = 8192
    tensor_parallel_size: int = 1
    gpu_memory_utilization: float = 0.9
    dtype: str = "auto"
    quantization: str | None = None
    max_num_seqs: int = 256
    seed: int | None = None
    json_schema: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.model_path, Path) or not self.model_path.is_absolute():
            raise ValueError("model path must be absolute")
        if not self.host or any(character.isspace() for character in self.host):
            raise ValueError("host must be a non-empty string without whitespace")
        if not 1 <= self.port <= 65535:
            raise ValueError("port must be within 1..65535")
        if not 256 <= self.max_model_len <= 1_048_576:
            raise ValueError("max model length must be within 256..1048576")
        if self.tensor_parallel_size < 1:
            raise ValueError("tensor parallel size must be positive")
        if not 0.05 <= self.gpu_memory_utilization <= 0.99:
            raise ValueError("gpu memory utilization must be within 0.05..0.99")
        if self.dtype not in {"auto", "float16", "bfloat16", "float32"}:
            raise ValueError("dtype must be auto, float16, bfloat16, or float32")
        if not self.served_model_name or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]*", self.served_model_name
        ):
            raise ValueError("served model name must be a bounded identifier")
        if self.quantization is not None and not re.fullmatch(
            r"[A-Za-z0-9_.-]+", self.quantization
        ):
            raise ValueError("quantization must be a bounded identifier when present")
        if self.max_num_seqs < 1:
            raise ValueError("max num seqs must be positive")
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
            "--served-model-name",
            self.served_model_name,
            "--max-model-len",
            str(self.max_model_len),
            "--tensor-parallel-size",
            str(self.tensor_parallel_size),
            "--gpu-memory-utilization",
            f"{self.gpu_memory_utilization:.2f}",
            "--dtype",
            self.dtype,
            "--max-num-seqs",
            str(self.max_num_seqs),
        ]
        if self.quantization is not None:
            arguments.extend(("--quantization", self.quantization))
        if self.seed is not None:
            arguments.extend(("--seed", str(self.seed)))
        if self.json_schema is not None:
            arguments.extend(("--guided-json", self.json_schema))
        return tuple(arguments)

    def render_digest(self) -> str:
        return hashlib.sha256("\0".join(self.render_arguments()).encode()).hexdigest()


def parse_vllm_health(text: str) -> HealthState:
    if text.strip().casefold() == "ok":
        return HealthState.READY
    raise ValueError("invalid vllm health document")


class VllmEngine(EngineRuntime):
    """Typed vLLM adapter: detect, render, preflight, run, observe."""

    def __init__(
        self,
        *,
        configuration: VllmConfiguration,
        binary: Path,
        owned_root: Path,
        probe: CapabilityProbe | None = None,
        runner: EngineRunner | None = None,
        port_probe: PortProbe | None = None,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        super().__init__(
            name="vllm",
            configuration=configuration,
            binary=binary,
            owned_root=owned_root,
            probe=probe,
            runner=runner,
            port_probe=port_probe,
            client=client,
            timeout_seconds=timeout_seconds,
            version_parser=_vllm_engine_capabilities,
            health_parser=parse_vllm_health,
            metrics_parser=parse_vllm_metrics,
        )

    def preflight(
        self,
        *,
        expected_binary_digest: str | None = None,
        minimum_build: int | None = None,
    ) -> tuple[str, ...]:
        """Evidence gate; the minimum is the vLLM version floor policy."""
        violations = list(super().preflight(expected_binary_digest=expected_binary_digest))
        try:
            caps = self.capabilities()
        except EngineCommandError:
            caps = None
        if caps is not None and not _version_at_least(caps.version, STABLE_MINIMUM_VERSION):
            violations.append(f"{caps.label} is below the minimum version {STABLE_MINIMUM_VERSION}")
        self._preflight_ok = not violations
        return tuple(violations)
