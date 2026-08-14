"""Unit tests: authorized campaign runner (BENCH-005)."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime

import pytest

from morpheus.core.benchmark import BenchmarkSample, CampaignDeclaration, RunIdentity
from morpheus.core.benchstore import BenchmarkStore
from morpheus.core.campaign import (
    CampaignAuthorizationError,
    CampaignCancelled,
    CampaignRunContext,
    authorization_token,
    run_campaign,
)


def declaration(**overrides) -> CampaignDeclaration:
    fields = {
        "name": "fixture-campaign",
        "campaign_type": "speed",
        "benchmark_revision": "bench-2026.2",
        "duration_seconds": 60,
        "concurrency": 1,
        "ownership_target": "DEV",
        "stop_conditions": (("target_samples", 10),),
    }
    fields.update(overrides)
    return CampaignDeclaration(**fields)


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


def sample_for(index: int, run_id: str) -> BenchmarkSample:
    return BenchmarkSample(
        run_id=run_id,
        started_at=datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC),
        sequence_index=index,
        duration_seconds=0.5,
        ttft_seconds=0.1,
        tokens_per_second=40.0,
        generated_tokens=32,
    )


def workload(counter: list[int] | None = None):
    def work(ctx: CampaignRunContext, index: int) -> BenchmarkSample:
        if counter is not None:
            counter.append(index)
        return sample_for(index, ctx.run_id)

    return work


class TestAuthorization:
    def test_requires_gate_token(self, tmp_path) -> None:
        with pytest.raises(CampaignAuthorizationError, match="explicit authority"):
            run_campaign(
                declaration(),
                identity(),
                workload(),
                BenchmarkStore(tmp_path),
                authorized=False,
                ownership_target="DEV",
            )

    def test_wrong_token_rejected(self, tmp_path) -> None:
        with pytest.raises(CampaignAuthorizationError, match="explicit authority"):
            run_campaign(
                declaration(),
                identity(),
                workload(),
                BenchmarkStore(tmp_path),
                authorized="not-the-token",
                ownership_target="DEV",
            )

    def test_ownership_target_must_match(self, tmp_path) -> None:
        with pytest.raises(CampaignAuthorizationError, match="mismatch"):
            run_campaign(
                declaration(),
                identity(),
                workload(),
                BenchmarkStore(tmp_path),
                authorized=authorization_token(),
                ownership_target="HOST-RO",
            )


class TestLimits:
    def test_target_samples_completes(self, tmp_path) -> None:
        store = BenchmarkStore(tmp_path)
        run = run_campaign(
            declaration(),
            identity(),
            workload(),
            store,
            authorized=authorization_token(),
            ownership_target="DEV",
            run_id="run-complete",
        )
        assert run.status == "completed"
        assert len(store.load_samples("run-complete")) == 10
        assert run.checkpoint == ()

    def test_max_errors_fails(self, tmp_path) -> None:
        def failing(ctx: CampaignRunContext, index: int) -> BenchmarkSample:
            raise RuntimeError("boom")

        store = BenchmarkStore(tmp_path)
        run = run_campaign(
            declaration(stop_conditions=(("max_errors", 2), ("target_samples", 10))),
            identity(),
            failing,
            store,
            authorized=authorization_token(),
            ownership_target="DEV",
            run_id="run-fail",
        )
        assert run.status == "failed"
        assert len(run.errors) == 2

    def test_runtime_deadline_cancels(self, tmp_path) -> None:
        def slow(ctx: CampaignRunContext, index: int) -> BenchmarkSample:
            time.sleep(0.05)
            return sample_for(index, ctx.run_id)

        store = BenchmarkStore(tmp_path)
        run = run_campaign(
            declaration(stop_conditions=(("max_runtime_seconds", 1), ("target_samples", 1_000))),
            identity(),
            slow,
            store,
            authorized=authorization_token(),
            ownership_target="DEV",
            run_id="run-deadline",
        )
        assert run.status == "cancelled"
        assert dict(run.checkpoint)["sequence_index"] < 1_000

    def test_stop_event_cancels(self, tmp_path) -> None:
        event = threading.Event()
        counter: list[int] = []

        def interruptible(ctx: CampaignRunContext, index: int) -> BenchmarkSample:
            if index == 3:
                event.set()
            counter.append(index)
            return sample_for(index, ctx.run_id)

        store = BenchmarkStore(tmp_path)
        run = run_campaign(
            declaration(stop_conditions=(("target_samples", 100),)),
            identity(),
            interruptible,
            store,
            authorized=authorization_token(),
            ownership_target="DEV",
            run_id="run-stop",
            stop_event=event,
        )
        assert run.status == "cancelled"
        assert len(counter) == 4
        assert dict(run.checkpoint)["sequence_index"] == 4

    def test_workload_cancellation(self, tmp_path) -> None:
        def cancel(ctx: CampaignRunContext, index: int) -> BenchmarkSample:
            if index == 2:
                raise CampaignCancelled("operator stopped")
            return sample_for(index, ctx.run_id)

        store = BenchmarkStore(tmp_path)
        run = run_campaign(
            declaration(stop_conditions=(("target_samples", 100),)),
            identity(),
            cancel,
            store,
            authorized=authorization_token(),
            ownership_target="DEV",
            run_id="run-cancel-raise",
        )
        assert run.status == "cancelled"
        assert len(store.load_samples("run-cancel-raise")) == 2


class TestCheckpointResume:
    def test_interrupted_run_is_resumable(self, tmp_path) -> None:
        event = threading.Event()
        counter: list[int] = []

        def interruptible(ctx: CampaignRunContext, index: int) -> BenchmarkSample:
            counter.append(index)
            if index == 4:
                event.set()
            return sample_for(index, ctx.run_id)

        store = BenchmarkStore(tmp_path)
        first = run_campaign(
            declaration(stop_conditions=(("target_samples", 10),)),
            identity(),
            interruptible,
            store,
            authorized=authorization_token(),
            ownership_target="DEV",
            run_id="run-resume",
            stop_event=event,
        )
        assert first.status == "cancelled"

        resumed = run_campaign(
            declaration(stop_conditions=(("target_samples", 10),)),
            identity(),
            interruptible,
            store,
            authorized=authorization_token(),
            ownership_target="DEV",
            run_id="run-resume",
        )
        assert resumed.status == "completed"
        assert len(store.load_samples("run-resume")) == 10
        assert len(counter) == 10
        assert counter[:5] == [0, 1, 2, 3, 4]
        assert sorted(set(counter)) == list(range(10))

    def test_completed_run_not_rerun(self, tmp_path) -> None:
        store = BenchmarkStore(tmp_path)
        run_campaign(
            declaration(stop_conditions=(("target_samples", 5),)),
            identity(),
            workload(),
            store,
            authorized=authorization_token(),
            ownership_target="DEV",
            run_id="run-done",
        )
        with pytest.raises(ValueError, match="already terminal"):
            run_campaign(
                declaration(stop_conditions=(("target_samples", 5),)),
                identity(),
                workload(),
                store,
                authorized=authorization_token(),
                ownership_target="DEV",
                run_id="run-done",
            )

    def test_checkpoint_persisted_every_ten(self, tmp_path) -> None:
        event = threading.Event()

        def long_run(ctx: CampaignRunContext, index: int) -> BenchmarkSample:
            if index == 14:
                event.set()
            return sample_for(index, ctx.run_id)

        store = BenchmarkStore(tmp_path)
        run = run_campaign(
            declaration(stop_conditions=(("target_samples", 1_000),)),
            identity(),
            long_run,
            store,
            authorized=authorization_token(),
            ownership_target="DEV",
            run_id="run-checkpoint",
            stop_event=event,
        )
        assert run.status == "cancelled"
        assert dict(run.checkpoint)["completed_samples"] == 15


class TestCleanup:
    def test_no_live_work_after_stop(self, tmp_path) -> None:
        event = threading.Event()
        counter: list[int] = []

        def slow(ctx: CampaignRunContext, index: int) -> BenchmarkSample:
            counter.append(index)
            if index == 5:
                event.set()
            time.sleep(0.02)
            return sample_for(index, ctx.run_id)

        store = BenchmarkStore(tmp_path)
        run_campaign(
            declaration(stop_conditions=(("target_samples", 100),)),
            identity(),
            slow,
            store,
            authorized=authorization_token(),
            ownership_target="DEV",
            run_id="run-idle",
            stop_event=event,
        )
        time.sleep(0.2)
        size = len(counter)
        time.sleep(0.2)
        assert len(counter) == size

    def test_failure_cleanup_keeps_documents(self, tmp_path) -> None:
        def failing(ctx: CampaignRunContext, index: int) -> BenchmarkSample:
            raise RuntimeError("boom")

        store = BenchmarkStore(tmp_path)
        run = run_campaign(
            declaration(stop_conditions=(("max_errors", 1),)),
            identity(),
            failing,
            store,
            authorized=authorization_token(),
            ownership_target="DEV",
            run_id="run-clean",
        )
        assert store.load_run("run-clean").status == run.status == "failed"
