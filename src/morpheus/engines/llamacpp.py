"""llama.cpp engine adapter (RUNM-002).

Typed engine contract: capability detection, immutable configuration
rendering, preflight, start, health, metrics, logs, graceful stop, and
cleanup. llama.cpp/llama-server is the common stable engine path; engines
are unvalidated and unadvertised as stable until their evidence lane passes.
"""

from __future__ import annotations

import hashlib
import json
import re
import socket
import subprocess  # nosec B404
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Protocol

import httpx
from prometheus_client.parser import text_fd_to_metric_families

from morpheus.core.health import Evidence, HealthState
from morpheus.core.metrics import MetricsSnapshot

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


@dataclass(frozen=True, slots=True)
class LlamaCppConfiguration:
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


class CapabilityProbe(Protocol):
    def probe(self, binary: Path) -> str: ...


class SubprocessCapabilityProbe:
    def probe(self, binary: Path) -> str:
        result = subprocess.run(  # noqa: S603  # nosec B603
            (str(binary), "--version"),
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout or result.stderr


class PortProbe(Protocol):
    def is_free(self, host: str, port: int) -> bool: ...


class SocketPortProbe:
    def is_free(self, host: str, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.0)
            return sock.connect_ex((host, port)) != 0


class ProcessHandle(Protocol):
    @property
    def pid(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def poll(self) -> int | None: ...

    def wait(self, timeout: float) -> int | None: ...

    def lines(self, limit: int | None = None) -> tuple[str, ...]: ...


class EngineRunner(Protocol):
    def launch(self, command: tuple[str, ...]) -> ProcessHandle: ...


class NativeEngineRunner:
    def __init__(self, *, log_capacity: int = 200) -> None:
        self._log_capacity = log_capacity

    def launch(self, command: tuple[str, ...]) -> ProcessHandle:
        handle = subprocess.Popen(  # noqa: S603  # nosec B603
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        return NativeProcessHandle(handle, log_capacity=self._log_capacity)


class NativeProcessHandle:
    def __init__(
        self,
        process: subprocess.Popen[str],
        *,
        log_capacity: int,
    ) -> None:
        self._process = process
        self._log = LogRing(log_capacity)
        self._reader = threading.Thread(target=self._drain, name="llamacpp-log-drain", daemon=True)
        self._reader.start()

    @property
    def pid(self) -> int | None:
        return self._process.pid

    def terminate(self) -> None:
        self._process.terminate()

    def kill(self) -> None:
        self._process.kill()

    def poll(self) -> int | None:
        return self._process.poll()

    def wait(self, timeout: float) -> int | None:
        try:
            return self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    def lines(self, limit: int | None = None) -> tuple[str, ...]:
        return self._log.snapshot(limit=limit)

    def _drain(self) -> None:
        assert self._process.stdout is not None
        for line in self._process.stdout:
            self._log.append(line.rstrip())


class LogRing:
    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("log capacity must be positive")
        self._capacity = capacity
        self._lines: deque[str] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def append(self, line: str) -> None:
        with self._lock:
            self._lines.append(line)

    def snapshot(self, limit: int | None = None) -> tuple[str, ...]:
        with self._lock:
            lines = tuple(self._lines)
        if limit is None or limit >= len(lines):
            return lines
        return lines[-limit:]


class EngineCommandError(RuntimeError):
    """A llama.cpp lifecycle command failed."""


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


class LlamaCppEngine:
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
        if binary.is_symlink() or not binary.is_file():
            raise EngineCommandError("engine binary must be a regular file")
        root = owned_root.resolve()
        if root == Path("/") or root.is_symlink():
            raise EngineCommandError("owned root must be a regular directory")
        model = configuration.model_path.resolve()
        if model != root and root not in model.parents:
            raise EngineCommandError("model path escapes the owned root")
        self._configuration = configuration
        self._binary = binary
        self._root = root
        self._probe = probe or SubprocessCapabilityProbe()
        self._runner = runner or NativeEngineRunner()
        self._port_probe = port_probe or SocketPortProbe()
        self._client = client
        self._timeout = httpx.Timeout(timeout_seconds)
        self._capabilities: LlamaCppCapabilities | None = None
        self._preflight_ok = False
        self._process: ProcessHandle | None = None

    @property
    def configuration(self) -> LlamaCppConfiguration:
        return self._configuration

    @property
    def owned_root(self) -> Path:
        return self._root

    def capabilities(self) -> LlamaCppCapabilities:
        if self._capabilities is None:
            output = self._probe.probe(self._binary)
            try:
                self._capabilities = parse_llamacpp_version(output)
            except ValueError as error:
                raise EngineCommandError("engine version could not be determined") from error
        return self._capabilities

    def preflight(
        self,
        *,
        expected_binary_digest: str | None = None,
        minimum_build: int = STABLE_MINIMUM_BUILD,
    ) -> tuple[str, ...]:
        violations: list[str] = []
        binary = self._binary
        if binary.is_symlink() or not binary.is_file():
            violations.append("engine binary is missing or unsafe")
        elif expected_binary_digest is not None:
            actual = hashlib.sha256(binary.read_bytes()).hexdigest()
            if actual != expected_binary_digest:
                violations.append("engine binary digest does not match its manifest")
        if not self._port_probe.is_free(self._configuration.host, self._configuration.port):
            violations.append("engine port is already in use")
        model = self._configuration.model_path
        if model.is_symlink() or not model.is_file():
            violations.append("model artifact is missing or unsafe")
        try:
            caps = self.capabilities()
        except EngineCommandError as error:
            violations.append(str(error))
            caps = None
        if caps is not None:
            if not caps.supported:
                violations.append(f"engine build b{caps.build} has no completed evidence lane")
            if caps.build < minimum_build:
                violations.append(
                    f"engine build b{caps.build} is below the minimum b{minimum_build}"
                )
        self._preflight_ok = not violations
        return tuple(violations)

    def start(self) -> None:
        if self._process is not None and self._process.poll() is None:
            raise EngineCommandError("engine is already running")
        if not self._preflight_ok:
            raise EngineCommandError("preflight must pass before start")
        command = (str(self._binary), *self._configuration.render_arguments())
        try:
            self._process = self._runner.launch(command)
        except OSError as error:
            raise EngineCommandError(f"engine launch failed: {error}") from error

    def logs(self, limit: int | None = None) -> tuple[str, ...]:
        if self._process is None:
            return ()
        return self._process.lines(limit=limit)

    def stop(self, *, grace_seconds: float = 30.0) -> None:
        process = self._process
        if process is None or process.poll() is not None:
            self._process = None
            return
        process.terminate()
        deadline = grace_seconds
        while deadline > 0 and process.poll() is None:
            time.sleep(0.05)
            deadline -= 0.05
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        self._process = None

    def cleanup(self) -> None:
        self.stop(grace_seconds=1.0)

    async def health(self) -> Evidence:
        started = time.monotonic()
        now = datetime.now(UTC)
        state = HealthState.UNKNOWN
        code = "llamacpp_unknown"
        summary = "Engine health could not be determined"
        try:
            response = await self._request("GET", "/health")
            state = parse_llamacpp_health(response.text)
            code = "llamacpp_ready" if state is HealthState.READY else "llamacpp_not_ready"
            summary = (
                "Engine API is serving" if state is HealthState.READY else "Engine API is not ready"
            )
        except httpx.HTTPStatusError as error:
            state = (
                HealthState.STARTING
                if error.response.status_code in {503, 425}
                else HealthState.DEGRADED
            )
            code = "llamacpp_starting" if state is HealthState.STARTING else "llamacpp_http_error"
            summary = "Engine API is not ready"
        except (httpx.TimeoutException, httpx.NetworkError):
            state = HealthState.UNREACHABLE
            code = "llamacpp_unreachable"
            summary = "Engine API is unreachable"
        except ValueError as error:
            state = HealthState.INCOMPATIBLE
            code = "llamacpp_incompatible"
            summary = str(error)
        duration = max(0.0, time.monotonic() - started)
        return Evidence(
            state=state,
            reason_code=code,
            summary=summary,
            observed_at=now,
            duration=timedelta(seconds=duration),
            source="llamacpp_health",
            expires_at=now + timedelta(seconds=30),
        )

    async def metrics(self) -> MetricsSnapshot:
        response = await self._request("GET", "/metrics")
        return parse_llamacpp_metrics(response.text)

    async def _request(self, method: str, path: str) -> httpx.Response:
        url = f"http://{self._configuration.host}:{self._configuration.port}{path}"
        if self._client is None:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.request(method, url)
        else:
            response = await self._client.request(method, url, timeout=self._timeout)
        response.raise_for_status()
        return response
