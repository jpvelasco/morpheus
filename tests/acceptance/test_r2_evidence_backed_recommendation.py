"""R2 acceptance: evidence-backed recommendation (SEL-004, SEL-005, issue #56).

Guarantees under test (RECTIFICATION_PLAN.md section 6, R2):
- the public recommendation path loads one retained catalog digest and the
  stable persisted machine profile instead of ``SEED_CATALOG``;
- measured, foreign-machine, stale, incomparable, estimated, and missing
  evidence produce distinct confidence/provenance/comparability outcomes;
- replaying only the immutable record inputs yields an identical timestamp-free
  record (byte-equivalent ranking and exclusions);
- choosing a lower-ranked candidate records the operator choice against the
  canonical plan family without rewriting the recommendation.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from morpheus.adapters.fakes import FakeClock, FakeInference
from morpheus.adapters.persistence.records_store import RecordsStore
from morpheus.api.app import create_app
from morpheus.config import MorpheusSettings
from morpheus.core.benchmark import (
    BenchmarkSummary,
    CampaignDeclaration,
    RunIdentity,
)
from morpheus.core.benchstore import BenchmarkStore, CampaignRun, sha256_hex
from morpheus.core.catalog import (
    SEED_CATALOG,
    CatalogCollection,
    EngineCatalogEntry,
    ModelCatalogEntry,
)
from morpheus.core.recommendation import canonical_json
from morpheus.core.solver import HardwareBudget
from morpheus.ops.planning import machine_profile_from_budget
from morpheus.ops.recommendation import catalog_snapshot_digest

pytestmark = pytest.mark.acceptance

NOW = datetime(2026, 8, 23, 12, 0, 0, tzinfo=UTC)
STALE_DAY = date(2026, 5, 1)
FRESH_DAY = date(2026, 8, 20)
_AUTH = {"Authorization": "Bearer test-api-key"}
OPERATOR = {"max_concurrency": 1}


def _budget() -> HardwareBudget:
    return HardwareBudget(
        ram_bytes=4 * 1024**3,
        vram_bytes=0,
        storage_bytes=16 * 1024**3,
        accelerator="cpu",
    )


def _reference_machine_id() -> str:
    return machine_profile_from_budget(_budget()).machine_id


FOREIGN_MACHINE_ID = "machine-r2-foreign"


def _model(model_id: str) -> ModelCatalogEntry:
    return ModelCatalogEntry(
        id=model_id,
        name=model_id,
        license="apache-2.0",
        architecture="transformer",
        modalities=("text",),
        formats=("gguf",),
        quantizations=("q4_k_m",),
        context_window=8192,
        artifact_size_bytes=128 * 1024**2,
        validation_freshness=FRESH_DAY,
        source_url="https://example.test/models",
        source_digest=sha256_hex(model_id.encode()),
        revision="r2",
        engine_support=("engine-r2-test",),
        features=("tool_calling",),
    )


def _catalog() -> CatalogCollection:
    models = [
        _model("model-r2-measured"),
        _model("model-r2-stale"),
        _model("model-r2-foreign"),
        _model("model-r2-estimated"),
        _model("model-r2-not-in-seed"),
    ]
    engines = [
        EngineCatalogEntry(
            id="engine-r2-test",
            name="R2 test engine",
            license="mit",
            version="1.0.0",
            platforms=("linux-x86_64",),
            features=("tool_calling",),
        )
    ]
    return CatalogCollection(version="r2-test-0001", models=models, engines=engines)


def _declaration(run_id: str) -> CampaignDeclaration:
    return CampaignDeclaration(
        name=run_id,
        campaign_type="speed",
        benchmark_revision="bench-r2",
        duration_seconds=60,
        concurrency=1,
        ownership_target="managed",
    )


def _identity(run_id: str, machine_id: str, model_id: str) -> RunIdentity:
    return RunIdentity(
        machine_id=machine_id,
        model_id=model_id,
        model_revision="r2",
        quantization="q4_k_m",
        engine_id="engine-r2-test",
        engine_version="1.0.0",
        benchmark_revision="bench-r2",
        context_window=8192,
    )


def _run(run_id: str, machine_id: str, model_id: str, ended_day: date) -> CampaignRun:
    return CampaignRun(
        run_id=run_id,
        declaration=_declaration(run_id),
        identity=_identity(run_id, machine_id, model_id),
        started_at=datetime.combine(ended_day, datetime.min.time(), tzinfo=UTC),
        ended_at=datetime.combine(ended_day, datetime.min.time().replace(hour=1), tzinfo=UTC),
        status="completed",
    )


def _summary(
    run_id: str,
    *,
    ttft_seconds: float | None,
    tokens_per_second: float | None,
) -> BenchmarkSummary:
    return BenchmarkSummary(
        run_id=run_id,
        sample_count=8,
        statistic="p50",
        ttft_seconds=ttft_seconds,
        tokens_per_second=tokens_per_second,
    )


def _seed_benchmarks(benchmarks: BenchmarkStore) -> None:
    benchmarks.initialize()
    reference = _reference_machine_id()
    runs = [
        (
            # Measured on the reference machine, but the campaign never
            # captured throughput: decode_throughput has no evidence at all
            # for this candidate (missing comparability).
            _run("run-r2-measured", reference, "model-r2-measured", FRESH_DAY),
            _summary("run-r2-measured", ttft_seconds=0.05, tokens_per_second=None),
        ),
        (
            _run("run-r2-stale", reference, "model-r2-stale", STALE_DAY),
            _summary("run-r2-stale", ttft_seconds=0.04, tokens_per_second=45.0),
        ),
        # Fresh measurements from a different machine on a candidate whose
        # values stay calibrated while their contributions drop to zero.
        (
            _run("run-r2-foreign", FOREIGN_MACHINE_ID, "model-r2-foreign", FRESH_DAY),
            _summary("run-r2-foreign", ttft_seconds=0.03, tokens_per_second=60.0),
        ),
    ]
    for run, summary in runs:
        benchmarks.store_run(run)
        benchmarks.store_summary(summary)


class HostRuntimeAgent:
    """Runtime agent stub returning the deterministic host facts under test."""

    async def inspect(self, operation: Any) -> Any:
        from morpheus.agent.protocol import AgentOperation, AgentResponse

        result: dict[str, Any] = {"containers": []}
        if operation is AgentOperation.HOST_SUMMARY:
            result = {
                "memory": {"total_bytes": 4 * 1024**3},
                "disk": {"total_bytes": 16 * 1024**3},
            }
        elif operation is AgentOperation.GPU_SUMMARY:
            result = {"gpus": []}
        return AgentResponse(request_id="fixture", operation=operation, result=result)


def _client(tmp_path: Any) -> TestClient:
    app = create_app(
        settings=MorpheusSettings(
            api_key="test-api-key",
            session_secret="session-test-secret",
            data_dir=tmp_path,
            enable_workflows=True,
        ),
        inference=FakeInference(health_result=_ready_evidence(), model_results=()),
        clock=FakeClock(now=NOW),
        runtime_agent=HostRuntimeAgent(),
    )
    client = TestClient(app, base_url="https://testserver")
    records = RecordsStore(tmp_path / "records")
    records.initialize()
    collection = _catalog()
    records.save_catalog_snapshot(catalog_snapshot_digest(collection), collection.to_dict())
    _seed_benchmarks(BenchmarkStore(tmp_path / "benchmarks"))
    return client


def _ready_evidence() -> Any:
    from morpheus.core.health import Evidence, HealthState

    return Evidence(
        state=HealthState.READY,
        reason_code="models_ready",
        summary="Inference API is ready",
        observed_at=NOW,
        duration=timedelta(milliseconds=2),
        source="fixture",
        expires_at=NOW + timedelta(seconds=30),
    )


def _signed_in(api: TestClient) -> dict[str, str]:
    response = api.post(
        "/api/v1/session",
        json={"api_key": "test-api-key"},
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200
    csrf = api.cookies.get("morpheus_csrf", "")
    return {"X-CSRF-Token": csrf}


def _recommend(client: TestClient, catalog_digest: str) -> dict[str, Any]:
    response = client.post(
        "/api/v1/recommendations",
        json={
            "profile": "developer-default",
            "operator": OPERATOR,
            "catalog_digest": catalog_digest,
        },
        headers=_AUTH,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _contributions(ranked: list[dict[str, Any]], model_id: str) -> dict[str, dict[str, Any]]:
    for entry in ranked:
        if entry["candidate"]["model_id"] == model_id:
            return {item["metric"]: item for item in entry["contributions"]}
    raise AssertionError(f"{model_id} was not ranked")


# ---------------------------------------------------------------------------
# Criterion 1: the recommendation path consumes the retained catalog snapshot
# and the stable persisted machine profile — never SEED_CATALOG.
# ---------------------------------------------------------------------------


def test_R2_recommendation_loads_retained_catalog_and_stable_machine_profile(
    tmp_path: Any,
) -> None:
    client = _client(tmp_path)
    digest = catalog_snapshot_digest(_catalog())

    payload = _recommend(client, digest)

    assert payload["catalog_digest"] == digest
    expected_machine = _reference_machine_id()
    assert payload["machine_profile"]["machine_id"] == expected_machine
    recommendation = payload["recommendation"]
    assert recommendation["reference_machine_id"] == expected_machine

    ranked_models = {entry["candidate"]["model_id"] for entry in recommendation["ranked"]}
    # Every retained-catalog model is ranked through the repository path.
    assert "model-r2-not-in-seed" in ranked_models
    # No seed-catalog leakage: only snapshot models appear.
    assert ranked_models.isdisjoint({entry.id for entry in SEED_CATALOG.models})

    # The canonical selection family received the same evidence-ranked order.
    selection = client.get("/api/v1/plans/selections/latest", headers=_AUTH).json()[
        "recommendation"
    ]
    assert selection["machine_id"] == expected_machine
    assert len(selection["plan_ids"]) == len(recommendation["ranked"])

    # The chosen-from plans exist as canonical plans.
    first_plan = selection["plan_ids"][0]
    assert client.get(f"/api/v1/plans/{first_plan}", headers=_AUTH).status_code == 200


# ---------------------------------------------------------------------------
# Criterion 2: measured, foreign-machine, stale, estimated, and missing
# evidence produce distinct confidence/provenance outcomes.
# ---------------------------------------------------------------------------


def test_R2_evidence_classes_produce_distinct_outcomes(tmp_path: Any) -> None:
    client = _client(tmp_path)
    payload = _recommend(client, catalog_snapshot_digest(_catalog()))
    ranked = payload["recommendation"]["ranked"]

    measured = _contributions(ranked, "model-r2-measured")
    assert measured["time_to_first_token"]["comparability"] == "comparable"
    assert measured["time_to_first_token"]["provenance"] == "measured"
    assert measured["time_to_first_token"]["effective_confidence"] == pytest.approx(1.0)
    assert measured["time_to_first_token"]["source"] == "run-r2-measured"
    # Its throughput metric was never measured: missing, not zero.
    assert measured["decode_throughput"]["comparability"] == "missing"
    assert measured["decode_throughput"]["contribution"] == 0.0

    stale = _contributions(ranked, "model-r2-stale")
    assert stale["time_to_first_token"]["comparability"] == "comparable"
    assert stale["time_to_first_token"]["provenance"] == "measured"
    assert stale["time_to_first_token"]["effective_confidence"] == pytest.approx(0.5)

    foreign = _contributions(ranked, "model-r2-foreign")
    assert foreign["time_to_first_token"]["comparability"] == "incomparable"
    assert foreign["time_to_first_token"]["contribution"] == 0.0

    estimated = _contributions(ranked, "model-r2-estimated")
    assert estimated["memory_headroom"]["provenance"] == "estimated"
    assert estimated["memory_headroom"]["effective_confidence"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Criterion 3: replaying the immutable record inputs reproduces the record
# byte-for-byte once provenance timestamps are excluded.
# ---------------------------------------------------------------------------


def test_R2_replay_is_byte_equivalent_without_observation_timestamps(
    tmp_path: Any,
) -> None:
    client = _client(tmp_path)
    digest = catalog_snapshot_digest(_catalog())

    first = _recommend(client, digest)["recommendation"]
    second = _recommend(client, digest)["recommendation"]

    assert first["record_id"] == second["record_id"]

    def timestamp_free(record: dict[str, Any]) -> str:
        payload = {key: value for key, value in record.items() if key != "created_at"}
        return canonical_json(payload)

    assert timestamp_free(first) == timestamp_free(second)


# ---------------------------------------------------------------------------
# Criterion 4: choosing a lower-ranked candidate creates the canonical plan
# and records the operator choice without rewriting the recommendation.
# ---------------------------------------------------------------------------


def test_R2_lower_ranked_choice_records_plan_and_preserves_recommendation(
    tmp_path: Any,
) -> None:
    client = _client(tmp_path)
    payload = _recommend(client, catalog_snapshot_digest(_catalog()))
    ranked = payload["recommendation"]["ranked"]
    selection = payload["canonical_selection"]

    lower_entry = ranked[-1]
    lower_plan_id = lower_entry["plan_id"]
    assert lower_plan_id != selection["plan_ids"][0]

    response = client.post(
        "/api/v1/plans/from-recommendation",
        json={
            "recommendation_id": selection["recommendation_id"],
            "plan_id": lower_plan_id,
            "ownership": "managed",
        },
        headers={**_AUTH, **_signed_in(client)},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["selected_plan_id"] == lower_plan_id

    stored = client.get(f"/api/v1/plans/{lower_plan_id}", headers=_AUTH)
    assert stored.status_code == 200
    assert stored.json()["plan"]["plan_id"] == lower_plan_id

    latest = client.get("/api/v1/plans/selections/latest", headers=_AUTH).json()["recommendation"]
    assert latest == selection

    after = _recommend(client, catalog_snapshot_digest(_catalog()))["recommendation"]
    assert after["record_id"] == payload["recommendation"]["record_id"]
