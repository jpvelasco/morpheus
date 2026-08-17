from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from morpheus.core.records import (
    CURRENT_SCHEMA_VERSION,
    BenchmarkCampaign,
    BenchmarkComparison,
    DeploymentPlan,
    DiagnosisRecord,
    EngineIdentity,
    MachineProfile,
    ModelIdentity,
    Recommendation,
    RecordEnvelope,
    SchemaVersionError,
    UnknownRecordTypeError,
    WorkloadProfile,
    decode_record,
    encode_record,
)

DIGEST = "b" * 64
PLAN_ID = "plan-libri-gguf-q4-0001"
MODEL_ID = "model-libri-coder-gguf"
ENGINE_ID = "engine-llama-cpp-0001"


def _model() -> ModelIdentity:
    return ModelIdentity(
        model_id=MODEL_ID,
        revision="v1.0.0",
        artifact_digest=DIGEST,
        model_format="gguf",
        quantization="q4_k_m",
        license_id="apache-2.0",
        source="huggingface",
    )


def _engine() -> EngineIdentity:
    return EngineIdentity(
        engine_id=ENGINE_ID,
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


def _machine() -> MachineProfile:
    return MachineProfile(
        machine_id="machine-ubuntu-1-0001",
        platform="linux",
        architecture="x86_64",
        accelerator="nvidia",
        memory_bytes=64 * 1024**3,
        disk_bytes=2 * 1024**4,
    )


def _plan() -> DeploymentPlan:
    return DeploymentPlan(
        plan_id=PLAN_ID,
        model=_model(),
        engine=_engine(),
        workload=_workload(),
        settings=(
            ("context_length", 32768),
            ("threads", 8),
        ),
        served_aliases=("libri-1", "coder"),
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


def _campaign() -> BenchmarkCampaign:
    return BenchmarkCampaign(
        campaign_id="campaign-bench-0001",
        plan_id=PLAN_ID,
        benchmark_suite_id="suite-developer-0001",
        workload_id="workload-developer-0001",
        state="planned",
    )


def _diagnosis() -> DiagnosisRecord:
    return DiagnosisRecord(
        diagnosis_id="diagnosis-0001",
        plan_id=PLAN_ID,
        evidence_package_digest=DIGEST,
        observations=("high-latency",),
        hypotheses=("context-exhaustion",),
        confidence=0.6,
        citations=("benchmark-campaign-0001",),
        proposed_checks=("check-ctx-usage",),
    )


def _recommendation() -> Recommendation:
    return Recommendation(
        recommendation_id="recommendation-0001",
        machine_id="machine-ubuntu-1-0001",
        plan_ids=(PLAN_ID,),
        evidence_ranked=True,
        weights=(("speed", 0.5), ("quality", 0.5)),
    )


def _comparison() -> BenchmarkComparison:
    return BenchmarkComparison(
        comparison_id="comparison-0001",
        plan_ids=(PLAN_ID, "plan-libri-gguf-q4-0002"),
        campaign_ids=("campaign-bench-0001", "campaign-bench-0002"),
        comparability="comparable",
        verdict="libri-gguf-q4-0001",
        source_evidence_digest=DIGEST,
    )


def test_RUNM_001_planning_records_are_immutable() -> None:
    plan = _plan()

    with pytest.raises(FrozenInstanceError):
        plan.owned_paths = ("/mnt/escape",)  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        plan.settings = ()  # type: ignore[misc]


def test_RUNM_001_changing_any_plan_input_requires_a_new_plan_identity() -> None:
    original = _plan()
    derived = DeploymentPlan(
        plan_id="plan-libri-gguf-q4-0002",
        model=original.model,
        engine=original.engine,
        workload=original.workload,
        settings=(("context_length", 16_384), ("threads", 8)),
        served_aliases=original.served_aliases,
        context_tokens=16_384,
        max_concurrency=original.max_concurrency,
        cache_policy=original.cache_policy,
        memory_estimate_bytes=original.memory_estimate_bytes,
        disk_estimate_bytes=original.disk_estimate_bytes,
        owned_paths=original.owned_paths,
        ports=original.ports,
        health_contract_id=original.health_contract_id,
        benchmark_gate_id=original.benchmark_gate_id,
        rollback_target_plan_id=original.plan_id,
        source_evidence_digest=original.source_evidence_digest,
    )

    assert derived.plan_id != original.plan_id
    assert derived.rollback_target_plan_id == original.plan_id


@pytest.mark.parametrize(
    ("model_id", "revision", "digest", "quantization"),
    [
        ("", "v1.0.0", DIGEST, "q4_k_m"),
        ("model id", "v1.0.0", DIGEST, "q4_k_m"),
        (MODEL_ID, "", DIGEST, "q4_k_m"),
        (MODEL_ID, "v1.0.0", "not-a-digest", "q4_k_m"),
        (MODEL_ID, "v1.0.0", DIGEST, "shell;flag"),
    ],
)
def test_RUNM_001_model_identity_rejects_unbounded_or_unsafe_fields(
    model_id: str, revision: str, digest: str, quantization: str
) -> None:
    with pytest.raises(ValueError):
        ModelIdentity(
            model_id=model_id,
            revision=revision,
            artifact_digest=digest,
            model_format="gguf",
            quantization=quantization,
            license_id="apache-2.0",
            source="huggingface",
        )


def test_RUNM_001_plan_settings_accept_only_typed_scalar_pairs() -> None:
    plan = DeploymentPlan(
        plan_id=PLAN_ID,
        model=_model(),
        engine=_engine(),
        workload=_workload(),
        settings=(("context_length", 32768), ("gpu_offload", True), ("speed", 0.9)),
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

    assert plan.settings[0][1] == 32768


@pytest.mark.parametrize(
    "setting",
    [
        ("", 8),
        ("context_length", "/bin/sh -c 'evil'"),
        ("x" * 70, 1),
        ("extra", ";true"),
        ("flag", "--weight-only"),
        ("flag", "with space"),
    ],
)
def test_RUNM_001_plan_settings_reject_unbounded_keys_and_values(
    setting: tuple[str, object],
) -> None:
    with pytest.raises(ValueError):
        DeploymentPlan(
            plan_id=PLAN_ID,
            model=_model(),
            engine=_engine(),
            workload=_workload(),
            settings=(setting,),
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


def test_RUNM_001_plan_settings_reject_duplicate_keys() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        DeploymentPlan(
            plan_id=PLAN_ID,
            model=_model(),
            engine=_engine(),
            workload=_workload(),
            settings=(("threads", 4), ("threads", 8)),
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


def test_RUNM_001_campaign_correlates_one_exact_plan() -> None:
    campaign = _campaign()

    assert campaign.plan_id == PLAN_ID
    assert campaign.state == "planned"


def test_RUNM_001_versioned_envelope_round_trips_canonically() -> None:
    records = (
        _machine(),
        _model(),
        _engine(),
        _workload(),
        _plan(),
        _campaign(),
        _comparison(),
        _diagnosis(),
        _recommendation(),
    )

    for record in records:
        envelope = encode_record(record)
        assert isinstance(envelope, bytes)
        assert RecordEnvelope.decode(envelope).record_id == record.record_id
        assert decode_record(envelope) == record


def test_RUNM_001_codec_rejects_unknown_record_types_and_future_schema_versions() -> None:
    plan = _plan()
    envelope = RecordEnvelope.from_record(plan)

    with pytest.raises(UnknownRecordTypeError):
        RecordEnvelope.decode(
            envelope.encode().replace(b'"deployment_plan"', b'"adversarial_plan"')
        )
    with pytest.raises(SchemaVersionError):
        RecordEnvelope.decode(
            envelope.encode().replace(
                f'"schema_version":{CURRENT_SCHEMA_VERSION}'.encode(),
                f'"schema_version":{CURRENT_SCHEMA_VERSION + 1}'.encode(),
            )
        )


def test_RUNM_001_codec_rejects_missing_and_extra_payload_fields() -> None:
    plan = _plan()
    envelope = RecordEnvelope.from_record(plan)

    missing = envelope.encode().replace(b'"context_tokens":32768,', b"")
    with pytest.raises(ValueError):
        RecordEnvelope.decode(missing)

    extra = envelope.encode().replace(b'"ports":[8080]', b'"ports":[8080],"backdoor":"true"')
    with pytest.raises(ValueError):
        RecordEnvelope.decode(extra)


def test_RUNM_001_codec_deterministic_across_input_key_order() -> None:
    plan = _plan()

    first = encode_record(plan)
    payload = plan.public_dict()
    reordered = {key: payload[key] for key in sorted(payload.keys(), reverse=True)}
    reserialized = RecordEnvelope(
        record_type="deployment_plan",
        schema_version=CURRENT_SCHEMA_VERSION,
        record_id=plan.record_id,
        payload=reordered,
    )

    assert reserialized.encode() == first
