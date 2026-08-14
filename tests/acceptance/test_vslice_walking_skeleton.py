from __future__ import annotations

from pathlib import Path

import pytest

from morpheus.core.records import (
    DeploymentPlan,
    EngineIdentity,
    MachineProfile,
    ModelIdentity,
    WorkloadProfile,
    decode_record,
    encode_record,
)
from morpheus.core.state_machines import decode_machine_record
from validation.vslice.fixtures import FakeVSliceEnvironment
from validation.vslice.harness import (
    ArtifactVerificationError,
    BenchmarkLimits,
    SliceOptions,
    VSliceError,
    fixture_catalog,
    render_command,
    run_slice,
    select_plan,
)

pytestmark = pytest.mark.acceptance

DIGEST_A = "1" * 64
DIGEST_B = "2" * 64
PLAN_A = "plan-vslice-libri-q4-a"
PLAN_B = "plan-vslice-libri-q4-b"


def _machine() -> MachineProfile:
    return MachineProfile(
        machine_id="machine-vslice-0001",
        platform="linux",
        architecture="x86_64",
        accelerator="cpu",
        memory_bytes=4 * 1024**3,
        disk_bytes=16 * 1024**3,
    )


def _workload() -> WorkloadProfile:
    return WorkloadProfile(
        workload_id="workload-vslice-0001",
        developer_profile="full-stack",
        context_tokens=2_048,
        max_concurrency=1,
        required_features=("chat",),
    )


def _model() -> ModelIdentity:
    return ModelIdentity(
        model_id="model-smollm2-135m-instruct",
        revision="f0a2b81",
        artifact_digest=DIGEST_A,
        model_format="gguf",
        quantization="q4_k_m",
        license_id="apache-2.0",
        source="huggingface",
    )


def _engine() -> EngineIdentity:
    return EngineIdentity(
        engine_id="engine-llama-cpp-vslice",
        kind="llama.cpp",
        artifact_digest=DIGEST_B,
        platforms=("linux-x86_64",),
    )


def _plans() -> tuple[DeploymentPlan, DeploymentPlan]:
    base = {
        "model": _model(),
        "engine": _engine(),
        "workload": _workload(),
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
        "source_evidence_digest": DIGEST_B,
    }
    return (
        DeploymentPlan(plan_id=PLAN_A, settings=(("context_length", 2048), ("threads", 2)), **base),
        DeploymentPlan(plan_id=PLAN_B, settings=(("context_length", 1024), ("threads", 2)), **base),
    )


def _options(cache: Path) -> SliceOptions:
    plan_a, plan_b = _plans()
    return SliceOptions(
        machine=_machine(),
        workload=_workload(),
        catalog=(plan_a, plan_b),
        plan_a_id=PLAN_A,
        plan_b_id=PLAN_B,
        cache_root=cache,
        startup_timeout_s=5.0,
        benchmark_limits=BenchmarkLimits(max_seconds=30, max_tokens_per_second=1_000),
    )


def test_vslice_001_chain_retains_one_exact_correlated_identity(tmp_path: Path) -> None:
    environment = FakeVSliceEnvironment()
    options = _options(tmp_path)

    report = run_slice(environment, options)

    assert report.plan_a.plan_id == PLAN_A
    assert report.plan_b.plan_id == PLAN_B
    assert report.recommendation.machine_id == _machine().machine_id
    assert report.recommendation.plan_ids == (PLAN_A, PLAN_B)
    assert report.acquisition.record.record_id == PLAN_A
    assert report.acquisition.record.state == "staged"
    assert report.campaign_a.record.record_id == f"campaign-{PLAN_A}"
    assert report.campaign_a.record.state == "succeeded"
    assert report.promotion_a.record.record_id == PLAN_A
    assert report.promotion_a.record.state == "active"
    assert report.promotion_b.record.record_id == PLAN_B
    assert report.promotion_b.record.state == "active"
    assert report.rollback.record.record_id == PLAN_A
    assert report.rollback.record.state == "completed"
    assert report.measurements is not None
    assert report.measurements.ttft_s > 0.0
    assert report.measurements.tokens_per_second > 0.0
    assert report.health_after_rollback is True
    assert report.external_after == report.external_before


def test_vslice_002_digest_mismatch_fails_acquisition_without_starting(tmp_path: Path) -> None:
    environment = FakeVSliceEnvironment(artifact_digest_override="f" * 64)
    options = _options(tmp_path)

    with pytest.raises(ArtifactVerificationError):
        run_slice(environment, options)

    assert environment.started == 0
    assert environment.downloaded == 1
    checkpoint = tmp_path / "checkpoints" / "acquisition.plan-vslice-libri-q4-a.json"
    assert checkpoint.exists()
    assert decode_machine_record(checkpoint.read_bytes()).state == "acquiring"


def test_vslice_003_interrupted_acquisition_resumes_without_duplicating(tmp_path: Path) -> None:
    environment = FakeVSliceEnvironment(fail_download_after_bytes=1_000)
    options = _options(tmp_path)

    with pytest.raises(VSliceError):
        run_slice(environment, options)
    first_downloads = environment.downloaded

    report = run_slice(environment, options)

    assert report.acquisition.record.state == "staged"
    assert environment.downloaded == first_downloads + 2


def test_vslice_004_low_disk_blocks_acquisition(tmp_path: Path) -> None:
    environment = FakeVSliceEnvironment(disk_free_bytes_value=64 * 1024**2)
    options = _options(tmp_path)

    with pytest.raises(VSliceError, match="disk"):
        run_slice(environment, options)

    assert environment.started == 0


def test_vslice_005_unknown_engine_setting_is_rejected_before_start(tmp_path: Path) -> None:
    plan_a, _ = _plans()
    with pytest.raises(ValueError, match="setting"):
        plan_a = DeploymentPlan(
            plan_id=PLAN_A,
            model=plan_a.model,
            engine=plan_a.engine,
            workload=plan_a.workload,
            settings=(("context_length", 2048), ("--weight-only", "true")),
            served_aliases=plan_a.served_aliases,
            context_tokens=plan_a.context_tokens,
            max_concurrency=plan_a.max_concurrency,
            cache_policy=plan_a.cache_policy,
            memory_estimate_bytes=plan_a.memory_estimate_bytes,
            disk_estimate_bytes=plan_a.disk_estimate_bytes,
            owned_paths=plan_a.owned_paths,
            ports=plan_a.ports,
            health_contract_id=plan_a.health_contract_id,
            benchmark_gate_id=plan_a.benchmark_gate_id,
            rollback_target_plan_id=plan_a.rollback_target_plan_id,
            source_evidence_digest=plan_a.source_evidence_digest,
        )
        render_command(plan_a)


def test_vslice_006_startup_timeout_aborts_campaign_and_cleans_up(tmp_path: Path) -> None:
    environment = FakeVSliceEnvironment(startup_healthy=False, startup_slow=True)
    options = _options(tmp_path)

    report = run_slice(environment, options)

    assert report.campaign_a.record.state == "aborted"
    assert report.promotion_a.record.state == "rejected"
    assert environment.stopped == environment.started


def test_vslice_007_failed_health_rolls_back_to_known_good_a(tmp_path: Path) -> None:
    environment = FakeVSliceEnvironment(fail_health_on_b=True)
    options = _options(tmp_path)

    report = run_slice(environment, options)

    assert report.promotion_b.record.state == "rolled_back"
    assert report.rollback.record.state == "completed"
    assert report.plan_after_rollback.plan_id == PLAN_A
    assert report.health_after_rollback is True


def test_vslice_008_benchmark_aborts_when_limits_are_breached(tmp_path: Path) -> None:
    environment = FakeVSliceEnvironment(slow_decode=True)
    options = _options(tmp_path)
    options = SliceOptions(
        machine=options.machine,
        workload=options.workload,
        catalog=options.catalog,
        plan_a_id=options.plan_a_id,
        plan_b_id=options.plan_b_id,
        cache_root=options.cache_root,
        startup_timeout_s=options.startup_timeout_s,
        benchmark_limits=BenchmarkLimits(max_seconds=1, max_tokens_per_second=1),
    )

    report = run_slice(environment, options)

    assert report.campaign_a.record.state == "aborted"
    assert report.promotion_a.record.state == "rejected"


def test_vslice_009_rollback_failure_leaves_a_failed_record(tmp_path: Path) -> None:
    environment = FakeVSliceEnvironment(fail_restore=True)
    options = _options(tmp_path)

    report = run_slice(environment, options)

    assert report.rollback.record.state == "failed"
    assert report.promotion_b.record.state == "active"


def test_vslice_010_repeated_commands_are_idempotent(tmp_path: Path) -> None:
    environment = FakeVSliceEnvironment()
    options = _options(tmp_path)

    first = run_slice(environment, options)
    second = run_slice(environment, options)

    assert first.acquisition.record.state == "staged"
    assert second.acquisition.record.state == "staged"
    assert second.promotion_a.record.state == "active"
    assert environment.downloaded == 2


def test_vslice_011_process_tree_cleanup_leaves_no_orphans(tmp_path: Path) -> None:
    environment = FakeVSliceEnvironment(spawn_extra_processes=2)
    options = _options(tmp_path)

    report = run_slice(environment, options)

    assert report.cleanup_orphans == ()
    assert environment.owned_processes() == ()


def test_vslice_012_restart_resumes_without_skipping_confirmation(tmp_path: Path) -> None:
    environment = FakeVSliceEnvironment()
    options = _options(tmp_path)
    run_slice(environment, options)

    resume = run_slice(environment, options)

    assert resume.promotion_b.record.state == "active"
    assert environment.downloaded == 2


def test_vslice_013_selection_is_deterministic_and_filters_incompatible_engines(
    tmp_path: Path,
) -> None:
    plan_a, plan_b = _plans()
    incompatible = DeploymentPlan(
        plan_id="plan-vslice-rocm",
        model=plan_a.model,
        engine=EngineIdentity(
            engine_id="engine-vllm-vslice",
            kind="vllm",
            artifact_digest=DIGEST_B,
            platforms=("linux-x86_64",),
        ),
        workload=plan_a.workload,
        settings=(("context_length", 2048),),
        served_aliases=("rocm-1",),
        context_tokens=2_048,
        max_concurrency=1,
        cache_policy="owned-cache",
        memory_estimate_bytes=512 * 1024**2,
        disk_estimate_bytes=256 * 1024**2,
        owned_paths=("/opt/morpheus/vslice/cache",),
        ports=(8080,),
        health_contract_id="health-openai-compatible-0001",
        benchmark_gate_id="gate-ttft-0001",
        rollback_target_plan_id=None,
        source_evidence_digest=DIGEST_B,
    )

    first = select_plan(_machine(), _workload(), (plan_a, plan_b, incompatible))
    second = select_plan(_machine(), _workload(), (plan_a, plan_b, incompatible))

    assert first.plan_ids == (PLAN_A, PLAN_B)
    assert second.plan_ids == (PLAN_A, PLAN_B)


def test_vslice_014_fixture_catalog_records_round_trip_through_the_codec(tmp_path: Path) -> None:
    for record in fixture_catalog():
        restored = decode_record(encode_record(record))

        assert restored == record
        assert restored.record_id == record.record_id
