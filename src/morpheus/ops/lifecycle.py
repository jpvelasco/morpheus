from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from morpheus.core.lifecycle import (
    CURRENT_SCHEMA_VERSION,
    LifecycleAction,
    LifecycleOutcome,
    LifecycleRequest,
    LifecycleSnapshot,
)


class LifecycleStateError(RuntimeError):
    """The requested operation is incompatible with current Morpheus state."""


class ExternalRuntimeChanged(RuntimeError):
    """A protected external identity changed across a lifecycle operation."""


class LifecycleAdapter(Protocol):
    """Typed boundary for fixed, Morpheus-owned lifecycle operations."""

    def snapshot(self) -> LifecycleSnapshot: ...

    def protected_runtime_identity(self) -> str: ...

    def apply(self, request: LifecycleRequest) -> None: ...

    def recover(self, snapshot: LifecycleSnapshot) -> None: ...


@dataclass(frozen=True, slots=True)
class LifecycleResult:
    action: LifecycleAction
    outcome: LifecycleOutcome
    before: LifecycleSnapshot
    after: LifecycleSnapshot

    def as_dict(self) -> dict[str, object]:
        return {
            "action": self.action.value,
            "after": self.after.public_dict(),
            "before": self.before.public_dict(),
            "outcome": self.outcome.value,
            "protected_external_runtime": "unchanged",
        }


class LifecycleCoordinator:
    def __init__(self, *, adapter: LifecycleAdapter, project_id: str) -> None:
        if not project_id or project_id in {"ai", "open-webui", "history-coder"}:
            raise ValueError("project_id is not a valid Morpheus lifecycle identity")
        self._adapter = adapter
        self._project_id = project_id

    def execute(self, request: LifecycleRequest) -> LifecycleResult:
        if request.purge and request.confirmation != f"purge:{self._project_id}":
            raise ValueError("purge confirmation does not match the Morpheus project")

        before = self._adapter.snapshot()
        external_before = self._adapter.protected_runtime_identity()
        outcome = self._outcome_without_mutation(request, before)
        if outcome is None:
            try:
                self._adapter.apply(request)
                after = self._adapter.snapshot()
                self._verify_postcondition(request, after)
            except Exception:
                if self._is_recoverable_mutation(request):
                    self._adapter.recover(before)
                raise
            outcome = (
                LifecycleOutcome.VALIDATED
                if request.action
                in {
                    LifecycleAction.VALIDATE,
                    LifecycleAction.RESTORE_PREFLIGHT,
                }
                else LifecycleOutcome.APPLIED
            )
        else:
            after = before

        external_after = self._adapter.protected_runtime_identity()
        if external_after != external_before:
            if outcome is LifecycleOutcome.APPLIED and self._is_recoverable_mutation(request):
                self._adapter.recover(before)
            raise ExternalRuntimeChanged("protected external runtime changed")
        return LifecycleResult(
            action=request.action,
            outcome=outcome,
            before=before,
            after=after,
        )

    @staticmethod
    def _outcome_without_mutation(
        request: LifecycleRequest, snapshot: LifecycleSnapshot
    ) -> LifecycleOutcome | None:
        action = request.action
        if action is LifecycleAction.INSTALL:
            if snapshot.installed and snapshot.active_version == request.version:
                return LifecycleOutcome.ALREADY_SATISFIED
            if snapshot.installed:
                raise LifecycleStateError("a different release is installed; use upgrade")
        elif action is LifecycleAction.START:
            if snapshot.running:
                return LifecycleOutcome.ALREADY_SATISFIED
            if not snapshot.installed:
                raise LifecycleStateError("start requires an installed release")
        elif action is LifecycleAction.STOP:
            if not snapshot.running:
                return LifecycleOutcome.ALREADY_SATISFIED
        elif action is LifecycleAction.MIGRATE:
            if not snapshot.installed:
                raise LifecycleStateError("migrate requires an installed release")
            if snapshot.schema_version >= CURRENT_SCHEMA_VERSION:
                return LifecycleOutcome.ALREADY_SATISFIED
        elif action is LifecycleAction.BACKUP:
            if request.backup_id in snapshot.backup_ids:
                return LifecycleOutcome.ALREADY_SATISFIED
        elif action is LifecycleAction.UPGRADE:
            if not snapshot.installed:
                raise LifecycleStateError("upgrade requires an installed release")
            if snapshot.active_version == request.version:
                return LifecycleOutcome.ALREADY_SATISFIED
        elif action is LifecycleAction.ROLLBACK:
            if not snapshot.installed:
                raise LifecycleStateError("rollback requires an installed release")
            if snapshot.previous_version is None:
                return LifecycleOutcome.ALREADY_SATISFIED
        elif action is LifecycleAction.UNINSTALL:
            if request.purge:
                if (
                    not snapshot.installed
                    and snapshot.active_version is None
                    and not snapshot.backup_ids
                    and snapshot.schema_version == 0
                ):
                    return LifecycleOutcome.ALREADY_SATISFIED
            elif not snapshot.installed:
                return LifecycleOutcome.ALREADY_SATISFIED
        return None

    @staticmethod
    def _is_recoverable_mutation(request: LifecycleRequest) -> bool:
        return request.action in {
            LifecycleAction.INSTALL,
            LifecycleAction.START,
            LifecycleAction.STOP,
            LifecycleAction.MIGRATE,
            LifecycleAction.UPGRADE,
            LifecycleAction.ROLLBACK,
        } or (request.action is LifecycleAction.UNINSTALL and not request.purge)

    @staticmethod
    def _verify_postcondition(request: LifecycleRequest, snapshot: LifecycleSnapshot) -> None:
        action = request.action
        valid = True
        if action is LifecycleAction.INSTALL:
            valid = snapshot.installed and snapshot.active_version == request.version
        elif action is LifecycleAction.START:
            valid = snapshot.installed and snapshot.running
        elif action is LifecycleAction.STOP:
            valid = not snapshot.running
        elif action is LifecycleAction.MIGRATE:
            valid = snapshot.schema_version >= CURRENT_SCHEMA_VERSION
        elif action is LifecycleAction.BACKUP:
            valid = request.backup_id in snapshot.backup_ids
        elif action is LifecycleAction.UPGRADE:
            valid = snapshot.installed and snapshot.active_version == request.version
        elif action is LifecycleAction.ROLLBACK:
            valid = snapshot.installed and snapshot.previous_version is None
        elif action is LifecycleAction.UNINSTALL:
            valid = not snapshot.installed
            if request.purge:
                valid = valid and snapshot.active_version is None and not snapshot.backup_ids
        if not valid:
            raise LifecycleStateError(f"{action.value} postcondition was not satisfied")
