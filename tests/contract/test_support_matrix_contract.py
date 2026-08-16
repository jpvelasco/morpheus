"""Contract tests: evidence-bounded support report (ACCESS-003).

The support report is assembled from retained evidence runs and benchmark
runs only; it advertises nothing without a PASS run behind it, and it
never names a physical target without matching retained evidence.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from morpheus.adapters.fakes import FakeClock, FakeInference
from morpheus.api.app import create_app
from morpheus.config import MorpheusSettings
from morpheus.core.benchmark import CampaignDeclaration, RunIdentity
from morpheus.core.benchstore import BenchmarkStore, CampaignRun
from morpheus.core.health import Evidence, HealthState
from morpheus.core.models import ModelIdentity
from morpheus.ops.evidence import CanaryGuard, EvidenceRun, EvidenceRunSpec, EvidenceStatus

NOW = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)
SOURCE_COMMIT = "0123456789abcdef0123456789abcdef0123456789abcdef"
AUTH = {"Authorization": "Bearer test-api-key"}


def client(tmp_path: Path) -> TestClient:
    app = create_app(
        settings=MorpheusSettings(
            api_key="test-api-key",
            session_secret="session-test-secret",
            data_dir=tmp_path,
            release_version="0.1.0",
            source_commit=SOURCE_COMMIT,
        ),
        inference=FakeInference(
            health_result=Evidence(
                state=HealthState.READY,
                reason_code="ok",
                summary="fixture ready",
                observed_at=NOW,
                duration=timedelta(milliseconds=1),
                source="fixture",
                expires_at=NOW,
            ),
            model_results=(
                ModelIdentity(
                    root="fixture-model", aliases=("fixture-model",), context_window=4096
                ),
            ),
        ),
        clock=FakeClock(now=NOW),
    )
    return TestClient(app)


def write_evidence_run(
    root: Path,
    run_id: str,
    *,
    environment: str,
    machine_profile: dict[str, str],
    deployment: dict[str, object],
    status: EvidenceStatus = EvidenceStatus.PASS,
) -> None:
    run = EvidenceRun.create(
        root,
        run_id,
        EvidenceRunSpec(
            task_ids=("AID-001",),
            requirement_ids=("AID-001",),
            environment=environment,
            source_commit=SOURCE_COMMIT,
        ),
        guard=CanaryGuard({}),
        started_at=NOW,
    )
    run.write_json("machine_profile.json", machine_profile)
    run.write_json("deployment.json", deployment)
    run.write_json("regressions.json", [])
    run.write_json("runbooks.json", [])
    run.finalize(
        status,
        ended_at=NOW,
        safe_summary="contract fixture evidence run",
        tool_versions={"morpheus": "0.1.0"},
    )


def write_benchmark_run(
    store: BenchmarkStore, run_id: str, *, machine_id: str, engine_id: str
) -> None:
    declaration = CampaignDeclaration(
        name="contract-campaign",
        campaign_type="speed",
        benchmark_revision="b1",
        duration_seconds=60,
        concurrency=1,
        ownership_target="contract",
    )
    identity = RunIdentity(
        machine_id=machine_id,
        model_id="fixture-model",
        model_revision="r1",
        quantization="q4",
        engine_id=engine_id,
        engine_version="1.0",
        benchmark_revision="b1",
    )
    store.store_run(
        CampaignRun(
            run_id=run_id,
            declaration=declaration,
            identity=identity,
            started_at=NOW,
            ended_at=NOW,
            status="completed",
        )
    )


def test_ACCESS_003_support_report_is_empty_without_evidence(tmp_path: Path) -> None:
    response = client(tmp_path).get("/api/v1/support", headers=AUTH)
    assert response.status_code == 200
    support = response.json()["support"]
    assert support["advertised"] == []
    for dimension in support["dimensions"]:
        assert dimension["state"] == "unproven"
        assert dimension["value"] == ""
    assert {target["target"] for target in support["targets"]} == {
        "ubuntu-1",
        "ubuntu-2",
        "windows-x64",
        "macos-arm64",
    }
    for target in support["targets"]:
        assert target["validated"] is False
        for claim in target["claims"]:
            assert claim["state"] == "unproven"
            assert claim["evidence_refs"] == []


def test_ACCESS_003_every_declared_claim_carries_artifact_lane_and_rollback(
    tmp_path: Path,
) -> None:
    response = client(tmp_path).get("/api/v1/support", headers=AUTH)
    assert response.status_code == 200
    for target in response.json()["support"]["targets"]:
        for claim in target["claims"]:
            assert claim["artifact"] in {"evidence_run", "benchmark_run"}
            assert claim["lane"] in {"HOST-RO", "HOST-MAINT"}
            assert claim["rollback_path"]


def test_ACCESS_003_report_claims_only_retained_evidence(tmp_path: Path) -> None:
    write_evidence_run(
        tmp_path / "diagnostics",
        "diag-1",
        environment="DEV",
        machine_profile={"platform": "linux", "architecture": "x86_64"},
        deployment={"engine_id": "llama.cpp"},
    )
    response = client(tmp_path).get("/api/v1/support", headers=AUTH)
    assert response.status_code == 200
    dimensions = {item["dimension"]: item for item in response.json()["support"]["dimensions"]}
    assert dimensions["os"]["state"] == "proven"
    assert dimensions["os"]["value"] == "linux"
    assert dimensions["architecture"]["state"] == "proven"
    assert dimensions["engine"]["state"] == "proven"
    assert dimensions["engine"]["value"] == "llama.cpp"
    assert dimensions["accelerator"]["state"] == "unproven"
    assert dimensions["install"]["state"] == "unproven"
    os_ref = dimensions["os"]["evidence_refs"][0]
    assert os_ref.startswith("diag-1:")


def test_ACCESS_003_failed_runs_never_advertise(tmp_path: Path) -> None:
    write_evidence_run(
        tmp_path / "diagnostics",
        "diag-broken",
        environment="DEV",
        machine_profile={"platform": "linux"},
        deployment={},
        status=EvidenceStatus.FAIL,
    )
    response = client(tmp_path).get("/api/v1/support", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["support"]["advertised"] == []


def test_ACCESS_003_benchmark_claim_comes_from_completed_runs(tmp_path: Path) -> None:
    benchmark_store = BenchmarkStore(tmp_path / "benchmarks")
    benchmark_store.initialize()
    write_benchmark_run(benchmark_store, "bench-1", machine_id="ubuntu-1", engine_id="vllm")
    response = client(tmp_path).get("/api/v1/support", headers=AUTH)
    assert response.status_code == 200
    dimensions = {item["dimension"]: item for item in response.json()["support"]["dimensions"]}
    assert dimensions["benchmark"]["state"] == "proven"
    assert dimensions["benchmark"]["value"] == "vllm@ubuntu-1"
    assert dimensions["benchmark"]["evidence_refs"] == ["bench-1:completed"]
    ubuntu-1 = next(
        target for target in response.json()["support"]["targets"] if target["target"] == "ubuntu-1"
    )
    benchmark_claim = next(
        claim for claim in ubuntu-1["claims"] if claim["dimension"] == "benchmark"
    )
    assert benchmark_claim["state"] == "proven"
    assert benchmark_claim["evidence_refs"] == ["bench-1:completed"]


def test_ACCESS_003_dev_evidence_never_names_physical_targets(tmp_path: Path) -> None:
    write_evidence_run(
        tmp_path / "diagnostics",
        "diag-1",
        environment="DEV",
        machine_profile={"machine_id": "ubuntu-1", "platform": "linux"},
        deployment={"engine_id": "llama.cpp"},
    )
    response = client(tmp_path).get("/api/v1/support", headers=AUTH)
    assert response.status_code == 200
    for target in response.json()["support"]["targets"]:
        assert target["validated"] is False
        assert all(claim["state"] == "unproven" for claim in target["claims"])


def test_ACCESS_003_target_named_evidence_is_advertised(tmp_path: Path) -> None:
    write_evidence_run(
        tmp_path / "diagnostics",
        "diag-ubuntu-1",
        environment="HOST-RO",
        machine_profile={
            "machine_id": "ubuntu-1",
            "platform": "linux",
            "architecture": "x86_64",
            "accelerator": "cuda",
        },
        deployment={
            "engine_id": "vllm",
            "install_method": "mrpkg",
            "access_profile": "loopback",
            "recovery": True,
        },
    )
    benchmark_store = BenchmarkStore(tmp_path / "benchmarks")
    benchmark_store.initialize()
    write_benchmark_run(benchmark_store, "bench-1", machine_id="ubuntu-1", engine_id="vllm")
    response = client(tmp_path).get("/api/v1/support", headers=AUTH)
    targets = {target["target"]: target for target in response.json()["support"]["targets"]}
    ubuntu-1 = targets["ubuntu-1"]
    proven = {claim["dimension"] for claim in ubuntu-1["claims"] if claim["state"] == "proven"}
    assert {
        "os",
        "architecture",
        "accelerator",
        "engine",
        "install",
        "access",
        "recovery",
    } <= proven
    assert ubuntu-1["validated"] is False
    os_claim = next(claim for claim in ubuntu-1["claims"] if claim["dimension"] == "os")
    assert os_claim["evidence_refs"][0].startswith("diag-ubuntu-1:")
    assert targets["ubuntu-2"]["validated"] is False
    assert targets["windows-x64"]["validated"] is False


def test_ACCESS_003_report_requires_authentication(tmp_path: Path) -> None:
    response = client(tmp_path).get("/api/v1/support")
    assert response.status_code == 401


def test_ACCESS_003_report_never_contains_secrets(tmp_path: Path) -> None:
    write_evidence_run(
        tmp_path / "diagnostics",
        "diag-1",
        environment="DEV",
        machine_profile={"platform": "linux"},
        deployment={"engine_id": "llama.cpp", "api_key": "super-secret-value"},
    )
    response = client(tmp_path).get("/api/v1/support", headers=AUTH)
    assert response.status_code == 200
    assert "super-secret-value" not in response.text
