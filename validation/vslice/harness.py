from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from morpheus.adapters.persistence.records_store import RecordsStore
from morpheus.core.deployment import DeploymentStore
from morpheus.core.records import (
    DeploymentPlan,
    MachineProfile,
    Recommendation,
    WorkloadProfile,
)
from morpheus.core.state_machines import (
    MachineKind,
    MachineRecord,
    StateMachine,
    decode_machine_record,
    encode_machine_record,
)
from morpheus.ops.planning import PlanningService

ACQUISITION_SOURCE = "https://github.com/ggml-org/llama.cpp/releases/download/b10400/llama-b10400-bin-ubuntu-x64.tar.gz"
MODEL_SOURCE = "https://huggingface.co/bartowski/SmolLM2-135M-Instruct-GGUF/resolve/f0a2b81d63eb57be0e90e82e327e03a7fc66a7dc/SmolLM2-135M-Instruct-Q4_K_M.gguf"

_SETTING_ALLOWLIST = frozenset({"context_length", "threads", "batch_size"})
_ENGINE_FLAGS = {
    "context_length": "--ctx-size",
    "threads": "--threads",
    "batch_size": "--batch-size",
}


class ArtifactVerificationError(ValueError):
    pass


class VSliceError(RuntimeError):
    pass


class VSliceEnvironment(Protocol):
    """Typed port for everything outside the walking-skeleton domain logic."""

    def artifact_digest(self, path: Path) -> str: ...

    def download_artifact(self, source: str, digest: str, destination: Path) -> None: ...

    def disk_free_bytes(self, root: Path) -> int: ...

    def start_server(
        self, plan: DeploymentPlan, workdir: Path, ready_url: str, timeout_s: float
    ) -> object: ...

    def stop_server(self, handle: object) -> None: ...

    def http_health(self, handle: object) -> bool: ...

    def chat_completion(
        self, handle: object, prompt: str, max_tokens: int
    ) -> tuple[str, float]: ...

    def list_owned_processes(self, marker: str) -> tuple[str, ...]: ...

    def snapshot_external(self) -> str: ...


@dataclass(frozen=True, slots=True)
class BenchmarkLimits:
    max_seconds: float = 30.0
    max_tokens_per_second: float = 1_000.0


@dataclass(frozen=True, slots=True)
class SliceOptions:
    machine: MachineProfile
    workload: WorkloadProfile
    catalog: tuple[DeploymentPlan, ...]
    plan_a_id: str
    plan_b_id: str
    cache_root: Path
    prompt: str = "Explain TCP in one sentence."
    max_tokens: int = 24
    startup_timeout_s: float = 30.0
    benchmark_limits: BenchmarkLimits = BenchmarkLimits()


@dataclass(frozen=True, slots=True)
class Measurement:
    ttft_s: float
    tokens_per_second: float


@dataclass(frozen=True, slots=True)
class MachineRun:
    machine: MachineKind
    record: MachineRecord


@dataclass(frozen=True, slots=True)
class VSliceReport:
    recommendation: Recommendation
    plan_a: DeploymentPlan
    plan_b: DeploymentPlan
    acquisition: MachineRun
    campaign_a: MachineRun
    campaign_b: MachineRun
    promotion_a: MachineRun
    promotion_b: MachineRun
    rollback: MachineRun
    plan_after_rollback: DeploymentPlan
    health_after_rollback: bool
    measurements: Measurement | None
    external_before: str
    external_after: str
    cleanup_orphans: tuple[str, ...]
    checkpoints: tuple[Path, ...]


def _initial(machine: MachineKind, record_id: str) -> MachineRun:
    initial = {
        MachineKind.ACQUISITION: "planned",
        MachineKind.CAMPAIGN: "planned",
        MachineKind.PROMOTION: "proposed",
        MachineKind.ROLLBACK: "requested",
    }[machine]
    return MachineRun(
        machine=machine,
        record=MachineRecord(machine=machine, record_id=record_id, state=initial),
    )


def _checkpoint_path(cache_root: Path, machine: MachineKind, record_id: str) -> Path:
    return cache_root / "checkpoints" / f"{machine.value}.{record_id}.json"


def _load_checkpoint(path: Path) -> MachineRecord | None:
    if not path.exists():
        return None
    return decode_machine_record(path.read_bytes())


def _store_checkpoint(path: Path, record: MachineRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode_machine_record(record))


def _machine_edges(
    cache_root: Path,
    run: MachineRun,
    record_id: str,
    chain: tuple[str, ...],
) -> MachineRun:
    """Advance one machine through its confirmed edge list, checkpointing durably."""
    checkpoint = _checkpoint_path(cache_root, run.machine, record_id)
    recorded = _load_checkpoint(checkpoint)
    if recorded is not None:
        run = MachineRun(run.machine, recorded)
        if run.record.terminal:
            return run
    for target in chain:
        if run.record.state == target:
            continue
        result = StateMachine.transition(run.record, target)
        if not result.accepted:
            raise VSliceError(f"{run.machine.value} cannot reach {target}: {result.audit}")
        _store_checkpoint(checkpoint, result.record)
        run = MachineRun(run.machine, result.record)
    return run


def select_plan(
    machine: MachineProfile,
    workload: WorkloadProfile,
    catalog: tuple[DeploymentPlan, ...],
    *,
    records_root: Path,
) -> Recommendation:
    """Select through the production planning service (RUNM-001 parity).

    The fixture must exercise the same public application service and canonical
    records as the API: selection persists the machine profile, workload,
    plans, and the timestamp-free canonical recommendation under ``records_root``.
    """
    service = PlanningService(
        records=RecordsStore(records_root / "records"),
        plans=DeploymentStore(records_root),
    )
    return service.select_plan(machine=machine, workload=workload, catalog=catalog)


def render_command(plan: DeploymentPlan) -> tuple[str, ...]:
    """Render bounded llama-server arguments; reject anything outside the allowlist."""
    command = [
        "llama-server",
        "--model",
        "/opt/morpheus-cache/model.gguf",
        "--host",
        "127.0.0.1",
        "--port",
        "8080",
        "--alias",
        plan.served_aliases[0],
    ]
    for key, value in plan.settings:
        if key not in _SETTING_ALLOWLIST:
            raise ValueError(f"setting {key!r} is not an allowed engine setting")
        if isinstance(value, bool):
            if value:
                command.append(_ENGINE_FLAGS[key])
        else:
            command.extend([_ENGINE_FLAGS[key], str(value)])
    return tuple(command)


def _acquire(
    environment: VSliceEnvironment,
    plan: DeploymentPlan,
    cache_root: Path,
) -> MachineRun:
    """Verified, resumable acquisition that never duplicates completed work."""
    run = _initial(MachineKind.ACQUISITION, plan.plan_id)
    if environment.disk_free_bytes(cache_root) < plan.disk_estimate_bytes:
        raise VSliceError("not enough free disk for the deployment plan")
    run = _machine_edges(cache_root, run, plan.plan_id, ("acquiring",))
    if run.record.state == "acquiring":
        model_path = cache_root / "cache" / "model.gguf"
        engine_path = cache_root / "cache" / "engine.tar.gz"
        if not model_path.exists():
            environment.download_artifact(MODEL_SOURCE, plan.model.artifact_digest, model_path)
            if environment.artifact_digest(model_path) != plan.model.artifact_digest:
                raise ArtifactVerificationError("model artifact digest mismatch")
        if not engine_path.exists():
            environment.download_artifact(
                ACQUISITION_SOURCE, plan.engine.artifact_digest, engine_path
            )
            if environment.artifact_digest(engine_path) != plan.engine.artifact_digest:
                raise ArtifactVerificationError("engine artifact digest mismatch")
        run = _machine_edges(cache_root, run, plan.plan_id, ("verified", "staged"))
    return run


def _campaign(
    environment: VSliceEnvironment,
    plan: DeploymentPlan,
    cache_root: Path,
    prompt: str,
    max_tokens: int,
    limits: BenchmarkLimits,
    server: object,
) -> tuple[MachineRun, Measurement | None]:
    campaign_id = f"campaign-{plan.plan_id}"
    run = _initial(MachineKind.CAMPAIGN, campaign_id)
    run = _machine_edges(cache_root, run, campaign_id, ("authorized", "running"))
    measurement: Measurement | None = None
    if run.record.state == "running":
        started = time.monotonic()
        text, elapsed = environment.chat_completion(server, prompt, max_tokens)
        duration = time.monotonic() - started
        tokens = max(len(text.split()), 1)
        tokens_per_second = tokens / elapsed if elapsed > 0 else 0.0
        measurement = Measurement(ttft_s=duration, tokens_per_second=tokens_per_second)
        if tokens_per_second >= limits.max_tokens_per_second or duration > limits.max_seconds:
            run = _machine_edges(cache_root, run, campaign_id, ("aborted",))
        else:
            run = _machine_edges(cache_root, run, campaign_id, ("succeeded",))
    return run, measurement


def _promote(
    environment: VSliceEnvironment,
    plan: DeploymentPlan,
    cache_root: Path,
    server: object,
    has_benchmark_evidence: bool,
) -> MachineRun:
    run = _initial(MachineKind.PROMOTION, plan.plan_id)
    if not has_benchmark_evidence:
        raise VSliceError("promotion requires campaign evidence")
    chain = ("preflighted", "confirmed", "activating")
    run = _machine_edges(cache_root, run, plan.plan_id, chain)
    if run.record.state == "activating":
        if environment.http_health(server):
            run = _machine_edges(cache_root, run, plan.plan_id, ("active",))
        else:
            run = _machine_edges(cache_root, run, plan.plan_id, ("recovering", "rolled_back"))
    return run


def _rollback(
    environment: VSliceEnvironment,
    plan: DeploymentPlan,
    cache_root: Path,
    server: object,
) -> tuple[MachineRun, bool]:
    run = _initial(MachineKind.ROLLBACK, plan.plan_id)
    run = _machine_edges(cache_root, run, plan.plan_id, ("preflighted", "restoring"))
    if run.record.state == "restoring":
        if environment.http_health(server):
            run = _machine_edges(cache_root, run, plan.plan_id, ("verified", "completed"))
        else:
            run = _machine_edges(cache_root, run, plan.plan_id, ("failed",))
    return run, run.record.state == "completed" and environment.http_health(server)


def _finalize_report(
    environment: VSliceEnvironment,
    options: SliceOptions,
    recommendation: Recommendation,
    plan_a: DeploymentPlan,
    plan_b: DeploymentPlan,
    acquisition: MachineRun,
    campaign_a: MachineRun,
    campaign_b: MachineRun,
    promotion_a: MachineRun,
    promotion_b: MachineRun,
    rollback: MachineRun,
    plan_after_rollback: DeploymentPlan,
    health_after_rollback: bool,
    measurements: Measurement | None,
    external_before: str,
) -> VSliceReport:
    orphans = environment.list_owned_processes("morpheus-vslice")
    for orphan in orphans:
        environment.stop_server(orphan)
    return VSliceReport(
        recommendation=recommendation,
        plan_a=plan_a,
        plan_b=plan_b,
        acquisition=acquisition,
        campaign_a=campaign_a,
        campaign_b=campaign_b,
        promotion_a=promotion_a,
        promotion_b=promotion_b,
        rollback=rollback,
        plan_after_rollback=plan_after_rollback,
        health_after_rollback=health_after_rollback,
        measurements=measurements,
        external_before=external_before,
        external_after=environment.snapshot_external(),
        cleanup_orphans=orphans,
        checkpoints=tuple(sorted((options.cache_root / "checkpoints").glob("*.json"))),
    )


def run_slice(environment: VSliceEnvironment, options: SliceOptions) -> VSliceReport:
    """One full walking skeleton: discovery to rollback with cleanup."""
    (options.cache_root / "checkpoints").mkdir(parents=True, exist_ok=True)
    external_before = environment.snapshot_external()

    recommendation = select_plan(
        options.machine,
        options.workload,
        options.catalog,
        records_root=options.cache_root,
    )
    plan_a = next(plan for plan in options.catalog if plan.plan_id == options.plan_a_id)
    plan_b = next(plan for plan in options.catalog if plan.plan_id == options.plan_b_id)

    render_command(plan_a)
    render_command(plan_b)

    acquisition_a = _acquire(environment, plan_a, options.cache_root)
    try:
        server_a = environment.start_server(
            plan_a,
            options.cache_root,
            "http://127.0.0.1:8080/health",
            options.startup_timeout_s,
        )
    except VSliceError:
        aborted = _machine_edges(
            options.cache_root,
            _initial(MachineKind.CAMPAIGN, f"campaign-{plan_a.plan_id}"),
            f"campaign-{plan_a.plan_id}",
            ("authorized", "running", "aborted"),
        )
        rejected = _machine_edges(
            options.cache_root,
            _initial(MachineKind.PROMOTION, plan_a.plan_id),
            plan_a.plan_id,
            ("rejected",),
        )
        return _finalize_report(
            environment,
            options,
            recommendation,
            plan_a,
            plan_b,
            acquisition_a,
            aborted,
            _initial(MachineKind.CAMPAIGN, f"campaign-{plan_b.plan_id}"),
            rejected,
            _initial(MachineKind.PROMOTION, plan_b.plan_id),
            _initial(MachineKind.ROLLBACK, plan_a.plan_id),
            plan_a,
            False,
            None,
            external_before,
        )
    campaign_a, measurement_a = _campaign(
        environment,
        plan_a,
        options.cache_root,
        options.prompt,
        options.max_tokens,
        options.benchmark_limits,
        server_a,
    )
    if campaign_a.record.state == "succeeded":
        promotion_a = _promote(environment, plan_a, options.cache_root, server_a, True)
    else:
        promotion_a = _machine_edges(
            options.cache_root,
            _initial(MachineKind.PROMOTION, plan_a.plan_id),
            plan_a.plan_id,
            ("rejected",),
        )
    environment.stop_server(server_a)

    if campaign_a.record.state != "succeeded" or promotion_a.record.state != "active":
        return _finalize_report(
            environment,
            options,
            recommendation,
            plan_a,
            plan_b,
            acquisition_a,
            campaign_a,
            _initial(MachineKind.CAMPAIGN, f"campaign-{plan_b.plan_id}"),
            promotion_a,
            _initial(MachineKind.PROMOTION, plan_b.plan_id),
            _initial(MachineKind.ROLLBACK, plan_a.plan_id),
            plan_a,
            False,
            measurement_a,
            external_before,
        )

    _acquire(environment, plan_b, options.cache_root)
    server_b = environment.start_server(
        plan_b,
        options.cache_root,
        "http://127.0.0.1:8080/health",
        options.startup_timeout_s,
    )
    campaign_b, _ = _campaign(
        environment,
        plan_b,
        options.cache_root,
        options.prompt,
        options.max_tokens,
        options.benchmark_limits,
        server_b,
    )
    if campaign_b.record.state == "succeeded":
        promotion_b = _promote(environment, plan_b, options.cache_root, server_b, True)
    else:
        promotion_b = _machine_edges(
            options.cache_root,
            _initial(MachineKind.PROMOTION, plan_b.plan_id),
            plan_b.plan_id,
            ("rejected",),
        )
    environment.stop_server(server_b)

    if promotion_b.record.state not in {"active", "rolled_back"}:
        return _finalize_report(
            environment,
            options,
            recommendation,
            plan_a,
            plan_b,
            acquisition_a,
            campaign_a,
            campaign_b,
            promotion_a,
            promotion_b,
            _initial(MachineKind.ROLLBACK, plan_a.plan_id),
            plan_a,
            False,
            measurement_a,
            external_before,
        )

    server_a = environment.start_server(
        plan_a,
        options.cache_root,
        "http://127.0.0.1:8080/health",
        options.startup_timeout_s,
    )
    try:
        rollback, health_after_rollback = _rollback(
            environment, plan_a, options.cache_root, server_a
        )
    finally:
        environment.stop_server(server_a)

    return _finalize_report(
        environment,
        options,
        recommendation,
        plan_a,
        plan_b,
        acquisition_a,
        campaign_a,
        campaign_b,
        promotion_a,
        promotion_b,
        rollback,
        plan_a,
        health_after_rollback,
        measurement_a,
        external_before,
    )


def fixture_catalog() -> tuple[DeploymentPlan, ...]:
    """The deterministic offline catalog used by the acceptance lane."""
    from morpheus.core.records import EngineIdentity, ModelIdentity

    model = ModelIdentity(
        model_id="model-smollm2-135m-instruct",
        revision="f0a2b81",
        artifact_digest="1" * 64,
        model_format="gguf",
        quantization="q4_k_m",
        license_id="apache-2.0",
        source="huggingface",
    )
    engine = EngineIdentity(
        engine_id="engine-llama-cpp-vslice",
        kind="llama.cpp",
        artifact_digest="2" * 64,
        platforms=("linux-x86_64",),
    )
    workload = WorkloadProfile(
        workload_id="workload-vslice-0001",
        developer_profile="full-stack",
        context_tokens=2_048,
        max_concurrency=1,
        required_features=("chat",),
    )
    base = {
        "model": model,
        "engine": engine,
        "workload": workload,
        "served_aliases": ("libri-1",),
        "context_tokens": 2_048,
        "max_concurrency": 1,
        "cache_policy": "owned-cache",
        "memory_estimate_bytes": 512 * 1024**2,
        "disk_estimate_bytes": 256 * 1024**2,
        "owned_paths": ("/opt/morpheus/vslice/cache",),
        "ports": (8080,),
        "health_contract_id": "health-openai-compatible-0001",
        "benchmark_gate_id": "gate-ttft-0001",
        "rollback_target_plan_id": None,
        "source_evidence_digest": "2" * 64,
    }
    return (
        DeploymentPlan(
            plan_id="plan-vslice-libri-q4-a",
            settings=(("context_length", 2048), ("threads", 2)),
            **base,
        ),
        DeploymentPlan(
            plan_id="plan-vslice-libri-q4-b",
            settings=(("context_length", 1024), ("threads", 2)),
            **base,
        ),
    )
