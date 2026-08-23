"""Owned-path adapter for the canonical record repositories (RUNM-001).

One store owns every canonical record family except deployment lifecycle
aggregates (those live in ``core.deployment.DeploymentStore``). Records are
persisted as envelope-encoded documents keyed by ``record_type/record_id``,
written atomically, and never re-derived on read: a stored document that no
longer rebuilds to its exact id is surfaced as an integrity error rather than
silently accepted.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from morpheus.core.durable import write_json_atomic
from morpheus.core.paths import OwnedPathError, OwnedPathResolver
from morpheus.core.records import (
    BenchmarkCampaign,
    DeploymentPlan,
    MachineProfile,
    Recommendation,
    WorkloadProfile,
    encode_record,
    record_from_public_dict,
)
from morpheus.core.repositories import (
    ActivePlanState,
    OperationRecord,
)

_SCHEMA_VERSION = 1


class RecordStoreError(ValueError):
    """A canonical record document violates its identity contract."""


def _record_type_name(record: Any) -> str:
    from morpheus.core.records import _RECORD_TYPE_NAMES

    name = _RECORD_TYPE_NAMES.get(type(record))
    if name is None:
        raise RecordStoreError(f"{type(record).__name__} is not a canonical record")
    return name


def _decode(document: bytes) -> tuple[str, int, str, dict[str, Any]]:
    payload = json.loads(document.decode("utf-8"))
    return (
        payload["record_type"],
        payload["schema_version"],
        payload["record_id"],
        payload["payload"],
    )


def _rebuild(record_type: str, payload: dict[str, Any]) -> Any:
    from morpheus.core.records import _RECORD_TYPES

    return record_from_public_dict(_RECORD_TYPES[record_type], payload)


def _operation_from_document(document: dict[str, Any]) -> OperationRecord:
    fields = dict(document["operation"])
    requested_at = fields.get("requested_at")
    if isinstance(requested_at, str):
        fields["requested_at"] = datetime.fromisoformat(requested_at)
    return OperationRecord(**fields)


class RecordsStore:
    """Implements the machine/catalog/workload/recommendation/campaign/
    operation repository protocols over one owned root."""

    def __init__(self, root: Path) -> None:
        self.resolver = OwnedPathResolver(root)

    def _path(self, relative: str) -> Path:
        return self.resolver.resolve_relative(relative)

    def initialize(self) -> None:
        self.resolver.root.mkdir(parents=True, exist_ok=True)

    # -- generic canonical-record persistence --------------------------------

    def put(self, record: Any) -> None:
        record_type = _record_type_name(record)
        relative = f"{record_type}s/{record.record_id}.json"
        target = self._path(relative)
        encoded = encode_record(record)
        if target.exists():
            existing_type, _, existing_id, existing_payload = _decode(target.read_bytes())
            rebuilt = _rebuild(existing_type, existing_payload)
            if (
                existing_type != record_type
                or existing_id != record.record_id
                or rebuilt != record
            ):
                raise RecordStoreError(
                    f"identity collision at {relative}: stored document differs"
                )
            return
        write_json_atomic(target, json.loads(encoded.decode("utf-8")))

    def get(self, record_type: str, record_id: str) -> Any | None:
        target = self._path(f"{record_type}s/{record_id}.json")
        if not target.exists():
            return None
        stored_type, _, stored_id, payload = _decode(target.read_bytes())
        if stored_type != record_type or stored_id != record_id:
            raise RecordStoreError(
                f"document {record_id} declares identity {stored_type}/{stored_id}"
            )
        return _rebuild(record_type, payload)

    # -- typed facades --------------------------------------------------------

    def save_machine_profile(self, profile: MachineProfile) -> None:
        self.put(profile)

    def machine_profile(self, machine_id: str) -> MachineProfile | None:
        return self.get("machine_profile", machine_id)

    def save_workload(self, workload: WorkloadProfile) -> None:
        self.put(workload)

    def workload(self, workload_id: str) -> WorkloadProfile | None:
        return self.get("workload_profile", workload_id)

    def save_plan(self, plan: DeploymentPlan) -> None:
        self.put(plan)

    def plan(self, plan_id: str) -> DeploymentPlan | None:
        return self.get("deployment_plan", plan_id)

    def plans(self) -> tuple[DeploymentPlan, ...]:
        return tuple(self.list_of("deployment_plan"))  # type: ignore[arg-type]

    def save_recommendation(self, recommendation: Recommendation) -> None:
        self.put(recommendation)

    def recommendation(self, recommendation_id: str) -> Recommendation | None:
        return self.get("recommendation", recommendation_id)

    def recommendations(self) -> tuple[Recommendation, ...]:
        return tuple(self.list_of("recommendation"))  # type: ignore[arg-type]

    def save_campaign(self, campaign: BenchmarkCampaign) -> None:
        self.put(campaign)

    def campaign(self, campaign_id: str) -> BenchmarkCampaign | None:
        return self.get("benchmark_campaign", campaign_id)

    def campaigns_for_plan(self, plan_id: str) -> tuple[BenchmarkCampaign, ...]:
        return tuple(
            campaign
            for campaign in self.list_of("benchmark_campaign")
            if isinstance(campaign, BenchmarkCampaign) and campaign.plan_id == plan_id
        )

    # -- catalog snapshots (collection documents, not envelope records) ------

    def save_catalog_snapshot(self, digest: str, collection: dict[str, Any]) -> None:
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise RecordStoreError("catalog snapshot digest must be sha256 hex")
        write_json_atomic(
            self._path(f"catalog_snapshots/{digest}.json"),
            {"schema_version": _SCHEMA_VERSION, "digest": digest, "collection": collection},
        )

    def catalog_snapshot(self, digest: str) -> dict[str, Any] | None:
        target = self._path(f"catalog_snapshots/{digest}.json")
        if not target.exists():
            return None
        document = json.loads(target.read_text(encoding="utf-8"))
        if document.get("digest") != digest:
            raise RecordStoreError("catalog snapshot document does not match its digest")
        return document["collection"]

    # -- operations ------------------------------------------------------------

    def save_operation(self, operation: OperationRecord) -> None:
        target = self._path(f"operations/{operation.operation_id}.json")
        document = {
            "schema_version": _SCHEMA_VERSION,
            "operation": operation.public_dict(),
        }
        if target.exists():
            stored = json.loads(target.read_text(encoding="utf-8"))
            if stored != document:
                raise RecordStoreError(
                    f"operation {operation.operation_id} is already recorded differently"
                )
            return
        write_json_atomic(target, document)

    def operation(self, operation_id: str) -> OperationRecord | None:
        target = self._path(f"operations/{operation_id}.json")
        if not target.exists():
            return None
        document = json.loads(target.read_text(encoding="utf-8"))
        return _operation_from_document(document)

    def operations_for_plan(self, plan_id: str) -> tuple[OperationRecord, ...]:
        operations_dir = self._path("operations")
        if not operations_dir.exists():
            return ()
        found = [
            _operation_from_document(json.loads(path.read_text(encoding="utf-8")))
            for path in sorted(operations_dir.glob("*.json"))
        ]
        return tuple(operation for operation in found if operation.plan_id == plan_id)

    # -- helpers -----------------------------------------------------------------

    def list_of(self, record_type: str) -> tuple[Any, ...]:
        directory = self._path(f"{record_type}s")
        if not directory.exists():
            return ()
        found: list[Any] = []
        for path in sorted(directory.glob("*.json")):
            stored_type, _, stored_id, payload = _decode(path.read_bytes())
            if stored_type != record_type or stored_id != path.stem:
                raise RecordStoreError(
                    f"document {path.name} declares identity {stored_type}/{stored_id}"
                )
            found.append(_rebuild(record_type, payload))
        return tuple(found)


class ActivePlanFileRepository:
    """Durable active/last-known-good pointer shared by planning surfaces."""

    def __init__(self, root: Path) -> None:
        self._resolver = OwnedPathResolver(root)

    def active_state(self) -> ActivePlanState:
        path = self._resolver.resolve_relative("active_plan.json")
        if not path.exists():
            return ActivePlanState(active_plan_id=None, last_known_good_plan_id=None)
        document = json.loads(path.read_text(encoding="utf-8"))
        return ActivePlanState(
            active_plan_id=document.get("active_plan_id"),
            last_known_good_plan_id=document.get("last_known_good_plan_id"),
        )

    def set_active_state(self, active_plan_id: str | None, previous_plan_id: str | None) -> None:
        path = self._resolver.resolve_relative("active_plan.json")
        write_json_atomic(
            path,
            {
                "schema_version": _SCHEMA_VERSION,
                "active_plan_id": active_plan_id,
                "last_known_good_plan_id": previous_plan_id,
            },
        )


__all__ = ["ActivePlanFileRepository", "RecordStoreError", "RecordsStore"]
