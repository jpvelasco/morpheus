"""Owned-root fixture stage hooks for disposable R3 labs.

These hooks never launch a real engine. They persist plan markers under the
Morpheus-owned data directory so install, configure, promote, and rollback
can be exercised without a GPU or external runtime.
"""

from __future__ import annotations

import json
from pathlib import Path

from morpheus.core.durable import write_json_atomic
from morpheus.core.paths import OwnedPathResolver
from morpheus.core.records import DeploymentPlan


class FixtureStageHooks:
    """File-marker StageHooks confined to ``{data_dir}/runtime``."""

    def __init__(self, data_dir: Path) -> None:
        self._resolver = OwnedPathResolver(Path(data_dir) / "runtime")

    def initialize(self) -> None:
        self._resolver.root.mkdir(parents=True, exist_ok=True)
        self._path("plans").mkdir(parents=True, exist_ok=True)

    def _path(self, relative: str) -> Path:
        return self._resolver.resolve_relative(relative)

    def _plan_dir(self, plan_id: str) -> Path:
        return self._path(f"plans/{plan_id}")

    def _write(self, relative: str, payload: dict[str, object]) -> None:
        write_json_atomic(self._path(relative), payload)

    def _write_plan_marker(
        self, plan: DeploymentPlan, name: str, payload: dict[str, object]
    ) -> Path:
        self.initialize()
        directory = self._plan_dir(plan.plan_id)
        directory.mkdir(parents=True, exist_ok=True)
        marker = directory / name
        write_json_atomic(marker, payload)
        return marker

    def _read(self, relative: str) -> dict[str, object] | None:
        target = self._path(relative)
        if not target.is_file():
            return None
        document = json.loads(target.read_text(encoding="utf-8"))
        return document if isinstance(document, dict) else None

    def stage_engine(self, plan: DeploymentPlan) -> Path:
        return self._write_plan_marker(
            plan,
            "engine.json",
            {
                "plan_id": plan.plan_id,
                "engine_id": plan.engine.engine_id,
                "kind": plan.engine.kind,
                "artifact_digest": plan.engine.artifact_digest,
            },
        )

    def active_plan_id(self) -> str | None:
        document = self._read("active.json")
        value = None if document is None else document.get("plan_id")
        return value if isinstance(value, str) else None

    def last_known_good_plan_id(self) -> str | None:
        document = self._read("last_known_good.json")
        value = None if document is None else document.get("plan_id")
        return value if isinstance(value, str) else None

    def validate(self, plan: DeploymentPlan) -> tuple[str, ...]:
        marker = self._plan_dir(plan.plan_id) / "engine.json"
        if not marker.is_file():
            return (f"plan {plan.plan_id} has no staged engine marker",)
        return ()

    def backup_config(self, plan: DeploymentPlan) -> Path | None:
        marker = self._plan_dir(plan.plan_id) / "config.json"
        if not marker.is_file():
            return None
        backup = self._plan_dir(plan.plan_id) / "config.previous.json"
        backup.write_text(marker.read_text(encoding="utf-8"), encoding="utf-8")
        return backup

    def write_config(self, plan: DeploymentPlan) -> Path:
        return self._write_plan_marker(
            plan,
            "config.json",
            {
                "plan_id": plan.plan_id,
                "engine_id": plan.engine.engine_id,
                "settings": dict(plan.settings),
            },
        )

    def activate(self, plan: DeploymentPlan) -> None:
        self.initialize()
        if self.validate(plan):
            raise ValueError(f"cannot activate unstaged plan {plan.plan_id}")
        current = self.active_plan_id()
        if current and current != plan.plan_id:
            self._write("last_known_good.json", {"plan_id": current})
        self._write("active.json", {"plan_id": plan.plan_id})
        (self._plan_dir(plan.plan_id) / "active").write_text(plan.plan_id, encoding="utf-8")

    def deactivate(self, plan: DeploymentPlan) -> None:
        marker = self._plan_dir(plan.plan_id) / "active"
        marker.unlink(missing_ok=True)
        if self.active_plan_id() == plan.plan_id:
            active = self._path("active.json")
            active.unlink(missing_ok=True)

    def cleanup(self, plan: DeploymentPlan) -> None:
        directory = self._plan_dir(plan.plan_id)
        if not directory.exists():
            return
        for child in directory.iterdir():
            child.unlink()
        directory.rmdir()
