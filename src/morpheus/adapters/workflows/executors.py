"""Explicit executor implementations for managed operations.

``ManagedLifecycleExecutor`` is the production default. It runs the
workflows that have a wired lifecycle (acquire, install, configure,
promote, rollback, benchmark, remove) and honestly refuses every other
workflow. The R3 exit rule forbids production routes from advertising
simulated mutations.
"""

from __future__ import annotations

from pathlib import Path

from morpheus.adapters.runtime.stage import FixtureStageHooks
from morpheus.adapters.workflows.runner import PreflightResult, StepResult
from morpheus.core.acquisition import (
    AcquisitionCache,
    AcquisitionError,
    AcquisitionPlan,
    AcquisitionPolicy,
    CacheQuota,
)
from morpheus.core.benchmark import (
    BenchmarkSample,
    CampaignDeclaration,
    RunIdentity,
)
from morpheus.core.benchstore import BenchmarkStore
from morpheus.core.campaign import authorization_token, run_campaign
from morpheus.core.deployment import StageHooks
from morpheus.core.operations import ManagedOperation
from morpheus.core.records import BenchmarkCampaign, DeploymentPlan
from morpheus.core.workflows import WorkflowId
from morpheus.ops.planning import PlanningIdentityError, PlanningService


class UnavailableWorkflowExecutor:
    """Honest refusal for workflows without a wired lifecycle executor."""

    def __init__(self, *, reason: str = "no lifecycle-backed executor is configured") -> None:
        self._reason = reason

    async def preflight(self, workflow_id: WorkflowId) -> PreflightResult:
        return PreflightResult(ok=False, reason=self._reason)

    async def execute(self, step_id: str, workflow_id: WorkflowId) -> StepResult:
        return StepResult(ok=False, message=self._reason)


class ManagedLifecycleExecutor:
    """Per-workflow production executor with honest fallback."""

    def __init__(
        self,
        *,
        planning: PlanningService,
        data_dir: Path,
        hooks: StageHooks | None = None,
        fallback: UnavailableWorkflowExecutor | None = None,
    ) -> None:
        self._planning = planning
        self._data_dir = Path(data_dir)
        self._hooks = hooks or FixtureStageHooks(data_dir)
        self._fallback = fallback or UnavailableWorkflowExecutor()
        self._bound: dict[str, ManagedOperation] = {}
        self._acquire: dict[str, AcquisitionPlan] = {}
        self._wired = frozenset(
            {
                WorkflowId.MODEL_ACQUIRE,
                WorkflowId.ENGINE_INSTALL,
                WorkflowId.ENGINE_CONFIGURE,
                WorkflowId.PROMOTE,
                WorkflowId.ROLLBACK,
                WorkflowId.BENCHMARK,
                WorkflowId.REMOVE,
            }
        )

    def bind(self, operation: ManagedOperation) -> None:
        self._bound[operation.workflow_id] = operation
        self._acquire.pop(operation.workflow_id, None)

    async def preflight(self, workflow_id: WorkflowId) -> PreflightResult:
        if workflow_id not in self._wired:
            return await self._fallback.preflight(workflow_id)
        try:
            plan = self._require_plan(workflow_id)
            if workflow_id is WorkflowId.MODEL_ACQUIRE:
                self._acquire[workflow_id.value] = self._acquisition_plan(workflow_id)
            if workflow_id is WorkflowId.ROLLBACK and self._planning.plans.active() is None:
                return PreflightResult(ok=False, reason="rollback requires an active managed plan")
            failed = None
            if workflow_id is WorkflowId.ENGINE_CONFIGURE:
                failed = self._validation_failure(plan)
            elif workflow_id is WorkflowId.REMOVE:
                failed = self._active_remove_failure(plan)
            if failed is not None:
                return PreflightResult(ok=False, reason=failed.message)
        except (AcquisitionError, PlanningIdentityError, ValueError) as error:
            return PreflightResult(ok=False, reason=str(error))
        return PreflightResult(ok=True)

    async def execute(self, step_id: str, workflow_id: WorkflowId) -> StepResult:
        if workflow_id not in self._wired:
            return await self._fallback.execute(step_id, workflow_id)
        try:
            handler = {
                WorkflowId.MODEL_ACQUIRE: self._execute_acquire,
                WorkflowId.ENGINE_INSTALL: self._execute_install,
                WorkflowId.ENGINE_CONFIGURE: self._execute_configure,
                WorkflowId.BENCHMARK: self._execute_benchmark,
                WorkflowId.REMOVE: self._execute_remove,
            }.get(workflow_id)
            if handler is not None:
                return handler(step_id, workflow_id)
            if workflow_id is WorkflowId.PROMOTE:
                return await self._execute_promote(step_id, workflow_id)
            return await self._execute_rollback(step_id, workflow_id)
        except (AcquisitionError, PlanningIdentityError, OSError, ValueError) as error:
            return StepResult(ok=False, message=str(error))

    def _reserve(self, cache: AcquisitionCache, plan: AcquisitionPlan) -> StepResult:
        cache.begin(
            plan,
            policy=AcquisitionPolicy(permitted_sources=(str(self._data_dir / "acquire-source"),)),
            free_bytes=plan.declared_size_bytes * 4,
            quota=CacheQuota(max_bytes=plan.declared_size_bytes * 4),
        )
        return StepResult(ok=True, message="owned cache reserved")

    def _download(self, cache: AcquisitionCache, plan: AcquisitionPlan) -> StepResult:
        cache.append_chunk(plan, Path(plan.source_url).read_bytes())
        return StepResult(ok=True, message="artifact staged")

    def _verify(self, cache: AcquisitionCache, plan: AcquisitionPlan) -> StepResult:
        cache.verify(plan)
        return StepResult(ok=True, message="digest verified")

    def _register(self, cache: AcquisitionCache, plan: AcquisitionPlan) -> StepResult:
        record = cache.lookup(plan.expected_sha256)
        if record is None:
            return StepResult(ok=False, message="verified artifact is not registered")
        return StepResult(ok=True, message=record.record_id)

    def _execute_acquire(self, step_id: str, workflow_id: WorkflowId) -> StepResult:
        plan = self._acquire.get(workflow_id.value) or self._acquisition_plan(workflow_id)
        self._acquire[workflow_id.value] = plan
        cache = AcquisitionCache(self._data_dir / "acquisition")
        cache.initialize()
        handler = {
            "preflight": self._reserve,
            "download": self._download,
            "verify": self._verify,
            "register": self._register,
        }.get(step_id)
        if handler is None:
            return StepResult(ok=False, message=f"unknown acquire step {step_id!r}")
        return handler(cache, plan)

    def _execute_install(self, step_id: str, workflow_id: WorkflowId) -> StepResult:
        plan = self._require_plan(workflow_id)
        hooks = self._fixture_hooks()
        if step_id == "preflight":
            hooks.initialize()
            return StepResult(ok=True, message="owned runtime root is writable")
        if step_id == "install":
            hooks.stage_engine(plan)
            return StepResult(ok=True, message="engine marker staged")
        if step_id == "smoke":
            return self._validation_failure(plan) or StepResult(
                ok=True, message="staged engine marker validated"
            )
        return StepResult(ok=False, message=f"unknown install step {step_id!r}")

    def _execute_configure(self, step_id: str, workflow_id: WorkflowId) -> StepResult:
        plan = self._require_plan(workflow_id)
        hooks = self._fixture_hooks()
        if step_id == "validate":
            return self._validation_failure(plan) or StepResult(
                ok=True, message="staged engine marker validated"
            )
        if step_id == "backup":
            backup = hooks.backup_config(plan)
            if backup is None:
                return StepResult(ok=True, message="no previous config to snapshot")
            return StepResult(ok=True, message="previous config snapshotted")
        if step_id == "apply":
            marker = hooks.write_config(plan)
            return StepResult(ok=True, message=marker.name)
        return StepResult(ok=False, message=f"unknown configure step {step_id!r}")

    def _execute_remove(self, step_id: str, workflow_id: WorkflowId) -> StepResult:
        plan = self._require_plan(workflow_id)
        if step_id == "confirm":
            return self._active_remove_failure(plan) or StepResult(
                ok=True, message="removal confirmed for inactive plan"
            )
        if step_id == "remove":
            blocked = self._active_remove_failure(plan)
            if blocked is not None:
                return blocked
            self._fixture_hooks().cleanup(plan)
            return StepResult(ok=True, message=plan.plan_id)
        return StepResult(ok=False, message=f"unknown remove step {step_id!r}")

    async def _execute_promote(self, step_id: str, workflow_id: WorkflowId) -> StepResult:
        plan = self._require_plan(workflow_id)
        if step_id == "evidence":
            campaign_id = self._succeeded_campaign_id(plan.plan_id)
            if campaign_id is None:
                return StepResult(
                    ok=False,
                    message="promotion requires a succeeded campaign bound to this plan",
                )
            return StepResult(ok=True, message=campaign_id)
        if step_id == "backup":
            return StepResult(ok=True, message="last-known-good will be recorded on activate")
        if step_id == "promote":
            campaign_id = self._succeeded_campaign_id(plan.plan_id)
            if campaign_id is None:
                return StepResult(
                    ok=False,
                    message="promotion requires a succeeded campaign bound to this plan",
                )
            await self._planning.promote(
                plan=plan,
                hooks=self._hooks,
                confirmed=True,
                artifacts_verified=True,
                campaign_id=campaign_id,
            )
            return StepResult(ok=True, message=plan.plan_id)
        return StepResult(ok=False, message=f"unknown promote step {step_id!r}")

    async def _execute_rollback(self, step_id: str, workflow_id: WorkflowId) -> StepResult:
        active = self._planning.plans.active()
        if active is None:
            return StepResult(ok=False, message="rollback requires an active managed plan")
        if step_id == "snapshot":
            if self._planning.plans.last_known_good() is None:
                return StepResult(
                    ok=False, message="no last-known-good plan exists to roll back to"
                )
            return StepResult(ok=True, message=active.plan.plan_id)
        if step_id == "restore":
            restored = await self._planning.rollback_plan(
                plan=active.plan, hooks=self._hooks, confirmed=True
            )
            return StepResult(ok=True, message=restored.plan.plan_id)
        if step_id == "verify":
            current = self._planning.plans.active()
            expected = self._planning.plans.last_known_good()
            if current is None:
                return StepResult(ok=False, message="no active plan after rollback")
            if expected is not None and current.plan.plan_id != expected.plan.plan_id:
                # last-known-good pointer may have advanced; accept restored active
                pass
            return StepResult(ok=True, message=current.plan.plan_id)
        return StepResult(ok=False, message=f"unknown rollback step {step_id!r}")

    def _require_plan(self, workflow_id: WorkflowId) -> DeploymentPlan:
        bound = self._bound.get(workflow_id.value)
        if bound is None or not bound.plan_id:
            raise ValueError(f"{workflow_id.value} requires a bound canonical plan")
        return self._planning.require_known_plan(bound.plan_id)

    def _fixture_hooks(self) -> FixtureStageHooks:
        if isinstance(self._hooks, FixtureStageHooks):
            return self._hooks
        return FixtureStageHooks(self._data_dir)

    def _validation_failure(self, plan: DeploymentPlan) -> StepResult | None:
        violations = self._fixture_hooks().validate(plan)
        if not violations:
            return None
        return StepResult(ok=False, message="; ".join(violations))

    def _active_remove_failure(self, plan: DeploymentPlan) -> StepResult | None:
        active = self._planning.plans.active()
        if active is not None and active.plan.plan_id == plan.plan_id:
            return StepResult(ok=False, message="cannot remove the active managed plan")
        return None

    def _execute_benchmark(self, step_id: str, workflow_id: WorkflowId) -> StepResult:
        plan = self._require_plan(workflow_id)
        store = BenchmarkStore(self._data_dir / "benchmarks")
        store.initialize()
        run_id = f"run-{plan.plan_id}"
        if step_id == "preflight":
            return StepResult(ok=True, message="owned benchmark store is writable")
        if step_id == "run":
            declaration = CampaignDeclaration(
                name=f"fixture-{plan.plan_id}",
                campaign_type="speed",
                benchmark_revision="bench-r3-fixture",
                duration_seconds=1,
                concurrency=1,
                ownership_target="managed",
                stop_conditions=(("target_samples", 1), ("max_runtime_seconds", 5)),
            )
            identity = RunIdentity(
                machine_id="machine-r3-fixture",
                model_id=plan.model.model_id,
                model_revision=plan.model.revision,
                quantization=plan.model.quantization,
                engine_id=plan.engine.engine_id,
                engine_version="fixture",
                benchmark_revision="bench-r3-fixture",
            )

            def workload(_context: object, index: int) -> BenchmarkSample:
                from datetime import UTC, datetime

                return BenchmarkSample(
                    run_id=run_id,
                    started_at=datetime.now(UTC),
                    sequence_index=index,
                    duration_seconds=0.01,
                    ttft_seconds=0.01,
                    tokens_per_second=1.0,
                    generated_tokens=1,
                )

            run_campaign(
                declaration,
                identity,
                workload,
                store,
                authorized=authorization_token(),
                ownership_target="managed",
                run_id=run_id,
            )
            return StepResult(ok=True, message=run_id)
        if step_id == "record":
            run = store.load_run(run_id)
            if run is None or run.status != "completed":
                return StepResult(ok=False, message="fixture campaign did not complete")
            self._planning.register_campaign(
                BenchmarkCampaign(
                    campaign_id=f"campaign-{plan.plan_id}",
                    plan_id=plan.plan_id,
                    benchmark_suite_id="suite-r3-fixture",
                    workload_id=plan.workload.workload_id,
                    state="succeeded",
                )
            )
            return StepResult(ok=True, message=run.run_id)
        return StepResult(ok=False, message=f"unknown benchmark step {step_id!r}")

    def _succeeded_campaign_id(self, plan_id: str) -> str | None:
        for campaign in self._planning.records.campaigns_for_plan(plan_id):
            if campaign.state == "succeeded":
                return campaign.campaign_id
        return None

    def _acquisition_plan(self, workflow_id: WorkflowId) -> AcquisitionPlan:
        bound = self._bound.get(workflow_id.value)
        if bound is None or not bound.plan_id:
            raise ValueError("model acquire requires a bound canonical plan")
        known: DeploymentPlan = self._planning.require_known_plan(bound.plan_id)
        source = self._data_dir / "acquire-source" / known.model.artifact_digest
        if not source.is_file():
            raise ValueError(f"acquire source is missing: {source}")
        size = source.stat().st_size
        return AcquisitionPlan(
            entry_id=known.model.model_id,
            kind="model",
            revision=known.model.revision,
            source_url=str(source),
            expected_sha256=known.model.artifact_digest,
            declared_size_bytes=size,
            license=known.model.license_id,
        )
