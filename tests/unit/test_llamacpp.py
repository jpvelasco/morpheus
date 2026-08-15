"""Unit tests: llama.cpp engine adapter (RUNM-002)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from morpheus.core.health import HealthState
from morpheus.core.metrics import MetricsSnapshot
from morpheus.engines.llamacpp import (
    EngineCommandError,
    LlamaCppConfiguration,
    LlamaCppEngine,
    LogRing,
    parse_llamacpp_health,
    parse_llamacpp_metrics,
    parse_llamacpp_version,
)

KNOWN_GOOD = "build: 6139 (9ce9e0b) with version 3.1.2\nllama.cpp mainline build 6139"
KNOWN_EXPERIMENTAL = "build: 3155 with version 2.5.1"
UNKNOWN_BUILD = "build: 9001 with version 9.9.9"


class FakeProbe:
    def __init__(self, output: str) -> None:
        self.output = output

    def probe(self, binary: Path) -> str:
        del binary
        return self.output


class FakePortProbe:
    def __init__(self, free: bool = True) -> None:
        self.free = free

    def is_free(self, host: str, port: int) -> bool:
        del host, port
        return self.free


class FakeProcess:
    def __init__(self, *, poll_result: int | None = None) -> None:
        self._poll = poll_result
        self.terminated = 0
        self.killed = 0
        self.wait_timeout: float | None = None
        self.ignore_terminate = False
        self._lines: tuple[str, ...] = ()

    @property
    def pid(self) -> int | None:
        return 4242

    def terminate(self) -> None:
        self.terminated += 1
        if not self.ignore_terminate:
            self._poll = 0

    def kill(self) -> None:
        self.killed += 1
        self._poll = 137

    def poll(self) -> int | None:
        return self._poll

    def wait(self, timeout: float) -> int | None:
        self.wait_timeout = timeout
        return self._poll

    def lines(self, limit: int | None = None) -> tuple[str, ...]:
        if limit is None:
            return self._lines
        return self._lines[-limit:]

    def append_lines(self, *lines: str) -> None:
        self._lines = self._lines + lines


class FakeRunner:
    def __init__(self) -> None:
        self.process = FakeProcess()
        self.commands: list[tuple[str, ...]] = []

    def launch(self, command: tuple[str, ...]) -> FakeProcess:
        self.commands.append(command)
        return self.process


def config(model: Path, **overrides) -> LlamaCppConfiguration:
    fields = {"model_path": model}
    fields.update(overrides)
    return LlamaCppConfiguration(**fields)


def engine(
    tmp_path: Path,
    *,
    config_overrides: dict | None = None,
    probe_output: str = KNOWN_GOOD,
    port_free: bool = True,
) -> tuple[LlamaCppEngine, FakeRunner]:
    root = tmp_path / "root"
    root.mkdir(exist_ok=True)
    binary = tmp_path / "llama-server"
    binary.write_bytes(b"engine")
    model = root / "model.gguf"
    model.write_bytes(b"model")
    runner = FakeRunner()
    engine = LlamaCppEngine(
        configuration=config(model, **(config_overrides or {})),
        binary=binary,
        owned_root=root,
        probe=FakeProbe(probe_output),
        runner=runner,
        port_probe=FakePortProbe(port_free),
    )
    return engine, runner


def test_parse_version_known_good_build() -> None:
    caps = parse_llamacpp_version(KNOWN_GOOD)
    assert caps.build == 6139
    assert caps.version == "3.1.2"
    assert caps.supported is True
    assert caps.streaming and caps.tools and caps.structured_output


def test_parse_version_experimental_and_unknown_builds() -> None:
    assert parse_llamacpp_version(KNOWN_EXPERIMENTAL).supported is False
    assert parse_llamacpp_version(UNKNOWN_BUILD).supported is False


def test_parse_version_rejects_unrecognized_output() -> None:
    with pytest.raises(ValueError, match="unrecognized"):
        parse_llamacpp_version("llama.cpp: no such command")


def test_configuration_validation_bounds() -> None:
    model = Path("C:/models/model.gguf") if Path("C:/").exists() else Path("/models/model.gguf")
    with pytest.raises(ValueError, match="absolute"):
        LlamaCppConfiguration(model_path=Path("relative/model.gguf"))
    with pytest.raises(ValueError, match="port"):
        config(model, port=0)
    with pytest.raises(ValueError, match="port"):
        config(model, port=70000)
    with pytest.raises(ValueError, match="threads"):
        config(model, threads=0)
    with pytest.raises(ValueError, match="context"):
        config(model, context_window=128)
    with pytest.raises(ValueError, match="parallel"):
        config(model, parallel_slots=0)
    with pytest.raises(ValueError, match="gpu layers"):
        config(model, gpu_layers=-2)
    with pytest.raises(ValueError, match="host"):
        config(model, host="  ")


def test_configuration_rendering_is_immutable_and_canonical() -> None:
    model = Path("C:/models/model.gguf") if Path("C:/").exists() else Path("/models/model.gguf")
    configuration = config(
        model,
        port=9100,
        threads=8,
        context_window=8192,
        parallel_slots=2,
        gpu_layers=-1,
        alias="dev-model",
        json_schema='{"type":"object"}',
    )
    first = configuration.render_arguments()
    second = configuration.render_arguments()
    assert first == second
    assert first[0] == "--model"
    assert str(model) in first
    assert first[first.index("--port") + 1] == "9100"
    assert "--alias" in first
    assert "--json-schema" in first
    assert configuration.render_digest() == configuration.render_digest()


def test_configuration_digest_changes_with_every_field() -> None:
    model = Path("C:/models/model.gguf") if Path("C:/").exists() else Path("/models/model.gguf")
    base = config(model)
    baseline = base.render_digest()
    for override in (
        {"host": "127.0.0.2"},
        {"port": 9100},
        {"threads": 8},
        {"context_window": 8192},
        {"parallel_slots": 2},
        {"gpu_layers": -1},
        {"seed": 7},
        {"alias": "dev-model"},
        {"json_schema": '{"type":"object"}'},
    ):
        assert config(model, **override).render_digest() != baseline


def test_engine_constructor_rejects_symlink_binary_and_escaping_model(tmp_path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.gguf"
    outside.write_bytes(b"x")
    binary = tmp_path / "llama-server"
    binary.write_bytes(b"engine")
    with pytest.raises(EngineCommandError, match="escapes"):
        LlamaCppEngine(
            configuration=config(outside),
            binary=binary,
            owned_root=root,
            probe=FakeProbe(KNOWN_GOOD),
        )


def test_preflight_accepts_healthy_system(tmp_path) -> None:
    engine_, _ = engine(tmp_path)
    assert engine_.preflight() == ()


def test_preflight_reports_digest_port_and_evidence_violations(tmp_path) -> None:
    engine_, _ = engine(tmp_path, probe_output=UNKNOWN_BUILD, port_free=False)
    violations = engine_.preflight(expected_binary_digest="0" * 64)
    joined = " ".join(violations)
    assert "digest" in joined
    assert "port" in joined
    assert "evidence lane" in joined


def test_preflight_requires_existing_model_artifact(tmp_path) -> None:
    root = tmp_path / "root"
    engine_, _ = engine(tmp_path, config_overrides={"model_path": root / "missing.gguf"})
    assert "model artifact" in " ".join(engine_.preflight())


def test_start_requires_passed_preflight(tmp_path) -> None:
    engine_, runner = engine(tmp_path, port_free=False)
    engine_.preflight()
    with pytest.raises(EngineCommandError, match="preflight"):
        engine_.start()
    assert runner.commands == []


def test_start_launches_rendered_command_once(tmp_path) -> None:
    engine_, runner = engine(tmp_path)
    assert engine_.preflight() == ()
    engine_.start()
    assert len(runner.commands) == 1
    assert runner.commands[0][0].endswith("llama-server")
    assert runner.commands[0][1:] == engine_.configuration.render_arguments()
    with pytest.raises(EngineCommandError, match="already running"):
        engine_.start()


def test_stop_terminates_then_escalates_to_kill(tmp_path) -> None:
    engine_, runner = engine(tmp_path)
    assert engine_.preflight() == ()
    engine_.start()
    runner.process.ignore_terminate = True
    engine_.stop(grace_seconds=0.05)
    assert runner.process.terminated == 1
    assert runner.process.killed == 1
    assert engine_._process is None
    engine_.stop(grace_seconds=0.05)


def test_stop_is_idempotent_when_process_already_exited(tmp_path) -> None:
    engine_, runner = engine(tmp_path)
    assert engine_.preflight() == ()
    engine_.start()
    engine_.stop(grace_seconds=0.05)
    engine_.stop(grace_seconds=0.05)
    assert runner.process.terminated == 1


def test_logs_are_bounded_and_ordered() -> None:
    ring = LogRing(3)
    ring.append("a")
    ring.append("b")
    ring.append("c")
    ring.append("d")
    assert ring.snapshot() == ("b", "c", "d")
    assert ring.snapshot(limit=2) == ("c", "d")
    with pytest.raises(ValueError, match="capacity"):
        LogRing(0)


def test_engine_logs_surface_process_lines(tmp_path) -> None:
    engine_, runner = engine(tmp_path)
    assert engine_.preflight() == ()
    assert engine_.logs() == ()
    engine_.start()
    runner.process.append_lines("main: model loaded", "HTTP server listening")
    assert engine_.logs() == ("main: model loaded", "HTTP server listening")
    assert engine_.logs(limit=1) == ("HTTP server listening",)


def test_parse_health_corpora() -> None:
    assert parse_llamacpp_health('{"status": "ok", "slots_idle": 2}') is HealthState.READY
    assert parse_llamacpp_health('{"status": "loading model"}') is HealthState.STARTING
    assert parse_llamacpp_health('{"status": "no slot available"}') is HealthState.STARTING
    assert parse_llamacpp_health('{"status": "error"}') is HealthState.DEGRADED
    with pytest.raises(ValueError, match="invalid"):
        parse_llamacpp_health("not json")
    with pytest.raises(ValueError, match="invalid"):
        parse_llamacpp_health('{"status": 4}')


def test_parse_metrics_corpus() -> None:
    text = "\n".join(
        (
            "# TYPE llama:request_success_total counter",
            'llama:request_success_total{model="m"} 12',
            "# TYPE llama:generation_tokens_total counter",
            'llama:generation_tokens_total{model="m"} 2048',
        )
    )
    snapshot = parse_llamacpp_metrics(text)
    assert snapshot.values["request_success_total"] == 12.0
    assert snapshot.values["generation_tokens_total"] == 2048.0
    assert snapshot.available_signals == frozenset(
        {"request_success_total", "generation_tokens_total"}
    )
    assert "prompt_tokens_total" in snapshot.missing_signals


def test_parse_metrics_rejects_invalid_text() -> None:
    with pytest.raises(ValueError, match="invalid"):
        parse_llamacpp_metrics("broken!!!not metrics")


async def test_health_maps_http_corpora(tmp_path) -> None:
    engine_, _ = engine(tmp_path)

    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"status": "ok", "slots_idle": 1})

    engine_._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert (await engine_.health()).state is HealthState.READY
    await engine_._client.aclose()

    engine_, _ = engine(tmp_path)
    engine_._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, text="loading"))
    )
    assert (await engine_.health()).state is HealthState.STARTING
    await engine_._client.aclose()


async def test_health_maps_unreachable_and_incompatible(tmp_path) -> None:
    engine_, _ = engine(tmp_path)

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("fixture", request=request)

    engine_._client = httpx.AsyncClient(transport=httpx.MockTransport(timeout))
    assert (await engine_.health()).state is HealthState.UNREACHABLE
    await engine_._client.aclose()

    engine_, _ = engine(tmp_path)
    engine_._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="garbage"))
    )
    assert (await engine_.health()).state is HealthState.INCOMPATIBLE
    await engine_._client.aclose()


async def test_metrics_http_path_returns_parsed_snapshot(tmp_path) -> None:
    engine_, _ = engine(tmp_path)
    text = "# TYPE llama:kv_cache_usage_ratio gauge\nllama:kv_cache_usage_ratio 0.5"
    engine_._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=text))
    )
    snapshot = await engine_.metrics()
    assert isinstance(snapshot, MetricsSnapshot)
    assert snapshot.values["kv_cache_usage_ratio"] == 0.5
    await engine_._client.aclose()


def test_cleanup_stops_short_grace(tmp_path) -> None:
    engine_, runner = engine(tmp_path)
    assert engine_.preflight() == ()
    engine_.start()
    runner.process.ignore_terminate = True
    engine_.cleanup()
    assert runner.process.terminated == 1
    assert runner.process.killed == 1
    assert engine_._process is None
