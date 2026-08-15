"""Contract tests: llama.cpp engine adapter (RUNM-002).

Guarantees:
- Configuration rendering is immutable and canonical; any single field
  change alters the render digest, and rendered arguments are plain string
  tokens (never a shell string) that identify the exact launch command.
- Preflight has no side effects: it never writes, launches, or contacts
  anything, and rejects symlinked binaries, symlinked or missing model
  artifacts, busy ports, digest mismatches, and evidence-less builds.
- Start launches exactly the rendered command once; a second start is
  rejected; after stop/cleanup the engine can be started again (recovery).
- Stop is graceful with escalation: terminate first, kill after grace, and
  the process handle is always released; stop/cleanup are idempotent.
- Logs are bounded and ordered under concurrent writers.
- Health and metrics corpora map to exact typed states and signals, and
  invalid documents are rejected rather than guessed.
"""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path

import httpx
import pytest

from morpheus.core.health import HealthState
from morpheus.engines.llamacpp import (
    KNOWN_GOOD_BUILDS,
    EngineCommandError,
    LlamaCppConfiguration,
    LlamaCppEngine,
    LogRing,
    parse_llamacpp_health,
    parse_llamacpp_metrics,
    parse_llamacpp_version,
)

pytestmark = pytest.mark.contract

KNOWN_GOOD = "build: 6139 (9ce9e0b) with version 3.1.2"


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


def build_engine(tmp_path: Path, **engine_overrides) -> tuple[LlamaCppEngine, dict[str, object]]:
    root = tmp_path / "root"
    root.mkdir(exist_ok=True)
    binary = tmp_path / "llama-server"
    binary.write_bytes(b"engine-binary")
    model = root / "model.gguf"
    model.unlink(missing_ok=True)
    model.write_bytes(b"model-artifact")
    probe = FakeProbe(engine_overrides.pop("probe_output", KNOWN_GOOD))
    port = FakePortProbe(engine_overrides.pop("port_free", True))
    runner = FakeRunner()
    configuration = LlamaCppConfiguration(model_path=model, port=9200)
    engine = LlamaCppEngine(
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
    model = Path("C:/models/m.gguf") if Path("C:/").exists() else Path("/models/m.gguf")
    configuration = LlamaCppConfiguration(
        model_path=model,
        port=9200,
        threads=8,
        context_window=8192,
        parallel_slots=4,
        gpu_layers=-1,
        seed=42,
        alias="dev-1",
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
        "9200",
        "--threads",
        "8",
        "--ctx-size",
        "8192",
        "--parallel",
        "4",
        "--n-gpu-layers",
        "-1",
        "--seed",
        "42",
        "--alias",
        "dev-1",
        "--json-schema",
        '{"type":"object"}',
    )
    assert all(isinstance(token, str) for token in first)
    assert configuration.render_digest() == hashlib.sha256("\0".join(first).encode()).hexdigest()


def test_any_single_field_change_alters_render_digest() -> None:
    model = Path("C:/models/m.gguf") if Path("C:/").exists() else Path("/models/m.gguf")
    base = LlamaCppConfiguration(model_path=model)
    baseline = base.render_digest()
    assert len(baseline) == 64
    assert baseline != LlamaCppConfiguration(model_path=model, port=1).render_digest()
    assert baseline != LlamaCppConfiguration(model_path=model, port=65535).render_digest()
    assert baseline != LlamaCppConfiguration(model_path=model, threads=128).render_digest()
    assert (
        baseline
        != LlamaCppConfiguration(model_path=model, context_window=1_048_576).render_digest()
    )
    assert baseline != LlamaCppConfiguration(model_path=model, parallel_slots=256).render_digest()
    assert baseline != LlamaCppConfiguration(model_path=model, gpu_layers=-1).render_digest()
    assert baseline != LlamaCppConfiguration(model_path=model, seed=7).render_digest()
    assert baseline != LlamaCppConfiguration(model_path=model, alias="a").render_digest()
    assert baseline != LlamaCppConfiguration(model_path=model, json_schema="{}").render_digest()
    assert baseline != LlamaCppConfiguration(model_path=model, host="127.0.0.2").render_digest()


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

    engine, handles = build_engine(tmp_path, probe_output="build: 3155 with version 2.5.1")
    violations = engine.preflight()
    assert any("evidence lane" in item for item in violations)

    engine, _ = build_engine(tmp_path, port_free=False)
    violations = engine.preflight()
    assert any("port" in item for item in violations)


def test_symlinked_binary_is_rejected_at_construction(tmp_path) -> None:
    root = tmp_path / "root"
    root.mkdir(exist_ok=True)
    target = tmp_path / "real-binary"
    target.write_bytes(b"engine")
    link = tmp_path / "llama-server"
    link.symlink_to(target)
    model = root / "model.gguf"
    model.write_bytes(b"model")
    with pytest.raises(EngineCommandError, match="regular file"):
        LlamaCppEngine(
            configuration=LlamaCppConfiguration(model_path=model),
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


def test_log_ring_is_bounded_and_thread_safe() -> None:
    ring = LogRing(8)
    writers = [
        threading.Thread(target=lambda: [ring.append(f"t{i}") for i in range(500)])
        for _ in range(4)
    ]
    for writer in writers:
        writer.start()
    for writer in writers:
        writer.join()
    snapshot = ring.snapshot()
    assert len(snapshot) == 8
    assert ring.snapshot(limit=3) == snapshot[-3:]
    assert all(isinstance(line, str) and line for line in snapshot)


def test_health_corpus_maps_exact_states() -> None:
    corpus = {
        '{"status": "ok", "slots_idle": 2}': HealthState.READY,
        '{"status": "loading model"}': HealthState.STARTING,
        '{"status": "no slot available"}': HealthState.STARTING,
        '{"status": "error"}': HealthState.DEGRADED,
    }
    for document, expected in corpus.items():
        assert parse_llamacpp_health(document) is expected
    for broken in ("", "[]", "42", '{"status": 4}', "not json"):
        with pytest.raises(ValueError, match="invalid"):
            parse_llamacpp_health(broken)


def test_metrics_corpus_and_empty_document() -> None:
    full = "\n".join(
        (
            "# TYPE llama:request_success_total counter",
            'llama:request_success_total{model="m"} 1',
            "# TYPE llama:requests_processing gauge",
            'llama:requests_processing{model="m"} 2',
            "# TYPE llama:kv_cache_usage_ratio gauge",
            'llama:kv_cache_usage_ratio{model="m"} 0.25',
        )
    )
    snapshot = parse_llamacpp_metrics(full)
    assert snapshot.values == {
        "request_success_total": 1.0,
        "requests_processing": 2.0,
        "kv_cache_usage_ratio": 0.25,
    }
    assert snapshot.available_signals == frozenset(
        {"request_success_total", "requests_processing", "kv_cache_usage_ratio"}
    )
    assert "prompt_tokens_total" in snapshot.missing_signals
    empty = parse_llamacpp_metrics("")
    assert empty.values == {}
    assert empty.missing_signals == frozenset(
        {
            "request_success_total",
            "request_failure_total",
            "requests_processing",
            "prompt_tokens_total",
            "generation_tokens_total",
            "kv_cache_usage_ratio",
        }
    )
    with pytest.raises(ValueError, match="invalid"):
        parse_llamacpp_metrics("# TYPE broken counter\nbroken not a metric value")


def test_capability_evidence_corpus() -> None:
    assert frozenset({6139, 5973, 5154}) == KNOWN_GOOD_BUILDS
    assert parse_llamacpp_version(KNOWN_GOOD).supported is True
    assert parse_llamacpp_version("build: 6139").version == "0.0.0"
    for output in ("", "llama-server: command not found", "build: abc"):
        with pytest.raises(ValueError, match="unrecognized"):
            parse_llamacpp_version(output)


async def test_http_surface_never_touches_live_endpoint_during_preflight(
    tmp_path,
) -> None:
    engine, handles = build_engine(tmp_path)
    assert engine.preflight() == ()
    assert handles["runner"].commands == []
    engine._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"status": "ok"}))
    )
    await engine.health()
    await engine._client.aclose()
    assert handles["runner"].commands == []
    assert handles["port"].calls == 1


async def test_health_http_contract_maps_ready_and_starting(tmp_path) -> None:
    engine, _ = build_engine(tmp_path)

    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"status": "ok"})

    engine._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    evidence = await engine.health()
    assert evidence.state is HealthState.READY
    assert evidence.reason_code == "llamacpp_ready"
    assert evidence.source == "llamacpp_health"
    await engine._client.aclose()
