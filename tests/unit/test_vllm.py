"""Unit tests: vLLM engine adapter (RUNM-002)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from morpheus.core.health import HealthState
from morpheus.core.metrics import MetricsSnapshot
from morpheus.engines.vllm import (
    EngineCommandError,
    VllmCapabilities,
    VllmConfiguration,
    VllmEngine,
    parse_vllm_health,
    parse_vllm_version,
)

KNOWN_GOOD = "vllm, version 0.9.2\nvLLM serving engine\n"
KNOWN_OLD = "vllm, version 0.6.0\n"
UNKNOWN_VERSION = "vllm, version 0.8.1\n"
ALT_FMT = "vLLM version 0.9.2\n"


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


def config(model: Path, **overrides) -> VllmConfiguration:
    fields = {"model_path": model}
    fields.update(overrides)
    return VllmConfiguration(**fields)


def engine(
    tmp_path: Path,
    *,
    config_overrides: dict | None = None,
    probe_output: str = KNOWN_GOOD,
    port_free: bool = True,
) -> tuple[VllmEngine, FakeRunner]:
    root = tmp_path / "root"
    root.mkdir(exist_ok=True)
    binary = tmp_path / "vllm"
    binary.write_bytes(b"engine")
    model = root / "model"
    model.write_bytes(b"model")
    runner = FakeRunner()
    engine = VllmEngine(
        configuration=config(model, **(config_overrides or {})),
        binary=binary,
        owned_root=root,
        probe=FakeProbe(probe_output),
        runner=runner,
        port_probe=FakePortProbe(port_free),
    )
    return engine, runner


def test_parse_version_known_good() -> None:
    caps = parse_vllm_version(KNOWN_GOOD)
    assert isinstance(caps, VllmCapabilities)
    assert caps.version == "0.9.2"
    assert caps.supported is True
    assert caps.nvidia_linux_only
    assert parse_vllm_version(ALT_FMT).version == "0.9.2"


def test_parse_version_unknown_and_old_are_unsupported() -> None:
    assert parse_vllm_version(UNKNOWN_VERSION).supported is False
    assert parse_vllm_version(KNOWN_OLD).supported is False


def test_parse_version_rejects_unrecognized_output() -> None:
    with pytest.raises(ValueError, match="unrecognized"):
        parse_vllm_version("vllm: no such command")


def test_configuration_validation_bounds() -> None:
    model = Path("C:/models/model") if Path("C:/").exists() else Path("/models/model")
    with pytest.raises(ValueError, match="absolute"):
        VllmConfiguration(model_path=Path("relative/model"))
    with pytest.raises(ValueError, match="port"):
        config(model, port=0)
    with pytest.raises(ValueError, match="port"):
        config(model, port=70000)
    with pytest.raises(ValueError, match="max model length"):
        config(model, max_model_len=128)
    with pytest.raises(ValueError, match="tensor parallel size"):
        config(model, tensor_parallel_size=0)
    with pytest.raises(ValueError, match="gpu memory utilization"):
        config(model, gpu_memory_utilization=1.0)
    with pytest.raises(ValueError, match="gpu memory utilization"):
        config(model, gpu_memory_utilization=0.01)
    with pytest.raises(ValueError, match="dtype"):
        config(model, dtype="fp8")
    with pytest.raises(ValueError, match="served model name"):
        config(model, served_model_name="bad name")
    with pytest.raises(ValueError, match="quantization"):
        config(model, quantization="awq bad")
    with pytest.raises(ValueError, match="max num seqs"):
        config(model, max_num_seqs=0)
    with pytest.raises(ValueError, match="host"):
        config(model, host="  ")


def test_configuration_rendering_is_immutable_and_canonical() -> None:
    model = Path("C:/models/model") if Path("C:/").exists() else Path("/models/model")
    configuration = config(
        model,
        port=9100,
        served_model_name="dev-model",
        max_model_len=16384,
        tensor_parallel_size=2,
        gpu_memory_utilization=0.85,
        dtype="bfloat16",
        quantization="awq",
        max_num_seqs=128,
        seed=7,
        json_schema='{"type":"object"}',
    )
    first = configuration.render_arguments()
    second = configuration.render_arguments()
    assert first == second
    assert first[0] == "--model"
    assert str(model) in first
    assert first[first.index("--port") + 1] == "9100"
    assert first[first.index("--gpu-memory-utilization") + 1] == "0.85"
    assert "--quantization" in first
    assert "--guided-json" in first
    assert configuration.render_digest() == configuration.render_digest()


def test_configuration_digest_changes_with_every_field() -> None:
    model = Path("C:/models/model") if Path("C:/").exists() else Path("/models/model")
    baseline = config(model).render_digest()
    for override in (
        {"host": "127.0.0.2"},
        {"port": 9100},
        {"served_model_name": "other-name"},
        {"max_model_len": 16384},
        {"tensor_parallel_size": 2},
        {"gpu_memory_utilization": 0.85},
        {"dtype": "bfloat16"},
        {"quantization": "awq"},
        {"max_num_seqs": 128},
        {"seed": 7},
        {"json_schema": '{"type":"object"}'},
    ):
        assert config(model, **override).render_digest() != baseline


def test_engine_constructor_rejects_symlink_binary_and_escaping_model(tmp_path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"x")
    binary = tmp_path / "vllm"
    binary.write_bytes(b"engine")
    with pytest.raises(EngineCommandError, match="escapes"):
        VllmEngine(
            configuration=config(outside),
            binary=binary,
            owned_root=root,
            probe=FakeProbe(KNOWN_GOOD),
        )


def test_preflight_accepts_healthy_system(tmp_path) -> None:
    engine_, _ = engine(tmp_path)
    assert engine_.preflight() == ()


def test_preflight_reports_digest_port_and_evidence_violations(tmp_path) -> None:
    engine_, _ = engine(tmp_path, probe_output=UNKNOWN_VERSION, port_free=False)
    violations = engine_.preflight(expected_binary_digest="0" * 64)
    joined = " ".join(violations)
    assert "digest" in joined
    assert "port" in joined
    assert "evidence lane" in joined


def test_preflight_rejects_below_minimum_version(tmp_path) -> None:
    engine_, _ = engine(tmp_path, probe_output=KNOWN_OLD)
    violations = engine_.preflight()
    joined = " ".join(violations)
    assert "below the minimum version" in joined
    assert "evidence lane" in joined


def test_preflight_requires_existing_model_artifact(tmp_path) -> None:
    root = tmp_path / "root"
    engine_, _ = engine(tmp_path, config_overrides={"model_path": root / "missing"})
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
    assert runner.commands[0][0].endswith("vllm")
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


def test_engine_logs_surface_process_lines(tmp_path) -> None:
    engine_, runner = engine(tmp_path)
    assert engine_.preflight() == ()
    assert engine_.logs() == ()
    engine_.start()
    runner.process.append_lines("INFO 06-21 14:00:00 main.py:71] Started server")
    assert engine_.logs() == ("INFO 06-21 14:00:00 main.py:71] Started server",)


def test_parse_health_corpora() -> None:
    assert parse_vllm_health("OK") is HealthState.READY
    assert parse_vllm_health("  ok\n") is HealthState.READY
    with pytest.raises(ValueError, match="invalid"):
        parse_vllm_health("still loading")
    with pytest.raises(ValueError, match="invalid"):
        parse_vllm_health("")


async def test_parse_metrics_reuses_vllm_signal_mapping(tmp_path) -> None:
    engine_, _ = engine(tmp_path)
    text = (
        "# TYPE vllm:num_requests_running gauge\n"
        "vllm:num_requests_running 3\n"
        "# TYPE vllm:generation_tokens_total counter\n"
        "vllm:generation_tokens_total 512\n"
    )
    engine_._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=text))
    )
    snapshot = await engine_.metrics()
    assert isinstance(snapshot, MetricsSnapshot)
    assert snapshot.values["requests_running"] == 3.0
    assert snapshot.values["generation_tokens_total"] == 512.0
    assert "gpu_cache_usage" in snapshot.missing_signals
    await engine_._client.aclose()


async def test_health_maps_http_corpora(tmp_path) -> None:
    engine_, _ = engine(tmp_path)
    engine_._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="OK"))
    )
    assert (await engine_.health()).state is HealthState.READY
    await engine_._client.aclose()

    engine_, _ = engine(tmp_path)
    engine_._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, text="loading"))
    )
    assert (await engine_.health()).state is HealthState.STARTING
    await engine_._client.aclose()

    engine_, _ = engine(tmp_path)
    engine_._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="garbage"))
    )
    assert (await engine_.health()).state is HealthState.INCOMPATIBLE
    await engine_._client.aclose()


async def test_health_maps_unreachable(tmp_path) -> None:
    engine_, _ = engine(tmp_path)

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("fixture", request=request)

    engine_._client = httpx.AsyncClient(transport=httpx.MockTransport(timeout))
    assert (await engine_.health()).state is HealthState.UNREACHABLE
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
