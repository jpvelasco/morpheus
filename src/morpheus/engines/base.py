"""Shared engine runtime lifecycle (RUNM-002).

Typed engine contract: capability detection, immutable configuration
rendering, preflight, start, health, metrics, logs, graceful stop, and
cleanup. Engines differ only in their configuration renderer, version
parser, health/metrics parsers, and evidence policy; the lifecycle itself
is shared and engine-neutral.
"""

from __future__ import annotations

import hashlib
import socket
import subprocess  # nosec B404
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

import httpx

from morpheus.core.health import Evidence, HealthState
from morpheus.core.metrics import MetricsSnapshot


class EngineConfiguration(Protocol):
    model_path: Path
    host: str
    port: int

    def render_arguments(self) -> tuple[str, ...]: ...

    def render_digest(self) -> str: ...


@dataclass(frozen=True, slots=True)
class EngineCapabilities:
    """Typed capability report for one probed engine binary."""

    label: str
    version: str
    supported: bool
    build: int | None = None


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
        self._reader = threading.Thread(target=self._drain, name="engine-log-drain", daemon=True)
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
    """An engine lifecycle command failed."""


class EngineRuntime:
    """Engine-neutral lifecycle shared by every managed engine tier.

    Engines inject their version/health/metrics parsers, render their own
    immutable configuration, and contribute extra preflight violations.
    """

    def __init__(
        self,
        *,
        name: str,
        configuration: EngineConfiguration,
        binary: Path,
        owned_root: Path,
        probe: CapabilityProbe | None = None,
        runner: EngineRunner | None = None,
        port_probe: PortProbe | None = None,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 5.0,
        version_parser: Callable[[str], EngineCapabilities],
        health_parser: Callable[[str], HealthState],
        metrics_parser: Callable[[str], MetricsSnapshot],
        extra_preflight: Callable[[], tuple[str, ...]] | None = None,
    ) -> None:
        if binary.is_symlink() or not binary.is_file():
            raise EngineCommandError("engine binary must be a regular file")
        root = owned_root.resolve()
        if root == Path("/") or root.is_symlink():
            raise EngineCommandError("owned root must be a regular directory")
        model = configuration.model_path.resolve()
        if model != root and root not in model.parents:
            raise EngineCommandError("model path escapes the owned root")
        self._name = name
        self._configuration = configuration
        self._binary = binary
        self._root = root
        self._probe = probe or SubprocessCapabilityProbe()
        self._runner = runner or NativeEngineRunner()
        self._port_probe = port_probe or SocketPortProbe()
        self._client = client
        self._timeout = httpx.Timeout(timeout_seconds)
        self._version_parser = version_parser
        self._health_parser = health_parser
        self._metrics_parser = metrics_parser
        self._extra_preflight = extra_preflight
        self._capabilities: EngineCapabilities | None = None
        self._preflight_ok = False
        self._process: ProcessHandle | None = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def configuration(self) -> EngineConfiguration:
        return self._configuration

    @property
    def owned_root(self) -> Path:
        return self._root

    def capabilities(self) -> EngineCapabilities:
        if self._capabilities is None:
            output = self._probe.probe(self._binary)
            try:
                self._capabilities = self._version_parser(output)
            except ValueError as error:
                raise EngineCommandError("engine version could not be determined") from error
        return self._capabilities

    def preflight(
        self,
        *,
        expected_binary_digest: str | None = None,
        minimum_build: int | None = None,
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
                violations.append(f"{caps.label} has no completed evidence lane")
            if caps.build is not None and minimum_build is not None and caps.build < minimum_build:
                violations.append(f"{caps.label} is below the minimum build b{minimum_build}")
        if self._extra_preflight is not None:
            violations.extend(self._extra_preflight())
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
        code = f"{self._name}_unknown"
        summary = "Engine health could not be determined"
        try:
            response = await self._request("GET", "/health")
            state = self._health_parser(response.text)
            if state is HealthState.READY:
                code = f"{self._name}_ready"
                summary = "Engine API is serving"
            else:
                code = f"{self._name}_not_ready"
                summary = "Engine API is not ready"
        except httpx.HTTPStatusError as error:
            if error.response.status_code in {503, 425}:
                state = HealthState.STARTING
                code = f"{self._name}_starting"
            else:
                state = HealthState.DEGRADED
                code = f"{self._name}_http_error"
            summary = "Engine API is not ready"
        except (httpx.TimeoutException, httpx.NetworkError):
            state = HealthState.UNREACHABLE
            code = f"{self._name}_unreachable"
            summary = "Engine API is unreachable"
        except ValueError as error:
            state = HealthState.INCOMPATIBLE
            code = f"{self._name}_incompatible"
            summary = str(error)
        duration = max(0.0, time.monotonic() - started)
        return Evidence(
            state=state,
            reason_code=code,
            summary=summary,
            observed_at=now,
            duration=timedelta(seconds=duration),
            source=f"{self._name}_health",
            expires_at=now + timedelta(seconds=30),
        )

    async def metrics(self) -> MetricsSnapshot:
        response = await self._request("GET", "/metrics")
        return self._metrics_parser(response.text)

    async def _request(self, method: str, path: str) -> httpx.Response:
        url = f"http://{self._configuration.host}:{self._configuration.port}{path}"
        if self._client is None:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.request(method, url)
        else:
            response = await self._client.request(method, url, timeout=self._timeout)
        response.raise_for_status()
        return response
