# ruff: noqa: T201  # CLI driver reports its slice results to stdout by design
from __future__ import annotations

import json
import sys
import tarfile
from pathlib import Path

from morpheus.core.records import (
    DeploymentPlan,
    EngineIdentity,
    MachineProfile,
    ModelIdentity,
    WorkloadProfile,
)
from validation.vslice.docker_environment import (
    ENGINE_SOURCE,
    MODEL_DIGEST,
    MODEL_SOURCE,
    DockerEnvironment,
    sha256_of,
)
from validation.vslice.harness import (
    BenchmarkLimits,
    SliceOptions,
    run_slice,
)

ROOT = Path(__file__).resolve().parents[2]
CACHE_ROOT = ROOT / "artifacts" / "vslice-cache"
MANIFEST = CACHE_ROOT / "artifacts.json"
MODEL_FILE = CACHE_ROOT / "cache" / "model.gguf"
ENGINE_TAR = CACHE_ROOT / "cache" / "engine.tar.gz"
ENGINE_BIN = CACHE_ROOT / "cache" / "engine" / "llama-b10400" / "llama-server"

PLAN_A = "plan-vslice-libri-q4-a"
PLAN_B = "plan-vslice-libri-q4-b"


def _load_manifest() -> dict[str, str]:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {}


def _save_manifest(manifest: dict[str, str]) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _ensure_model(environment: DockerEnvironment) -> None:
    if not MODEL_FILE.exists():
        print(f"downloading model ({MODEL_SOURCE})")
        environment.download_artifact(MODEL_SOURCE, MODEL_DIGEST, MODEL_FILE)
    actual = sha256_of(MODEL_FILE)
    if actual != MODEL_DIGEST:
        raise SystemExit(f"model digest mismatch: {actual} != {MODEL_DIGEST}")
    print(f"model ready: {MODEL_FILE.name} sha256 {actual}")


def _ensure_engine(environment: DockerEnvironment) -> str:
    manifest = _load_manifest()
    recorded = manifest.get("engine_sha256", "")
    if ENGINE_TAR.exists() and recorded and sha256_of(ENGINE_TAR) == recorded:
        digest = recorded
        print(f"engine cached: sha256 {digest}")
    else:
        print(f"downloading engine ({ENGINE_SOURCE})")
        environment.download_artifact(ENGINE_SOURCE, recorded, ENGINE_TAR)
        digest = sha256_of(ENGINE_TAR)
        manifest["engine_sha256"] = digest
        _save_manifest(manifest)
        print(f"engine downloaded: sha256 {digest}")
    if not ENGINE_BIN.exists():
        print("extracting engine bundle")
        engine_dir = CACHE_ROOT / "cache" / "engine"
        engine_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(ENGINE_TAR, "r:gz") as archive:
            archive.extractall(engine_dir, filter="data")
    if not ENGINE_BIN.exists():
        raise SystemExit("llama-server not found in engine archive")
    return digest


def _ensure_image(environment: DockerEnvironment) -> None:
    image = (
        "morpheus/vslice-runtime@"
        "sha256:64a2f90ec51d971f13b1fdb0f735e18bc78c4b40cfe17b404041224e33a101b8"
    )
    if not environment.image_present(image):
        raise SystemExit(
            "pinned runtime image is missing; build it with validation/vslice/runtime.Dockerfile"
        )


def _real_catalog(engine_digest: str) -> tuple[DeploymentPlan, ...]:
    model = ModelIdentity(
        model_id="model-smollm2-135m-instruct",
        revision="f0a2b81",
        artifact_digest=MODEL_DIGEST,
        model_format="gguf",
        quantization="q4_k_m",
        license_id="apache-2.0",
        source="huggingface",
    )
    engine = EngineIdentity(
        engine_id="engine-llama-cpp-b10400-ubuntu-x64",
        kind="llama.cpp",
        artifact_digest=engine_digest,
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
        "source_evidence_digest": MODEL_DIGEST,
    }
    return (
        DeploymentPlan(plan_id=PLAN_A, settings=(("context_length", 2048), ("threads", 2)), **base),
        DeploymentPlan(plan_id=PLAN_B, settings=(("context_length", 1024), ("threads", 2)), **base),
    )


def main() -> int:
    fresh = "--fresh" in sys.argv[1:]
    if fresh:
        checkpoints = CACHE_ROOT / "checkpoints"
        if checkpoints.exists():
            for item in checkpoints.glob("*.json"):
                item.unlink()
    environment = DockerEnvironment(CACHE_ROOT)
    _ensure_image(environment)
    _ensure_model(environment)
    engine_digest = _ensure_engine(environment)

    machine = MachineProfile(
        machine_id="machine-batmobile-vslice",
        platform="linux",
        architecture="x86_64",
        accelerator="cpu",
        memory_bytes=4 * 1024**3,
        disk_bytes=16 * 1024**3,
    )
    workload = WorkloadProfile(
        workload_id="workload-vslice-0001",
        developer_profile="full-stack",
        context_tokens=2_048,
        max_concurrency=1,
        required_features=("chat",),
    )
    options = SliceOptions(
        machine=machine,
        workload=workload,
        catalog=_real_catalog(engine_digest),
        plan_a_id=PLAN_A,
        plan_b_id=PLAN_B,
        cache_root=CACHE_ROOT,
        prompt="Explain TCP in one sentence.",
        max_tokens=24,
        startup_timeout_s=60.0,
        benchmark_limits=BenchmarkLimits(max_seconds=120, max_tokens_per_second=1_000),
    )

    report = run_slice(environment, options)

    print("\n=== VSLICE-001 real slice report ===")
    print(f"acquisition_a: {report.acquisition.record.state}")
    print(f"campaign_a:    {report.campaign_a.record.state}")
    print(f"promotion_a:   {report.promotion_a.record.state}")
    print(f"campaign_b:    {report.campaign_b.record.state}")
    print(f"promotion_b:   {report.promotion_b.record.state}")
    print(f"rollback:      {report.rollback.record.state}")
    print(f"plan_after:    {report.plan_after_rollback.plan_id}")
    print(f"health_after:  {report.health_after_rollback}")
    if report.measurements is not None:
        print(f"ttft_s:        {report.measurements.ttft_s:.3f}")
        print(f"tokens_per_s:  {report.measurements.tokens_per_second:.2f}")
    print(f"external same: {report.external_after == report.external_before}")
    print(f"orphans:       {report.cleanup_orphans}")
    print(f"checkpoints:   {len(report.checkpoints)}")

    fresh_measurement = report.measurements is None or report.measurements.ttft_s > 0
    ok = (
        report.acquisition.record.state == "staged"
        and report.campaign_a.record.state == "succeeded"
        and report.promotion_a.record.state == "active"
        and report.campaign_b.record.state == "succeeded"
        and report.promotion_b.record.state == "active"
        and report.rollback.record.state == "completed"
        and report.health_after_rollback is True
        and fresh_measurement
        and report.cleanup_orphans == ()
        and report.external_after == report.external_before
    )
    print(f"overall: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
