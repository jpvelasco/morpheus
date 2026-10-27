"""Explicit disposable runtime composition shared by application tests."""

from pathlib import Path

from morpheus.adapters.persistence.records_store import RecordsStore
from morpheus.adapters.runtime.stage import FixtureStageHooks
from morpheus.adapters.workflows.executors import FixtureLifecycleExecutor
from morpheus.core.deployment import DeploymentStore
from morpheus.ops.planning import PlanningService


def fixture_executor(data_dir: Path, hooks: FixtureStageHooks) -> FixtureLifecycleExecutor:
    return FixtureLifecycleExecutor(
        planning=PlanningService(
            records=RecordsStore(data_dir / "records"),
            plans=DeploymentStore(data_dir / "deployments"),
        ),
        data_dir=data_dir,
        hooks=hooks,
    )
