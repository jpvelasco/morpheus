"""Unit tests: active-plan compat route composition (GATE-001)."""

from morpheus.core.records import (
    DeploymentPlan,
    EngineIdentity,
    ModelIdentity,
    WorkloadProfile,
)
from morpheus.gateway.managed import route_for_plan

DIGEST = "e" * 64


def test_route_for_plan_uses_first_port_and_served_aliases() -> None:
    plan = DeploymentPlan(
        plan_id="plan-compat-0001",
        model=ModelIdentity(
            model_id="model-compat",
            revision="v1.0.0",
            artifact_digest=DIGEST,
            model_format="gguf",
            quantization="q4_k_m",
            license_id="apache-2.0",
            source="huggingface",
        ),
        engine=EngineIdentity(
            engine_id="engine-compat",
            kind="llama.cpp",
            artifact_digest=DIGEST,
            platforms=("linux-x86_64",),
        ),
        workload=WorkloadProfile(
            workload_id="workload-compat",
            developer_profile="full-stack",
            context_tokens=8192,
            max_concurrency=1,
            required_features=("tool_use",),
        ),
        settings=(("context_length", 8192),),
        served_aliases=("compat-alias",),
        context_tokens=8192,
        max_concurrency=1,
        cache_policy="owned-cache",
        memory_estimate_bytes=1024,
        disk_estimate_bytes=1024,
        owned_paths=("/var/lib/morpheus/models/compat",),
        ports=(7413, 7414),
        health_contract_id="health-openai-compatible-0001",
        benchmark_gate_id="gate-ttft-latency-0001",
        rollback_target_plan_id=None,
        source_evidence_digest=DIGEST,
    )
    route = route_for_plan(plan)
    assert route.mode == "managed"
    assert route.managed_base_url == "http://127.0.0.1:7413"
    assert route.bypass_base_url is None
    assert route.aliases == (("compat-alias", "model-compat"),)
