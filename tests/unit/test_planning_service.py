"""Unit tests: canonical record repositories and planning service edges (RUNM-001)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from morpheus.adapters.persistence.records_store import (
    RecordsStore,
    RecordStoreError,
)
from morpheus.core.deployment import DeploymentStore, LossyMigrationError
from morpheus.core.records import (
    BenchmarkCampaign,
    DeploymentPlan,
    EngineIdentity,
    MachineProfile,
    ModelIdentity,
    Recommendation,
    WorkloadProfile,
)
from morpheus.core.repositories import OperationRecord
from morpheus.ops.planning import (
    PlanningIdentityError,
    PlanningService,
    machine_profile_from_budget,
)

DIGEST_A = "1" * 64
DIGEST_B = "2" * 64


def _machine(machine_id: str = "machine-edge-0001") -> MachineProfile:
    return MachineProfile(
        machine_id=machine_id,
        platform="linux",
        architecture="x86_64",
        accelerator="cpu",
        memory_bytes=1024**3,
        disk_bytes=4 * 1024**3,
    )


def _workload(workload_id: str = "workload-edge-0001") -> WorkloadProfile:
    return WorkloadProfile(
        workload_id=workload_id,
        developer_profile="full-stack",
        context_tokens=1_024,
        max_concurrency=1,
        required_features=("chat",),
    )


def _model(model_id: str = "model-edge") -> ModelIdentity:
    return ModelIdentity(
        model_id=model_id,
        revision="v1",
        artifact_digest=DIGEST_A,
        model_format="gguf",
        quantization="q4_k_m",
        license_id="apache-2.0",
        source="huggingface",
    )


def _engine() -> EngineIdentity:
    return EngineIdentity(
        engine_id="engine-edge",
        kind="llama.cpp",
        artifact_digest=DIGEST_B,
        platforms=("linux-x86_64",),
    )


def _plan(plan_id: str = "plan-edge-0001", model_id: str = "model-edge") -> DeploymentPlan:
    return DeploymentPlan(
        plan_id=plan_id,
        model=_model(model_id),
        engine=_engine(),
        workload=_workload(),
        settings=(("context_length", 1_024),),
        served_aliases=("edge-1",),
        context_tokens=1_024,
        max_concurrency=1,
        cache_policy="owned-cache",
        memory_estimate_bytes=128 * 1024**2,
        disk_estimate_bytes=64 * 1024**2,
        owned_paths=("/opt/morpheus/edge/cache",),
        ports=(8099,),
        health_contract_id="health-openai-compatible-0001",
        benchmark_gate_id="gate-edge-0001",
        rollback_target_plan_id=None,
        source_evidence_digest=DIGEST_B,
    )


def _campaign(plan_id: str, campaign_id: str = "campaign-edge-0001") -> BenchmarkCampaign:
    return BenchmarkCampaign(
        campaign_id=campaign_id,
        plan_id=plan_id,
        benchmark_suite_id="suite-edge",
        workload_id=_workload().workload_id,
        state="succeeded",
    )


class _FakeClock:
    def utc_now(self) -> datetime:
        return datetime(2026, 8, 23, tzinfo=UTC)

    def monotonic(self) -> float:
        return 0.0


# ---------------------------------------------------------------------------
# RecordsStore
# ---------------------------------------------------------------------------


def test_put_is_idempotent_for_identical_records(tmp_path: Path) -> None:
    store = RecordsStore(tmp_path / "records")
    store.initialize()
    profile = _machine()
    store.save_machine_profile(profile)
    store.save_machine_profile(profile)
    assert store.machine_profile(profile.machine_id) == profile


def test_put_rejects_identity_collisions(tmp_path: Path) -> None:
    store = RecordsStore(tmp_path / "records")
    store.initialize()
    profile = _machine()
    store.put(profile)
    tampered_dir = tmp_path / "records" / "machine_profiles"
    document_path = next(tampered_dir.glob("*.json"))
    document = json.loads(document_path.read_text(encoding="utf-8"))
    document["payload"]["memory_bytes"] = 42
    document_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(RecordStoreError, match="identity collision"):
        store.put(profile)


def test_get_detects_mislabeled_documents(tmp_path: Path) -> None:
    store = RecordsStore(tmp_path / "records")
    store.initialize()
    profile = _machine()
    store.put(profile)
    document_path = tmp_path / "records" / "machine_profiles" / f"{profile.machine_id}.json"
    document = json.loads(document_path.read_text(encoding="utf-8"))
    document["record_type"] = "workload_profile"
    document_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(RecordStoreError, match="declares identity"):
        store.get("machine_profile", profile.machine_id)


def test_catalog_snapshot_round_trip_and_digest_check(tmp_path: Path) -> None:
    store = RecordsStore(tmp_path / "records")
    store.initialize()
    digest = "a" * 64
    collection = {"models": [], "engines": [], "version": "2026.2"}

    assert store.catalog_snapshot(digest) is None
    store.save_catalog_snapshot(digest, collection)
    assert store.catalog_snapshot(digest) == collection

    with pytest.raises(RecordStoreError, match="sha256 hex"):
        store.save_catalog_snapshot("not-a-digest", collection)

    document_path = tmp_path / "records" / "catalog_snapshots" / f"{digest}.json"
    document = json.loads(document_path.read_text(encoding="utf-8"))
    document["digest"] = "b" * 64
    document_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(RecordStoreError, match="does not match its digest"):
        store.catalog_snapshot(digest)


def test_operation_records_round_trip_and_collision_detection(tmp_path: Path) -> None:
    store = RecordsStore(tmp_path / "records")
    store.initialize()

    def operation(state: str) -> OperationRecord:
        return OperationRecord(
            operation_id="operation-edge-0001",
            plan_id="plan-edge-0001",
            action="promote",
            ownership="managed",
            state=state,
            requested_at=datetime(2026, 8, 23, tzinfo=UTC),
        )

    store.save_operation(operation("active"))
    assert store.operation("operation-edge-0001").state == "active"
    assert [item.state for item in store.operations_for_plan("plan-edge-0001")] == ["active"]
    assert store.operations_for_plan("plan-other") == ()
    assert store.operation("missing-operation") is None

    with pytest.raises(RecordStoreError, match="recorded differently"):
        store.save_operation(operation("rolled_back"))


def test_operation_record_requires_managed_ownership_and_timestamps() -> None:
    with pytest.raises(ValueError, match="managed"):
        OperationRecord(
            operation_id="operation-x",
            plan_id="plan-x",
            action="promote",
            ownership="external_observed",
            state="active",
            requested_at=datetime(2026, 8, 23, tzinfo=UTC),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        OperationRecord(
            operation_id="operation-x",
            plan_id="plan-x",
            action="promote",
            ownership="managed",
            state="active",
            requested_at=datetime(2026, 8, 23),  # noqa: DTZ001 - intentionally naive
        )
    with pytest.raises(ValueError, match="plan_id"):
        OperationRecord(
            operation_id="operation-x",
            plan_id="",
            action="promote",
            ownership="managed",
            state="active",
            requested_at=datetime(2026, 8, 23, tzinfo=UTC),
        )


def test_list_of_surfaces_integrity_errors(tmp_path: Path) -> None:
    store = RecordsStore(tmp_path / "records")
    store.initialize()
    store.save_workload(_workload())
    document_path = tmp_path / "records" / "workload_profiles" / f"{_workload().workload_id}.json"
    document = json.loads(document_path.read_text(encoding="utf-8"))
    document["record_id"] = "renamed-id"
    document_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(RecordStoreError, match="declares identity"):
        store.list_of("workload_profile")


def test_list_of_on_missing_directory_is_empty(tmp_path: Path) -> None:
    store = RecordsStore(tmp_path / "records")
    store.initialize()
    assert store.plans() == ()
    assert store.recommendations() == ()
    assert store.campaigns_for_plan("plan-none") == ()


# ---------------------------------------------------------------------------
# DeploymentStore identity edges
# ---------------------------------------------------------------------------


def test_snapshot_requires_canonical_plan_instance() -> None:
    from morpheus.core.deployment import DeploymentSnapshot

    with pytest.raises(ValueError, match="canonical deployment plan"):
        DeploymentSnapshot(plan="not-a-plan")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="bounded identifier"):
        DeploymentSnapshot(plan=_plan(), campaign_id="")


def test_unknown_snapshot_schema_versions_are_rejected() -> None:
    from morpheus.core.deployment import migrate_snapshot

    with pytest.raises(LossyMigrationError, match="17"):
        migrate_snapshot({"schema_version": 17})


def test_get_plan_returns_none_for_untracked_ids(tmp_path: Path) -> None:
    store = DeploymentStore(tmp_path)
    assert store.get_plan("plan-absent") is None


# ---------------------------------------------------------------------------
# PlanningService edges
# ---------------------------------------------------------------------------


def _service(tmp_path: Path) -> tuple[PlanningService, RecordsStore]:
    records = RecordsStore(tmp_path / "records")
    plans = DeploymentStore(tmp_path / "deployments")
    service = PlanningService(records=records, plans=plans, clock=_FakeClock())
    return service, records


def test_select_without_catalog_or_fit_is_rejected(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    with pytest.raises(PlanningIdentityError, match="at least one canonical plan"):
        service.select_plan(machine=_machine(), workload=_workload(), catalog=())

    tiny_machine = MachineProfile(
        machine_id="machine-tiny",
        platform="linux",
        architecture="x86_64",
        accelerator="cpu",
        memory_bytes=1,
        disk_bytes=1,
    )
    with pytest.raises(PlanningIdentityError, match="no viable"):
        service.select_plan(machine=tiny_machine, workload=_workload(), catalog=(_plan(),))


def test_selection_is_deterministic_and_persists_every_record(tmp_path: Path) -> None:
    service, records = _service(tmp_path)
    machine, workload = _machine(), _workload()
    first = service.select_plan(machine=machine, workload=workload, catalog=(_plan(),))
    second = service.select_plan(machine=machine, workload=workload, catalog=(_plan(),))
    assert first == second
    assert records.machine_profile(machine.machine_id) == machine
    assert records.workload(workload.workload_id) == workload
    assert records.plan("plan-edge-0001") == _plan()
    assert records.recommendation(first.recommendation_id) == first
    assert service.latest_recommendation() == first
    assert service.selections()[-1] == first


def test_legacy_recommendation_conversion_accepts_plan_addressed_records(
    tmp_path: Path,
) -> None:
    payload: dict[str, Any] = {
        "record_id": "legacy-0001",
        "reference_machine_id": "machine-edge-0001",
        "plan_ids": ["plan-edge-0001"],
        "evidence_ranked": True,
        "weights": (("fit", 1.0),),
    }
    converted = PlanningService.canonical_recommendation_from_legacy(payload)
    assert isinstance(converted, Recommendation)
    assert converted.machine_id == "machine-edge-0001"


def test_rollback_requires_confirmation_and_known_plan(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    service.select_plan(machine=_machine(), workload=_workload(), catalog=(_plan(),))
    plan = _plan()
    hooks = _NoHooks()

    import asyncio

    with pytest.raises(PlanningIdentityError, match="confirmation"):
        asyncio.run(service.rollback_plan(plan=plan, hooks=hooks, confirmed=False))

    from dataclasses import replace

    missing = replace(plan, plan_id="plan-missing")
    with pytest.raises(PlanningIdentityError, match="unknown plan"):
        asyncio.run(service.rollback_plan(plan=missing, hooks=hooks, confirmed=True))


def test_promotion_requires_confirmed_operator(tmp_path: Path) -> None:
    service, records = _service(tmp_path)
    service.select_plan(machine=_machine(), workload=_workload(), catalog=(_plan(),))
    records.save_campaign(_campaign("plan-edge-0001"))

    import asyncio

    with pytest.raises(PlanningIdentityError, match="confirmation"):
        asyncio.run(
            service.promote(
                plan=_plan(),
                hooks=_NoHooks(),
                confirmed=False,
                artifacts_verified=True,
                campaign_id="campaign-edge-0001",
            )
        )


def test_operation_id_collisions_advance_sequence(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    service.select_plan(machine=_machine(), workload=_workload(), catalog=(_plan(),))

    import asyncio

    first = asyncio.run(
        service.audit_event(event="started", plan_id="plan-edge-0001", ownership="managed")
    )
    second = asyncio.run(
        service.audit_event(event="completed", plan_id="plan-edge-0001", ownership="managed")
    )
    assert first["operation_id"] != second["operation_id"]


def test_clock_defaults_to_wall_time_only_when_unset(tmp_path: Path) -> None:
    records = RecordsStore(tmp_path / "records")
    service = PlanningService(records=records, plans=DeploymentStore(tmp_path / "deployments"))
    now = service._now()
    assert now.tzinfo is UTC


def test_machine_profile_from_budget_is_content_derived() -> None:
    from morpheus.core.solver import HardwareBudget

    budget = HardwareBudget(ram_bytes=1024**3, storage_bytes=4 * 1024**3, accelerator="cpu")
    profile = machine_profile_from_budget(budget)
    assert profile.machine_id.startswith("machine-")
    assert len(profile.machine_id) == len("machine-") + 16
    same = machine_profile_from_budget(budget)
    assert same.machine_id == profile.machine_id


class _NoHooks:
    def validate(self, plan: DeploymentPlan) -> tuple[str, ...]:  # pragma: no cover - unused here
        del plan
        return ()

    def activate(self, plan: DeploymentPlan) -> None:  # pragma: no cover - unused here
        raise AssertionError("no activation expected in this test")

    def deactivate(self, plan: DeploymentPlan) -> None:  # pragma: no cover - unused here
        raise AssertionError("no deactivation expected in this test")

    def cleanup(self, plan: DeploymentPlan) -> None:  # pragma: no cover - unused here
        raise AssertionError("no cleanup expected in this test")
