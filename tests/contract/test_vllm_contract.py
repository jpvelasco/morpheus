"""Contract tests: vLLM engine adapter (RUNM-002).

Guarantees:
- Configuration rendering is immutable and canonical; any single field
  change alters the render digest, and rendered arguments are plain string
  tokens (never a shell string) that identify the exact launch command.
- Preflight has no side effects: it never writes, launches, or contacts
  anything, and rejects symlinked binaries, symlinked or missing model
  artifacts, busy ports, digest mismatches, evidence-less versions, and
  versions below the stable minimum.
- Start launches exactly the rendered command once; a second start is
  rejected; after stop/cleanup the engine can be started again (recovery).
- Stop is graceful with escalation: terminate first, kill after grace, and
  the process handle is always released; stop/cleanup are idempotent.
- Health and metrics corpora map to exact typed states and signals, and
  invalid documents are rejected rather than guessed.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest

from morpheus.adapters.metrics.vllm import parse_vllm_metrics
from morpheus.core.health import HealthState
from morpheus.engines.vllm import (
    KNOWN_GOOD_VERSIONS,
    STABLE_MINIMUM_VERSION,
    EngineCommandError,
    VllmConfiguration,
    VllmEngine,
    parse_vllm_health,
    parse_vllm_version,
)

pytestmark = pytest.mark.contract

KNOWN_GOOD = "vllm, version 0.9.2"
KNOWN_OLD = "vllm, version 0.6.0"
UNKNOWN_VERSION = "vllm, version 0.8.1"


class FakeProbe:
    def __init__(self, output: str) -> None:
        self.output = output
        self.calls = 0

    def probe(self, binary: Path) -> str:
        self.calls += 1
        return self.output


class FakePortProbe:
    def __init__(self, free: bool = True) -> None:
        self.free = free
        self.calls = 0

    def is_free(self, host: str, port: int) -> bool:
        self.calls += 1
        return self.free


class FakeProcess:
    def __init__(self) -> None:
        self.terminated = 0
        self.killed = 0
        self._poll: int | None = None
        self.ignore_terminate = False
        self.lines_: tuple[str, ...] = ()

    @property
    def pid(self) -> int | None:
        return 777

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
        return self._poll

    def lines(self, limit: int | None = None) -> tuple[str, ...]:
        if limit is None:
            return self.lines_
        return self.lines_[-limit:]


class FakeRunner:
    def __init__(self) -> None:
        self.process = FakeProcess()
        self.commands: list[tuple[str, ...]] = []

    def launch(self, command: tuple[str, ...]) -> FakeProcess:
        self.commands.append(command)
        return self.process


def build_engine(tmp_path: Path, **engine_overrides) -> tuple[VllmEngine, dict[str, object]]:
    root = tmp_path / "root"
    root.mkdir(exist_ok=True)
    binary = tmp_path / "vllm"
    binary.write_bytes(b"engine-binary")
    model = root / "model"
    model.unlink(missing_ok=True)
    model.write_bytes(b"model-artifact")
    probe = FakeProbe(engine_overrides.pop("probe_output", KNOWN_GOOD))
    port = FakePortProbe(engine_overrides.pop("port_free", True))
    runner = FakeRunner()
    configuration = VllmConfiguration(model_path=model, port=8300)
    engine = VllmEngine(
        configuration=configuration,
        binary=binary,
        owned_root=root,
        probe=probe,
        runner=runner,
        port_probe=port,
        **engine_overrides,
    )
    return (
        engine,
        {"probe": probe, "port": port, "runner": runner, "binary": binary, "model": model},
    )


def test_configuration_rendering_is_immutable_and_token_exact() -> None:
    model = Path("C:/models/m") if Path("C:/").exists() else Path("/models/m")
    configuration = VllmConfiguration(
        model_path=model,
        port=8300,
        served_model_name="morpheus-managed",
        max_model_len=16384,
        tensor_parallel_size=2,
        gpu_memory_utilization=0.85,
        dtype="bfloat16",
        quantization="awq",
        max_num_seqs=128,
        seed=42,
        json_schema='{"type":"object"}',
    )
    first = configuration.render_arguments()
    second = configuration.render_arguments()
    assert first == second
    assert first == (
        "--model",
        str(model),
        "--host",
        "127.0.0.1",
        "--port",
        "8300",
        "--served-model-name",
        "morpheus-managed",
        "--max-model-len",
        "16384",
        "--tensor-parallel-size",
        "2",
        "--gpu-memory-utilization",
        "0.85",
        "--dtype",
        "bfloat16",
        "--max-num-seqs",
        "128",
        "--quantization",
        "awq",
        "--seed",
        "42",
        "--guided-json",
        '{"type":"object"}',
    )
    assert all(isinstance(token, str) for token in first)
    assert configuration.render_digest() == hashlib.sha256("\0".join(first).encode()).hexdigest()


def test_any_single_field_change_alters_render_digest() -> None:
    model = Path("C:/models/m") if Path("C:/").exists() else Path("/models/m")
    base = VllmConfiguration(model_path=model)
    baseline = base.render_digest()
    assert len(baseline) == 64
    assert baseline != VllmConfiguration(model_path=model, port=1).render_digest()
    assert baseline != VllmConfiguration(model_path=model, port=65535).render_digest()
    assert baseline != VllmConfiguration(model_path=model, host="127.0.0.2").render_digest()
    assert baseline != VllmConfiguration(model_path=model, served_model_name="x").render_digest()
    assert baseline != VllmConfiguration(model_path=model, max_model_len=256).render_digest()
    assert baseline != VllmConfiguration(model_path=model, tensor_parallel_size=4).render_digest()
    assert (
        baseline != VllmConfiguration(model_path=model, gpu_memory_utilization=0.5).render_digest()
    )
    assert baseline != VllmConfiguration(model_path=model, dtype="float16").render_digest()
    assert baseline != VllmConfiguration(model_path=model, quantization="awq").render_digest()
    assert baseline != VllmConfiguration(model_path=model, max_num_seqs=64).render_digest()
    assert baseline != VllmConfiguration(model_path=model, seed=7).render_digest()
    assert baseline != VllmConfiguration(model_path=model, json_schema="{}").render_digest()


def test_preflight_has_no_side_effects(tmp_path) -> None:
    engine, handles = build_engine(tmp_path)
    binary_bytes = handles["binary"].read_bytes()
    model_bytes = handles["model"].read_bytes()
    before = set(tmp_path.rglob("*"))
    assert engine.preflight() == ()
    after = set(tmp_path.rglob("*"))
    assert before == after
    assert handles["binary"].read_bytes() == binary_bytes
    assert handles["model"].read_bytes() == model_bytes
    assert handles["runner"].commands == []
    assert handles["port"].calls == 1


def test_preflight_rejects_every_evidence_gate(tmp_path) -> None:
    engine, handles = build_engine(tmp_path)
    binary = handles["binary"]
    model = handles["model"]
    matching = hashlib.sha256(binary.read_bytes()).hexdigest()
    assert engine.preflight(expected_binary_digest=matching) == ()

    wrong_digest = "0" * 64
    violations = engine.preflight(expected_binary_digest=wrong_digest)
    assert any("digest" in item for item in violations)

    model.unlink()
    violations = engine.preflight(expected_binary_digest=matching)
    assert any("model artifact" in item for item in violations)

    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"x")
    model.symlink_to(outside)
    violations = engine.preflight(expected_binary_digest=matching)
    assert any("model artifact" in item for item in violations)

    engine, handles = build_engine(tmp_path, probe_output=UNKNOWN_VERSION)
    violations = engine.preflight()
    assert any("evidence lane" in item for item in violations)

    engine, _ = build_engine(tmp_path, probe_output=KNOWN_OLD)
    violations = engine.preflight()
    joined = " ".join(violations)
    assert "below the minimum version" in joined
    assert STABLE_MINIMUM_VERSION in joined

    engine, _ = build_engine(tmp_path, port_free=False)
    violations = engine.preflight()
    assert any("port" in item for item in violations)


def test_symlinked_binary_is_rejected_at_construction(tmp_path) -> None:
    root = tmp_path / "root"
    root.mkdir(exist_ok=True)
    target = tmp_path / "real-binary"
    target.write_bytes(b"engine")
    link = tmp_path / "vllm"
    link.symlink_to(target)
    model = root / "model"
    model.write_bytes(b"model")
    with pytest.raises(EngineCommandError, match="regular file"):
        VllmEngine(
            configuration=VllmConfiguration(model_path=model),
            binary=link,
            owned_root=root,
            probe=FakeProbe(KNOWN_GOOD),
        )


def test_start_launches_rendered_command_exactly_once_and_recovers_after_stop(
    tmp_path,
) -> None:
    engine, handles = build_engine(tmp_path)
    assert engine.preflight() == ()
    engine.start()
    assert len(handles["runner"].commands) == 1
    launched = handles["runner"].commands[0]
    assert launched == (
        str(handles["binary"]),
        *engine.configuration.render_arguments(),
    )
    with pytest.raises(EngineCommandError, match="already running"):
        engine.start()
    engine.stop(grace_seconds=0.05)
    engine.start()
    assert len(handles["runner"].commands) == 2


def test_stop_escalates_and_releases_handle(tmp_path) -> None:
    engine, handles = build_engine(tmp_path)
    assert engine.preflight() == ()
    engine.start()
    handles["runner"].process.ignore_terminate = True
    engine.stop(grace_seconds=0.05)
    assert handles["runner"].process.terminated == 1
    assert handles["runner"].process.killed == 1
    assert engine._process is None
    engine.stop(grace_seconds=0.05)
    engine.cleanup()
    assert handles["runner"].process.terminated == 1


def test_health_corpus_maps_exact_states() -> None:
    assert parse_vllm_health("OK") is HealthState.READY
    assert parse_vllm_health("ok") is HealthState.READY
    assert parse_vllm_health(" Ok \n") is HealthState.READY
    for broken in ("", "loading", "[]", '{"status":"ok"}', "not json"):
        with pytest.raises(ValueError, match="invalid"):
            parse_vllm_health(broken)


def test_metrics_corpus_and_empty_document() -> None:
    full = "\n".join(
        (
            "# TYPE vllm:num_requests_running gauge",
            "vllm:num_requests_running 3",
            "# TYPE vllm:gpu_cache_usage_perc gauge",
            "vllm:gpu_cache_usage_perc 0.42",
            "# TYPE vllm:request_success_total counter",
            "vllm:request_success_total 17",
        )
    )
    snapshot = parse_vllm_metrics(full)
    assert snapshot.values == {
        "requests_running": 3.0,
        "gpu_cache_usage": 0.42,
        "request_success_total": 17.0,
    }
    assert snapshot.available_signals == frozenset(
        {"requests_running", "gpu_cache_usage", "request_success_total"}
    )
    assert "generation_tokens_total" in snapshot.missing_signals
    empty = parse_vllm_metrics("")
    assert empty.values == {}
    assert empty.missing_signals == frozenset(
        {
            "requests_running",
            "requests_waiting",
            "gpu_cache_usage",
            "prompt_tokens_total",
            "generation_tokens_total",
            "request_success_total",
        }
    )
    with pytest.raises(ValueError, match="invalid"):
        parse_vllm_metrics("# TYPE broken counter\nbroken not a metric value")


def test_capability_evidence_corpus() -> None:
    assert frozenset({"0.9.2"}) == KNOWN_GOOD_VERSIONS
    assert parse_vllm_version(KNOWN_GOOD).supported is True
    assert parse_vllm_version(UNKNOWN_VERSION).supported is False
    for output in ("", "vllm: command not found", "version 0.9.2 extra"):
        with pytest.raises(ValueError, match="unrecognized"):
            parse_vllm_version(output)


async def test_http_surface_never_touches_live_endpoint_during_preflight(
    tmp_path,
) -> None:
    engine, handles = build_engine(tmp_path)
    assert engine.preflight() == ()
    assert handles["runner"].commands == []
    engine._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="OK"))
    )
    await engine.health()
    await engine._client.aclose()
    assert handles["runner"].commands == []
    assert handles["port"].calls == 1


async def test_health_http_contract_maps_ready(tmp_path) -> None:
    engine, _ = build_engine(tmp_path)

    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, text="OK")

    engine._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    evidence = await engine.health()
    assert evidence.state is HealthState.READY
    assert evidence.reason_code == "vllm_ready"
    assert evidence.source == "vllm_health"
    await engine._client.aclose()
