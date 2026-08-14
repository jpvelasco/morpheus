"""Authorized campaign runner with limits, checkpoints, and cleanup (BENCH-005).

The runner executes only caller-provided workload callables; it never starts
load against observed external runtimes. A campaign requires explicit authority
and an ownership target match, declares its stop conditions up front, records
checkpoints so interruption is resumable, and guarantees that no workload is
left running after it returns.
"""

from __future__ import annotations

import hmac
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from morpheus.core.benchmark import (
    BenchmarkError,
    BenchmarkSample,
    CampaignDeclaration,
    RunIdentity,
)
from morpheus.core.benchstore import BenchmarkStore, CampaignRun

_AUTHORIZATION_TOKEN = "morpheus-campaign-authorized"  # noqa: S105  # nosec B105 - gate token
_CHECKPOINT_EVERY = 10


class CampaignAuthorizationError(PermissionError):
    """The campaign is not explicitly authorized for its ownership target."""


class CampaignCancelled(BenchmarkError):
    """The campaign was cancelled and left a resumable checkpoint."""


@dataclass(frozen=True, slots=True)
class CampaignRunContext:
    declaration: CampaignDeclaration
    identity: RunIdentity
    run_id: str
    deadline: datetime | None
    start_index: int
    stop_event: threading.Event


Workload = Callable[[CampaignRunContext, int], BenchmarkSample]


def _compare_token(value: str) -> bool:
    return hmac.compare_digest(value, _AUTHORIZATION_TOKEN)


def authorization_token() -> str:
    """Return the gate token callers must pass to run a campaign."""
    return _AUTHORIZATION_TOKEN


def _declared_limits(declaration: CampaignDeclaration) -> dict[str, int]:
    return dict(declaration.stop_conditions)


def run_campaign(
    declaration: CampaignDeclaration,
    identity: RunIdentity,
    workload: Workload,
    store: BenchmarkStore,
    *,
    authorized: bool | str = False,
    ownership_target: str,
    run_id: str | None = None,
    stop_event: threading.Event | None = None,
) -> CampaignRun:
    """Run a declared campaign under its limits, recording checkpoints.

    ``authorized`` must be the exact gate token from
    :func:`authorization_token`; ownership target must match the declaration.
    The workload receives (context, sample index) and must return a
    BenchmarkSample; raising CampaignCancelled or exhausting the deadline marks
    the run cancelled with a resumable checkpoint.
    """
    if authorized is False or not isinstance(authorized, str) or not _compare_token(authorized):
        raise CampaignAuthorizationError(
            "campaign requires explicit authority; routine actions cannot start load"
        )
    if declaration.ownership_target != ownership_target:
        raise CampaignAuthorizationError(
            f"ownership target mismatch: declared {declaration.ownership_target!r}, "
            f"authorized for {ownership_target!r}"
        )
    store.initialize()
    limits = _declared_limits(declaration)
    target_samples = limits.get("target_samples", 0)
    max_errors = limits.get("max_errors", 0)
    max_runtime = limits.get("max_runtime_seconds", 0)
    stop = stop_event or threading.Event()
    run_id = run_id or f"campaign-{int(time.time() * 1000)}"
    started = datetime.now(UTC)
    deadline = started + timedelta(seconds=max_runtime) if max_runtime else None
    prior = store.load_run(run_id) if _run_exists(store, run_id) else None
    start_index = 0
    prior_samples: tuple[BenchmarkSample, ...] = ()
    if prior is not None:
        resume_checkpoint = dict(prior.checkpoint)
        start_index = resume_checkpoint.get("sequence_index", 0)
        completed = resume_checkpoint.get("completed_samples", 0)
        if prior.status == "completed":
            raise BenchmarkError(f"run already terminal: {run_id}")
        prior_samples = store.load_samples(run_id)
    else:
        completed = 0
        store.store_run(
            CampaignRun(
                run_id=run_id,
                declaration=declaration,
                identity=identity,
                started_at=started,
            )
        )
    context = CampaignRunContext(
        declaration=declaration,
        identity=identity,
        run_id=run_id,
        deadline=deadline,
        start_index=start_index,
        stop_event=stop,
    )
    errors: list[str] = []
    samples: list[BenchmarkSample] = []
    status = "completed"
    sequence = start_index
    try:
        while True:
            if stop.is_set():
                status = "cancelled"
                break
            if deadline is not None and datetime.now(UTC) >= deadline:
                status = "cancelled"
                break
            if target_samples and sequence - start_index + completed >= target_samples:
                break
            if max_errors and len(errors) >= max_errors:
                status = "failed"
                break
            try:
                sample = workload(context, sequence)
            except CampaignCancelled:
                status = "cancelled"
                break
            except Exception as exc:
                errors.append(f"sample {sequence}: {type(exc).__name__}: {exc}")
                sequence += 1
                continue
            samples.append(sample)
            sequence += 1
            if sequence % _CHECKPOINT_EVERY == 0:
                store.store_run(
                    _run_document(
                        run_id,
                        declaration,
                        identity,
                        started,
                        status,
                        errors,
                        (("sequence_index", sequence), ("completed_samples", len(samples))),
                    )
                )
    finally:
        if samples:
            store.store_samples(tuple(prior_samples) + tuple(samples))
        elif prior_samples:
            store.store_samples(prior_samples)
        checkpoint = (
            (("sequence_index", sequence), ("completed_samples", completed + len(samples)))
            if status == "cancelled"
            else ()
        )
        store.store_run(
            _run_document(run_id, declaration, identity, started, status, errors, checkpoint)
        )
    return store.load_run(run_id)


def _run_exists(store: BenchmarkStore, run_id: str) -> bool:
    try:
        store.load_run(run_id)
        return True
    except BenchmarkError:
        return False


def _run_document(
    run_id: str,
    declaration: CampaignDeclaration,
    identity: RunIdentity,
    started: datetime,
    status: str,
    errors: list[str],
    checkpoint: tuple[tuple[str, int], ...],
) -> CampaignRun:
    return CampaignRun(
        run_id=run_id,
        declaration=declaration,
        identity=identity,
        started_at=started,
        ended_at=datetime.now(UTC),
        status=status,
        errors=tuple(errors),
        checkpoint=checkpoint,
    )
