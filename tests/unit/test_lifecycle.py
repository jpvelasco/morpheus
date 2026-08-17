from __future__ import annotations

from dataclasses import replace

import pytest

from morpheus.core.lifecycle import (
    LifecycleAction,
    LifecycleOutcome,
    LifecycleRequest,
    LifecycleSnapshot,
)
from morpheus.ops.lifecycle import ExternalRuntimeChanged, LifecycleCoordinator


class FakeLifecycleAdapter:
    def __init__(self) -> None:
        self.state = LifecycleSnapshot()
        self.external_identity = "protected-runtime-digest"
        self.calls: list[tuple[str, str | None]] = []
        self.fail_action: LifecycleAction | None = None
        self.recovered: LifecycleSnapshot | None = None

    def snapshot(self) -> LifecycleSnapshot:
        return self.state

    def protected_runtime_identity(self) -> str:
        return self.external_identity

    def apply(self, request: LifecycleRequest) -> None:
        self.calls.append((request.action.value, request.version or request.backup_id))
        if request.action is self.fail_action:
            self.state = replace(self.state, running=False)
            raise RuntimeError("injected lifecycle failure")

        if request.action is LifecycleAction.INSTALL:
            self.state = replace(
                self.state,
                installed=True,
                active_version=request.version,
                schema_version=1,
            )
        elif request.action is LifecycleAction.START:
            self.state = replace(self.state, running=True)
        elif request.action is LifecycleAction.STOP:
            self.state = replace(self.state, running=False)
        elif request.action is LifecycleAction.MIGRATE:
            self.state = replace(self.state, schema_version=1)
        elif request.action is LifecycleAction.BACKUP:
            self.state = replace(
                self.state,
                backup_ids=self.state.backup_ids | frozenset({request.backup_id or ""}),
            )
        elif request.action is LifecycleAction.UPGRADE:
            self.state = replace(
                self.state,
                active_version=request.version,
                previous_version=self.state.active_version,
                installed=True,
            )
        elif request.action is LifecycleAction.ROLLBACK:
            self.state = replace(
                self.state,
                active_version=self.state.previous_version,
                previous_version=None,
                installed=True,
            )
        elif request.action is LifecycleAction.UNINSTALL:
            purged = request.confirmation is not None
            self.state = (
                LifecycleSnapshot()
                if purged
                else replace(self.state, installed=False, running=False)
            )

    def recover(self, snapshot: LifecycleSnapshot) -> None:
        self.calls.append(("recover", snapshot.active_version))
        self.recovered = snapshot
        self.state = snapshot


def execute_twice(
    coordinator: LifecycleCoordinator, request: LifecycleRequest
) -> tuple[LifecycleOutcome, LifecycleOutcome]:
    first = coordinator.execute(request)
    second = coordinator.execute(request)
    return first.outcome, second.outcome


def test_REL_003_repeated_install_start_stop_migrate_backup_and_preflight_are_defined() -> None:
    adapter = FakeLifecycleAdapter()
    coordinator = LifecycleCoordinator(adapter=adapter, project_id="morpheus-lab")

    assert execute_twice(
        coordinator,
        LifecycleRequest(action=LifecycleAction.INSTALL, version="0.1.0"),
    ) == (LifecycleOutcome.APPLIED, LifecycleOutcome.ALREADY_SATISFIED)
    assert execute_twice(coordinator, LifecycleRequest(action=LifecycleAction.START)) == (
        LifecycleOutcome.APPLIED,
        LifecycleOutcome.ALREADY_SATISFIED,
    )
    assert execute_twice(coordinator, LifecycleRequest(action=LifecycleAction.STOP)) == (
        LifecycleOutcome.APPLIED,
        LifecycleOutcome.ALREADY_SATISFIED,
    )
    assert execute_twice(coordinator, LifecycleRequest(action=LifecycleAction.MIGRATE)) == (
        LifecycleOutcome.ALREADY_SATISFIED,
        LifecycleOutcome.ALREADY_SATISFIED,
    )
    assert execute_twice(
        coordinator,
        LifecycleRequest(action=LifecycleAction.BACKUP, backup_id="before-upgrade"),
    ) == (LifecycleOutcome.APPLIED, LifecycleOutcome.ALREADY_SATISFIED)
    assert execute_twice(
        coordinator,
        LifecycleRequest(
            action=LifecycleAction.RESTORE_PREFLIGHT,
            backup_id="before-upgrade",
        ),
    ) == (LifecycleOutcome.VALIDATED, LifecycleOutcome.VALIDATED)


def test_REL_003_repeated_validate_upgrade_rollback_and_uninstall_are_defined() -> None:
    adapter = FakeLifecycleAdapter()
    coordinator = LifecycleCoordinator(adapter=adapter, project_id="morpheus-lab")
    coordinator.execute(LifecycleRequest(action=LifecycleAction.INSTALL, version="0.1.0"))

    assert execute_twice(
        coordinator,
        LifecycleRequest(action=LifecycleAction.VALIDATE, version="0.1.0"),
    ) == (LifecycleOutcome.VALIDATED, LifecycleOutcome.VALIDATED)
    assert execute_twice(
        coordinator,
        LifecycleRequest(action=LifecycleAction.UPGRADE, version="0.2.0"),
    ) == (LifecycleOutcome.APPLIED, LifecycleOutcome.ALREADY_SATISFIED)
    assert execute_twice(coordinator, LifecycleRequest(action=LifecycleAction.ROLLBACK)) == (
        LifecycleOutcome.APPLIED,
        LifecycleOutcome.ALREADY_SATISFIED,
    )
    assert execute_twice(coordinator, LifecycleRequest(action=LifecycleAction.UNINSTALL)) == (
        LifecycleOutcome.APPLIED,
        LifecycleOutcome.ALREADY_SATISFIED,
    )


def test_INV_001_lifecycle_rejects_changed_protected_runtime_identity() -> None:
    adapter = FakeLifecycleAdapter()
    coordinator = LifecycleCoordinator(adapter=adapter, project_id="morpheus-lab")
    original_apply = adapter.apply

    def mutate_external(request: LifecycleRequest) -> None:
        original_apply(request)
        adapter.external_identity = "changed-protected-runtime-digest"

    adapter.apply = mutate_external  # type: ignore[method-assign]

    with pytest.raises(ExternalRuntimeChanged, match="protected external runtime changed"):
        coordinator.execute(LifecycleRequest(action=LifecycleAction.INSTALL, version="0.1.0"))


def test_REL_003_failed_upgrade_recovers_the_exact_preoperation_snapshot() -> None:
    adapter = FakeLifecycleAdapter()
    coordinator = LifecycleCoordinator(adapter=adapter, project_id="morpheus-lab")
    coordinator.execute(LifecycleRequest(action=LifecycleAction.INSTALL, version="0.1.0"))
    coordinator.execute(LifecycleRequest(action=LifecycleAction.START))
    before = adapter.snapshot()
    adapter.fail_action = LifecycleAction.UPGRADE

    with pytest.raises(RuntimeError, match="injected lifecycle failure"):
        coordinator.execute(LifecycleRequest(action=LifecycleAction.UPGRADE, version="0.2.0"))

    assert adapter.recovered == before
    assert adapter.snapshot() == before


def test_INV_004_purge_requires_lab_authorization_and_exact_project_confirmation() -> None:
    with pytest.raises(ValueError, match="lab authorization"):
        LifecycleRequest(
            action=LifecycleAction.UNINSTALL,
            confirmation="purge:morpheus-lab",
        )

    adapter = FakeLifecycleAdapter()
    coordinator = LifecycleCoordinator(adapter=adapter, project_id="morpheus-lab")
    with pytest.raises(ValueError, match="confirmation"):
        coordinator.execute(
            LifecycleRequest(
                action=LifecycleAction.UNINSTALL,
                confirmation="purge:other-project",
                lab_authorized=True,
            )
        )

    request = LifecycleRequest(
        action=LifecycleAction.UNINSTALL,
        confirmation="purge:morpheus-lab",
        lab_authorized=True,
    )
    assert request.purge is True


@pytest.mark.parametrize(
    ("action", "version", "backup_id"),
    [
        (LifecycleAction.INSTALL, None, None),
        (LifecycleAction.UPGRADE, "../escape", None),
        (LifecycleAction.BACKUP, None, "../escape"),
        (LifecycleAction.RESTORE_PREFLIGHT, None, None),
    ],
)
def test_SEC_002_lifecycle_rejects_missing_or_path_shaped_identifiers(
    action: LifecycleAction,
    version: str | None,
    backup_id: str | None,
) -> None:
    with pytest.raises(ValueError):
        LifecycleRequest(action=action, version=version, backup_id=backup_id)


def test_INV_001_structured_result_exposes_only_external_integrity_comparison() -> None:
    adapter = FakeLifecycleAdapter()
    result = LifecycleCoordinator(adapter=adapter, project_id="morpheus-lab").execute(
        LifecycleRequest(action=LifecycleAction.INSTALL, version="0.1.0")
    )

    payload = result.as_dict()
    assert payload["protected_external_runtime"] == "unchanged"
    assert "protected-runtime-digest" not in str(payload)


@pytest.mark.parametrize(
    "snapshot",
    [
        LifecycleSnapshot(installed=False, running=False),
    ],
)
def test_REL_003_lifecycle_snapshot_public_shape_is_stable(snapshot: LifecycleSnapshot) -> None:
    assert snapshot.public_dict()["backup_count"] == 0


def test_REL_003_lifecycle_snapshot_rejects_impossible_or_unsafe_state() -> None:
    with pytest.raises(ValueError, match="running"):
        LifecycleSnapshot(running=True)
    with pytest.raises(ValueError, match="invalid version"):
        LifecycleSnapshot(active_version="../escape")
    with pytest.raises(ValueError, match="negative"):
        LifecycleSnapshot(schema_version=-1)
    with pytest.raises(ValueError, match="backup"):
        LifecycleSnapshot(backup_ids=frozenset({"../escape"}))


@pytest.mark.parametrize(
    "factory",
    [
        lambda: LifecycleRequest(LifecycleAction.START, backup_id="not-accepted"),
        lambda: LifecycleRequest(LifecycleAction.START, version="0.1.0"),
        lambda: LifecycleRequest(
            LifecycleAction.BACKUP,
            backup_id="valid",
            confirmation="purge:morpheus-lab",
            lab_authorized=True,
        ),
        lambda: LifecycleRequest(LifecycleAction.UNINSTALL, lab_authorized=True),
    ],
)
def test_SEC_002_lifecycle_request_rejects_fields_outside_the_fixed_action(
    factory: object,
) -> None:
    with pytest.raises(ValueError):
        factory()  # type: ignore[operator]


@pytest.mark.parametrize("project_id", ["", "ai", "open-webui", "coder-model"])
def test_INV_001_lifecycle_coordinator_rejects_protected_project_identity(
    project_id: str,
) -> None:
    with pytest.raises(ValueError, match="project_id"):
        LifecycleCoordinator(adapter=FakeLifecycleAdapter(), project_id=project_id)


@pytest.mark.parametrize(
    "operation",
    [
        LifecycleRequest(LifecycleAction.START),
        LifecycleRequest(LifecycleAction.MIGRATE),
        LifecycleRequest(LifecycleAction.UPGRADE, version="0.2.0"),
        LifecycleRequest(LifecycleAction.ROLLBACK),
    ],
)
def test_REL_003_stateful_operations_fail_closed_before_install(
    operation: LifecycleRequest,
) -> None:
    coordinator = LifecycleCoordinator(adapter=FakeLifecycleAdapter(), project_id="morpheus-lab")
    with pytest.raises(RuntimeError):
        coordinator.execute(operation)


def test_REL_003_install_rejects_implicit_upgrade() -> None:
    coordinator = LifecycleCoordinator(adapter=FakeLifecycleAdapter(), project_id="morpheus-lab")
    coordinator.execute(LifecycleRequest(LifecycleAction.INSTALL, version="0.1.0"))

    with pytest.raises(RuntimeError, match="use upgrade"):
        coordinator.execute(LifecycleRequest(LifecycleAction.INSTALL, version="0.2.0"))
