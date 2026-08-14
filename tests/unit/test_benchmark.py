"""Unit tests: immutable benchmark entities, reducers, and durable store."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from morpheus.core.benchmark import (
    BenchmarkError,
    BenchmarkSample,
    BenchmarkSummary,
    CampaignDeclaration,
    RunIdentity,
    summarize_samples,
)
from morpheus.core.benchstore import (
    _MIGRATIONS,
    SCHEMA_VERSION,
    BenchmarkStore,
    StoreManifest,
    migrate,
    register_migration,
    sha256_hex,
)
from morpheus.core.paths import OwnedPathError


def sample(run_id: str, index: int, ttft: float, tps: float) -> BenchmarkSample:
    return BenchmarkSample(
        run_id=run_id,
        started_at=datetime(2026, 8, 1, 12, 0, index, tzinfo=UTC),
        sequence_index=index,
        duration_seconds=1.0,
        ttft_seconds=ttft,
        tokens_per_second=tps,
        generated_tokens=32,
    )


def identity(engine: str = "llama.cpp", machine_id: str = "fixture-machine") -> RunIdentity:
    return RunIdentity(
        machine_id=machine_id,
        model_id="llama-3.1-8b-instruct",
        model_revision="v0.1",
        quantization="q8_0",
        engine_id=engine,
        engine_version="0.1.0",
        benchmark_revision="bench-2026.2",
    )


def declaration() -> CampaignDeclaration:
    return CampaignDeclaration(
        name="fixture-campaign",
        campaign_type="speed",
        benchmark_revision="bench-2026.2",
        duration_seconds=60,
        concurrency=1,
        ownership_target="DEV",
    )


class TestCampaignDeclaration:
    def test_round_trip(self) -> None:
        assert CampaignDeclaration.from_dict(declaration().to_dict()) == declaration()

    @pytest.mark.parametrize("bad", ["", "two words", "upper!"])
    def test_rejects_unbounded_name(self, bad: str) -> None:
        with pytest.raises(BenchmarkError):
            CampaignDeclaration(
                name=bad,
                campaign_type="speed",
                benchmark_revision="bench-2026.2",
                duration_seconds=60,
                concurrency=1,
                ownership_target="DEV",
            )

    def test_rejects_unknown_type(self) -> None:
        with pytest.raises(BenchmarkError):
            CampaignDeclaration(
                name="ok",
                campaign_type="image-gen",
                benchmark_revision="bench-2026.2",
                duration_seconds=60,
                concurrency=1,
                ownership_target="DEV",
            )

    def test_rejects_unknown_resource(self) -> None:
        with pytest.raises(BenchmarkError):
            CampaignDeclaration(
                name="ok",
                campaign_type="speed",
                benchmark_revision="bench-2026.2",
                duration_seconds=60,
                concurrency=1,
                ownership_target="DEV",
                resource_envelope=(("flops", 8),),
            )

    def test_rejects_non_positive_limits(self) -> None:
        with pytest.raises(BenchmarkError):
            CampaignDeclaration(
                name="ok",
                campaign_type="speed",
                benchmark_revision="bench-2026.2",
                duration_seconds=0,
                concurrency=1,
                ownership_target="DEV",
            )


class TestRunIdentity:
    def test_round_trip(self) -> None:
        assert RunIdentity.from_dict(identity().to_dict()) == identity()

    def test_rejects_unbounded_machine(self) -> None:
        with pytest.raises(BenchmarkError):
            identity(machine_id="not bounded id")

    def test_defaults_round_trip(self) -> None:
        record = identity()
        assert record.model_digest is None
        assert record.warmup_samples == 0


class TestBenchmarkSample:
    def test_round_trip(self) -> None:
        record = sample("run-1", 1, 0.2, 42.0)
        assert BenchmarkSample.from_dict(record.to_dict()) == record

    def test_rejects_naive_timestamp(self) -> None:
        with pytest.raises(BenchmarkError):
            BenchmarkSample(
                run_id="run-1",
                started_at=datetime(2026, 8, 1, 12, 0),  # noqa: DTZ001
                sequence_index=0,
            )

    def test_rejects_negative_metrics(self) -> None:
        with pytest.raises(BenchmarkError):
            BenchmarkSample(
                run_id="run-1",
                started_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
                sequence_index=0,
                ttft_seconds=-0.1,
            )

    def test_accepts_error_sample_without_metrics(self) -> None:
        record = BenchmarkSample(
            run_id="run-1",
            started_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
            sequence_index=2,
            error="timeout",
        )
        assert record.error == "timeout"


class TestSummaries:
    def test_p50_statistic(self) -> None:
        samples = tuple(sample("run-1", i, float(i + 1) / 10.0, float(i + 1)) for i in range(5))
        summary = summarize_samples("run-1", samples, statistic="p50")
        assert summary.ttft_seconds == pytest.approx(0.3)
        assert summary.tokens_per_second == pytest.approx(3.0)
        assert summary.sample_count == 5

    def test_mean_and_p95(self) -> None:
        samples = tuple(sample("run-1", i, float(i + 1) / 10.0, float(i + 1)) for i in range(10))
        mean = summarize_samples("run-1", samples, statistic="mean")
        assert mean.ttft_seconds == pytest.approx(0.55)
        p95 = summarize_samples("run-1", samples, statistic="p95")
        assert p95.tokens_per_second == pytest.approx(10.0)

    def test_errors_excluded(self) -> None:
        failed = BenchmarkSample(
            run_id="run-1",
            started_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
            sequence_index=9,
            error="timeout",
        )
        summary = summarize_samples("run-1", (sample("run-1", 0, 0.2, 42.0), failed))
        assert summary.sample_count == 1
        assert summary.ttft_seconds == pytest.approx(0.2)

    def test_run_variation_reported(self) -> None:
        samples = tuple(sample("run-1", i, 0.2, float(10 + i)) for i in range(3))
        summary = summarize_samples("run-1", samples)
        variation = dict(summary.run_variation)
        assert "tokens_per_second" in variation
        assert variation["tokens_per_second"] > 0

    def test_single_sample_has_no_variation(self) -> None:
        summary = summarize_samples("run-1", (sample("run-1", 0, 0.2, 42.0),))
        assert summary.run_variation == ()

    def test_unknown_statistic_rejected(self) -> None:
        with pytest.raises(BenchmarkError):
            summarize_samples("run-1", (sample("run-1", 0, 0.2, 42.0),), statistic="avg")

    def test_summary_round_trip(self) -> None:
        summary = summarize_samples("run-1", (sample("run-1", 0, 0.2, 42.0),))
        assert BenchmarkSummary.from_dict(summary.to_dict()) == summary

    def test_regeneration_is_identical(self) -> None:
        samples = tuple(sample("run-1", i, 0.2, float(10 + i)) for i in range(5))
        original = summarize_samples("run-1", samples)
        regenerated = summarize_samples("run-1", samples, statistic="p50")
        assert regenerated.to_dict() == original.to_dict()


class TestBenchmarkStore:
    def test_initialize_writes_manifest(self, tmp_path) -> None:
        store = BenchmarkStore(tmp_path)
        store.initialize()
        manifest = StoreManifest.from_dict(store._read_json(tmp_path / "manifest.json"))
        assert manifest.schema_version == SCHEMA_VERSION
        assert (tmp_path / "raw").is_dir()

    def test_raw_lines_content_addressed(self, tmp_path) -> None:
        store = BenchmarkStore(tmp_path)
        store.initialize()
        digests = store.store_raw_lines(("line-one", "line-two", "line-one"))
        assert len(set(digests)) == 2
        assert digests[0] == sha256_hex(b"line-one")
        assert (tmp_path / "raw" / digests[0]).exists()
        assert store.read_raw(digests[0]) == "line-one"

    def test_raw_digest_collision_detected(self, tmp_path) -> None:
        store = BenchmarkStore(tmp_path)
        store.initialize()
        store.store_raw_lines(("line",))
        target = tmp_path / "raw" / sha256_hex(b"line")
        target.write_text("tampered", encoding="utf-8")
        with pytest.raises(BenchmarkError, match="collision"):
            store.store_raw_lines(("line",))

    def test_samples_round_trip(self, tmp_path) -> None:
        store = BenchmarkStore(tmp_path)
        store.initialize()
        samples = tuple(sample("run-1", i, 0.2, 42.0) for i in range(3))
        store.store_samples(samples)
        assert store.load_samples("run-1") == samples

    def test_summary_round_trip(self, tmp_path) -> None:
        store = BenchmarkStore(tmp_path)
        store.initialize()
        summary = summarize_samples("run-1", (sample("run-1", 0, 0.2, 42.0),))
        store.store_summary(summary)
        assert store.load_summary("run-1") == summary

    def test_load_missing_document(self, tmp_path) -> None:
        store = BenchmarkStore(tmp_path)
        store.initialize()
        with pytest.raises(BenchmarkError, match="missing"):
            store.load_samples("nope")

    def test_escapes_rejected(self, tmp_path) -> None:
        store = BenchmarkStore(tmp_path)
        store.initialize()
        with pytest.raises(OwnedPathError):
            store._path("../manifest.json")

    def test_backup_and_restore_round_trip(self, tmp_path) -> None:
        store = BenchmarkStore(tmp_path / "store")
        store.initialize()
        store.store_raw_lines(("line",))
        store.store_samples((sample("run-1", 0, 0.2, 42.0),))
        backup_dir = tmp_path / "backup"
        store.backup(backup_dir)
        assert (backup_dir / "raw").is_dir()
        restored = BenchmarkStore.restore(backup_dir, tmp_path / "restored")
        assert restored.load_samples("run-1") == store.load_samples("run-1")
        assert restored.read_raw(sha256_hex(b"line")) == "line"

    def test_backup_rejects_existing_destination(self, tmp_path) -> None:
        store = BenchmarkStore(tmp_path / "store")
        store.initialize()
        store.backup(tmp_path / "backup")
        with pytest.raises(BenchmarkError, match="already exists"):
            store.backup(tmp_path / "backup")

    def test_restore_rejects_non_backup(self, tmp_path) -> None:
        with pytest.raises(BenchmarkError, match="not a benchmark store backup"):
            BenchmarkStore.restore(tmp_path / "empty", tmp_path / "restored")

    def test_symlinked_document_rejected(self, tmp_path) -> None:
        import os

        if not hasattr(os, "symlink"):
            pytest.skip("os.symlink unavailable")
        store = BenchmarkStore(tmp_path)
        store.initialize()
        store.store_samples((sample("run-1", 0, 0.2, 42.0),))
        target = tmp_path / "samples" / "run-1.json"
        try:
            target.unlink()
            os.symlink("../manifest.json", target, target_is_directory=False)
        except OSError:
            pytest.skip("symlink creation not permitted")
        with pytest.raises(OwnedPathError, match="symbolic link"):
            store.load_samples("run-1")


class TestMigration:
    def test_v1_payload_passes_through(self, tmp_path) -> None:
        store = BenchmarkStore(tmp_path)
        store.initialize()
        samples = tuple(sample("run-1", 0, 0.2, 42.0) for i in range(2))
        store.store_samples(samples)
        payload = store._read_json(tmp_path / "samples" / "run-1.json")
        assert migrate(payload, SCHEMA_VERSION) == payload

    def test_registered_migration_applies(self, tmp_path) -> None:
        def add_marker(payload: dict) -> dict:
            payload["migrated"] = True
            return payload

        register_migration(0)(add_marker)
        migrated = migrate({"schema_version": 0, "samples": []}, 0)
        assert migrated["migrated"] is True
        _MIGRATIONS.clear()

    def test_missing_migration_raises(self) -> None:
        with pytest.raises(BenchmarkError, match="no migration"):
            migrate({"schema_version": 0, "samples": []}, 0)

    def test_migration_is_idempotent_chain(self) -> None:
        seen: list[int] = []

        def first(payload: dict) -> dict:
            seen.append(1)
            payload["v"] = 1
            return payload

        register_migration(0)(first)
        migrate({"schema_version": 0, "v": 0}, 0)
        migrate({"schema_version": 0, "v": 0}, 0)
        assert seen == [1, 1]
        _MIGRATIONS.clear()
