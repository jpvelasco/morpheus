"""Acceptance: a disposable fixture campaign survives interruption without leaked work."""

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
from morpheus.core.campaign import CampaignRunContext, authorization_token, run_campaign

pytestmark = pytest.mark.acceptance


def _declaration() -> CampaignDeclaration:
    return CampaignDeclaration(
        name="fixture-campaign",
        campaign_type="speed",
        benchmark_revision="bench-2026.2",
        duration_seconds=60,
        concurrency=1,
        ownership_target="DEV",
        stop_conditions=(("target_samples", 20),),
    )


def _identity() -> RunIdentity:
    return RunIdentity(
        machine_id="fixture-machine",
        model_id="llama-3.1-8b-instruct",
        model_revision="v0.1",
        quantization="q8_0",
        engine_id="llama.cpp",
        engine_version="0.1.0",
        benchmark_revision="bench-2026.2",
    )


def _sample(ctx: CampaignRunContext, index: int) -> BenchmarkSample:
    return BenchmarkSample(
        run_id=ctx.run_id,
        started_at=datetime(2026, 8, 1, 12, 0, index, tzinfo=UTC),
        sequence_index=index,
        duration_seconds=0.1,
        ttft_seconds=0.05,
        tokens_per_second=30.0,
        generated_tokens=16,
    )


def test_fixture_campaign_interrupted_then_resumed(tmp_path) -> None:
    store = BenchmarkStore(tmp_path)
    event = threading.Event()
    attempts: list[int] = []

    def interruptible(ctx: CampaignRunContext, index: int) -> BenchmarkSample:
        attempts.append(index)
        if index == 9:
            event.set()
        return _sample(ctx, index)

    first = run_campaign(
        _declaration(),
        _identity(),
        interruptible,
        store,
        authorized=authorization_token(),
        ownership_target="DEV",
        run_id="acceptance-fixture",
        stop_event=event,
    )
    assert first.status == "cancelled"
    assert dict(first.checkpoint)["completed_samples"] == 10

    second = run_campaign(
        _declaration(),
        _identity(),
        interruptible,
        store,
        authorized=authorization_token(),
        ownership_target="DEV",
        run_id="acceptance-fixture",
    )
    assert second.status == "completed"
    assert second.errors == ()
    samples = store.load_samples("acceptance-fixture")
    assert len(samples) == 20
    assert len(attempts) == 20
    summary = summarize_samples("acceptance-fixture", samples)
    assert summary.sample_count == 20
    assert summary.ttft_seconds is not None


def test_fixture_campaign_rejects_unauthorized_start(tmp_path) -> None:
    store = BenchmarkStore(tmp_path)
    try:
        run_campaign(
            _declaration(),
            _identity(),
            _sample,
            store,
            authorized=False,
            ownership_target="DEV",
            run_id="acceptance-denied",
        )
        raise AssertionError("unauthorized campaign must not run")
    except PermissionError:
        pass
    assert (tmp_path / "runs").exists() is False
