"""Typed boundary for explicitly configured owned control actions."""

from pathlib import Path
from typing import Protocol


class ControlActionsPort(Protocol):
    def apply(self, *, control: str, action: str, plan_id: str) -> Path | None: ...
