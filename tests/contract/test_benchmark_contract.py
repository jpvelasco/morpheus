"""Contract tests: benchmark entities, reducers, and durable store (BENCH-002, BENCH-003)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from morpheus.core.benchmark import (
    BenchmarkError,
    BenchmarkSample,
    CampaignDeclaration,
    RunIdentity,
    summarize_samples,
)
from morpheus.core.benchstore import BenchmarkStore, CampaignRun, StoreManifest


def make_samples(run_id: str = "run-1", count: int = 4) -> tuple[BenchmarkSample, ...]:
    return tuple(
        BenchmarkSample(
            run_id=run_id,
            started_at=datetime(2026, 8, 1, 12, 0, index, tzinfo=UTC),
            sequence_index=index,
            duration_seconds=1.0,
            ttft_seconds=0.1 * (index + 1),
            tokens_per_second=10.0 + index,
            generated_tokens=32,
        )
        for index in range(count)
    )


def make_identity() -> RunIdentity:
    return RunIdentity(
        machine_id="fixture-machine",
        model_id="qwen2.5-7b-instruct",
        model_revision="v0.1",
        quantization="q8_0",
        engine_id="llama.cpp",
        engine_version="0.1.0",
        benchmark_revision="bench-2026.2",
        context_window=8192,
        warmup_samples=4,
    )


def make_declaration() -> CampaignDeclaration:
    return CampaignDeclaration(
        name="contract-campaign",
        campaign_type="coding",
        benchmark_revision="bench-2026.2",
        duration_seconds=120,
        concurrency=2,
        ownership_target="DEV",
        workload_parameters=(("temperature", "0.0"),),
        resource_envelope=(("ram", 8_589_934_592), ("vram", 12_884_901_888)),
        request_shape=(("max_tokens", "1024"),),
        stop_conditions=(("max_errors", 3), ("target_samples", 500)),
    )


def test_campaign_declaration_contract_round_trip() -> None:
    record = make_declaration()
    assert CampaignDeclaration.from_dict(record.to_dict()) == record
    assert dict(record.stop_conditions)["max_errors"] == 3
    assert dict(record.resource_envelope)["vram"] == 12_884_901_888


def test_run_identity_contract_round_trip() -> None:
    record = make_identity()
    assert RunIdentity.from_dict(record.to_dict()) == record
    assert record.context_window == 8192
    assert record.warmup_samples == 4


def test_summary_requires_declared_statistic() -> None:
    summary = summarize_samples("run-1", make_samples(), statistic="p95")
    assert summary.statistic == "p95"
    assert summary.sample_count == 4
    assert summary.ttft_seconds == pytest.approx(0.4)
    assert summary.run_variation


def test_store_persists_identity_and_summary(tmp_path) -> None:
    store = BenchmarkStore(tmp_path)
    store.initialize()
    store.store_samples(make_samples())
    store.store_summary(summarize_samples("run-1", make_samples()))
    assert (
        store.load_summary("run-1").to_dict()
        == summarize_samples("run-1", make_samples()).to_dict()
    )


def test_store_backup_restore_preserves_manifest(tmp_path) -> None:
    store = BenchmarkStore(tmp_path / "store")
    store.initialize()
    store.store_samples(make_samples())
    store.backup(tmp_path / "backup")
    restored = BenchmarkStore.restore(tmp_path / "backup", tmp_path / "restored")
    manifest = StoreManifest.from_dict(restored._read_json(restored.root / "manifest.json"))
    assert manifest.schema_version == 1
    assert restored.load_samples("run-1") == store.load_samples("run-1")


def test_rejects_tampered_raw_content(tmp_path) -> None:
    store = BenchmarkStore(tmp_path)
    store.initialize()
    store.store_raw_lines(("payload",))
    from morpheus.core.benchstore import sha256_hex

    target = tmp_path / "raw" / sha256_hex(b"payload")
    target.write_text("changed", encoding="utf-8")
    with pytest.raises(BenchmarkError, match="collision"):
        store.store_raw_lines(("payload",))


def test_invalid_documents_rejected_at_boundary(tmp_path) -> None:
    store = BenchmarkStore(tmp_path)
    store.initialize()
    store.store_samples(make_samples())
    with pytest.raises(BenchmarkError):
        store.load_samples("unknown-run")


def test_store_lists_runs_most_recent_first_and_bounded(tmp_path) -> None:
    store = BenchmarkStore(tmp_path)
    store.initialize()
    for index in range(3):
        store.store_run(
            CampaignRun(
                run_id=f"run-{index}",
                declaration=make_declaration(),
                identity=make_identity(),
                started_at=datetime(2026, 8, 1, 12, index, tzinfo=UTC),
                ended_at=datetime(2026, 8, 1, 12, index + 1, tzinfo=UTC),
                status="completed",
            )
        )
    assert [run.run_id for run in store.list_runs(limit=10)] == ["run-2", "run-1", "run-0"]
    assert [run.run_id for run in store.list_runs(limit=2)] == ["run-2", "run-1"]
    with pytest.raises(BenchmarkError):
        store.list_runs(limit=101)
