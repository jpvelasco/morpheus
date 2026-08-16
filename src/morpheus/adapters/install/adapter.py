"""Package-trust-aware install adapter (DESK-002).

The adapter protocol executes a confirmed bootstrap plan against a local
runtime. The development executor records the exact operation sequence
for a plan and enforces the same gates as application: unsigned packages
require confirmation and no plan replaces a running service silently.
Native executors (systemd-user, LaunchAgent, per-user Windows service)
implement the same protocol in the physical qualification lane.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from morpheus.core.bootstrap import BootstrapPlan


class InstallError(RuntimeError):
    """A bootstrap plan failed to execute."""


@dataclass(frozen=True, slots=True)
class InstallOutcome:
    plan_kind: str
    operations: tuple[str, ...]
    ok: bool


class InstallAdapter(Protocol):
    async def execute(
        self, plan: BootstrapPlan, *, explicit_confirmation: bool
    ) -> InstallOutcome: ...


class DevInstallExecutor:
    """Records the operations a plan would perform without side effects."""

    def __init__(self) -> None:
        self.operations: list[str] = []

    async def execute(self, plan: BootstrapPlan, *, explicit_confirmation: bool) -> InstallOutcome:
        if plan.kind == "noop":
            return InstallOutcome(plan_kind="noop", operations=(), ok=True)
        if plan.confirmation_required and not explicit_confirmation:
            raise InstallError(f"{plan.kind} requires explicit confirmation: {plan.reason}")
        if not plan.confirmation_required and not plan.unattended_allowed:
            raise InstallError(f"{plan.kind} must not be applied unattended: {plan.reason}")
        operations = tuple(plan.steps)
        self.operations.extend(operations)
        return InstallOutcome(plan_kind=plan.kind, operations=operations, ok=True)
