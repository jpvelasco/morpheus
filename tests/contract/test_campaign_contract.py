"""Contract tests: authorized campaign runner (BENCH-001, BENCH-005)."""

from __future__ import annotations

import threading
from datetime import UTC, datetime

import pytest

from morpheus.core.benchmark import (
    BenchmarkSample,
    CampaignDeclaration,
    RunIdentity,
    summarize_samples,
)
from morpheus.core.benchstore import BenchmarkStore
from morpheus.core.campaign import (
    CampaignRunContext,
    authorization_token,
    run_campaign,
)

pytestmark = pytest.mark.contract


def declaration() -> CampaignDeclaration:
    return CampaignDeclaration(
        name="contract-campaign",
        campaign_type="speed",
        benchmark_revision="bench-2026.2",
        duration_seconds=120,
        concurrency=1,
        ownership_target="DEV",
        stop_conditions=(("target_samples", 12), ("max_errors", 2)),
    )


def identity() -> RunIdentity:
    return RunIdentity(
        machine_id="fixture-machine",
        model_id="llama-3.1-8b-instruct",
        model_revision="v0.1",
        quantization="q8_0",
        engine_id="llama.cpp",
        engine_version="0.1.0",
        benchmark_revision="bench-2026.2",
    )


def work(ctx: CampaignRunContext, index: int) -> BenchmarkSample:
    return BenchmarkSample(
        run_id=ctx.run_id,
        started_at=datetime(2026, 8, 1, 12, 0, index, tzinfo=UTC),
        sequence_index=index,
        duration_seconds=0.1,
        ttft_seconds=0.05,
        tokens_per_second=30.0,
        generated_tokens=16,
    )


def test_campaign_produces_raw_and_summary_records(tmp_path) -> None:
    store = BenchmarkStore(tmp_path)
    run = run_campaign(
        declaration(),
        identity(),
        work,
        store,
        authorized=authorization_token(),
        ownership_target="DEV",
        run_id="contract-run",
    )
    assert run.status == "completed"
    samples = store.load_samples("contract-run")
    assert len(samples) == 12
    summary = summarize_samples("contract-run", samples)
    store.store_summary(summary)
    assert store.load_summary("contract-run").sample_count == 12


def test_declared_limits_never_exceeded(tmp_path) -> None:
    counter: list[int] = []

    def counted(ctx: CampaignRunContext, index: int) -> BenchmarkSample:
        counter.append(index)
        return work(ctx, index)

    store = BenchmarkStore(tmp_path)
    run_campaign(
        declaration(),
        identity(),
        counted,
        store,
        authorized=authorization_token(),
        ownership_target="DEV",
        run_id="contract-limits",
    )
    assert len(counter) == 12


def test_routine_calls_cannot_start_load(tmp_path) -> None:
    with pytest.raises(PermissionError):
        run_campaign(
            declaration(),
            identity(),
            work,
            BenchmarkStore(tmp_path),
            authorized=False,
            ownership_target="DEV",
            run_id="contract-denied",
        )


def test_cancellation_leaves_resumable_state(tmp_path) -> None:
    event = threading.Event()

    def interruptible(ctx: CampaignRunContext, index: int) -> BenchmarkSample:
        if index == 6:
            event.set()
        return work(ctx, index)

    store = BenchmarkStore(tmp_path)
    first = run_campaign(
        declaration(),
        identity(),
        interruptible,
        store,
        authorized=authorization_token(),
        ownership_target="DEV",
        run_id="contract-resume",
        stop_event=event,
    )
    assert first.status == "cancelled"
    checkpoint = dict(first.checkpoint)
    assert checkpoint["completed_samples"] == 7
    second = run_campaign(
        declaration(),
        identity(),
        interruptible,
        store,
        authorized=authorization_token(),
        ownership_target="DEV",
        run_id="contract-resume",
    )
    assert second.status == "completed"
    assert len(store.load_samples("contract-resume")) == 12
