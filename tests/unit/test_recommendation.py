"""Unit tests: immutable recommendation records and store (SEL-004, SEL-005)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from morpheus.core.paths import OwnedPathError
from morpheus.core.ranking import (
    Contribution,
    RankedCandidate,
)
from morpheus.core.recommendation import (
    RecommendationError,
    RecommendationRecord,
    RecommendationStore,
    build_recommendation,
    canonical_json,
)
from morpheus.core.solver import (
    Candidate,
    ConstraintViolation,
)
from morpheus.core.workload import SEED_PROFILES, OperatorConstraints

LLAMA = Candidate(
    model_id="llama-3.1-8b-instruct",
    quantization="q8_0",
    engine_id="llama.cpp",
    context_window=8192,
    concurrency=1,
)
QWEN = Candidate(
    model_id="qwen2.5-7b-instruct",
    quantization="q8_0",
    engine_id="llama.cpp",
    context_window=8192,
    concurrency=1,
)

PROFILE = SEED_PROFILES[0]
BUDGET = {"ram_bytes": 64 * 1024**3, "storage_bytes": 500 * 1024**3, "accelerator": "cpu"}
VIOLATIONS = (ConstraintViolation("accelerator", "engine vllm requires cuda"),)

RANKED = (
    RankedCandidate(
        candidate=LLAMA,
        score=0.42,
        contributions=(
            Contribution(
                metric="decode_throughput",
                weight=0.1,
                calibrated=0.5,
                effective_confidence=1.0,
                contribution=0.5,
                comparability="comparable",
            ),
        ),
        summary="strongest: decode_throughput",
    ),
    RankedCandidate(
        candidate=QWEN,
        score=0.31,
        contributions=(
            Contribution(
                metric="decode_throughput",
                weight=0.1,
                calibrated=0.3,
                effective_confidence=1.0,
                contribution=0.3,
                comparability="comparable",
            ),
        ),
        summary="strongest: decode_throughput",
    ),
)
EXCLUDED = ((Candidate("qwen2.5-7b-instruct", "f16", "vllm", 8192, 1), VIOLATIONS),)


def record(created_at: datetime | None = None) -> RecommendationRecord:
    return build_recommendation(
        profile=PROFILE,
        operator=None,
        reference_machine_id="ubuntu-1",
        budget=BUDGET,
        ranked=RANKED,
        excluded=EXCLUDED,
        created_at=created_at,
    )


class TestRecord:
    def test_record_id_is_content_digest(self) -> None:
        import hashlib

        item = record()
        assert len(item.record_id) == 64
        payload = canonical_json(item.content_dict()).encode("utf-8")
        assert item.record_id == hashlib.sha256(payload).hexdigest()

    def test_identical_inputs_produce_identical_records(self) -> None:
        first = record(created_at=datetime(2026, 8, 1, tzinfo=UTC))
        second = record(created_at=datetime(2026, 8, 1, tzinfo=UTC))
        assert first == second
        assert first.to_dict() == second.to_dict()

    def test_round_trip(self) -> None:
        item = record()
        assert RecommendationRecord.from_dict(item.to_dict()) == item

    def test_requires_at_least_one_ranked_tuple(self) -> None:
        with pytest.raises(RecommendationError):
            build_recommendation(
                profile=PROFILE,
                operator=None,
                reference_machine_id="ubuntu-1",
                budget=BUDGET,
                ranked=(),
                excluded=(),
            )

    def test_naive_timestamp_is_rejected(self) -> None:
        with pytest.raises(RecommendationError):
            RecommendationRecord(
                record_id="a" * 64,
                created_at=datetime(2026, 8, 1),  # noqa: DTZ001 - intentionally naive
                profile=PROFILE,
                operator=None,
                reference_machine_id="ubuntu-1",
                budget=BUDGET,
                ranked=RANKED,
                excluded=(),
                summary="x",
            )

    def test_summary_reports_exclusions(self) -> None:
        assert "excluded: 1 tuples" in record().summary
        assert "exclusion reasons: accelerator" in record().summary

    def test_operator_caps_round_trip(self) -> None:
        item = build_recommendation(
            profile=PROFILE,
            operator=OperatorConstraints(max_context=8192, allowed_engines=("llama.cpp",)),
            reference_machine_id="ubuntu-1",
            budget=BUDGET,
            ranked=RANKED,
            excluded=(),
        )
        assert RecommendationRecord.from_dict(item.to_dict()) == item


class TestCanonicalJson:
    def test_sorted_keys_stable(self) -> None:
        first = canonical_json({"b": 1, "a": 2, "c": {"z": 1, "y": 2}})
        second = canonical_json({"c": {"y": 2, "z": 1}, "a": 2, "b": 1})
        assert first == second

    def test_indent_is_stable(self) -> None:
        assert canonical_json({"x": [1, 2]}).endswith("\n")


class TestStore:
    def test_store_and_load_round_trip(self, tmp_path: Path) -> None:
        store = RecommendationStore(tmp_path / "recs")
        store.initialize()
        item = record()
        digest = store.store_record(item)
        assert digest == item.record_id
        assert store.load_record(digest) == item

    def test_store_is_idempotent(self, tmp_path: Path) -> None:
        store = RecommendationStore(tmp_path / "recs")
        store.initialize()
        item = record()
        store.store_record(item)
        store.store_record(item)
        manifest = json.loads((tmp_path / "recs" / "manifest.json").read_text())
        assert manifest["entries"] == [item.record_id]

    def test_latest_returns_most_recent_entry(self, tmp_path: Path) -> None:
        store = RecommendationStore(tmp_path / "recs")
        store.initialize()
        older = record(created_at=datetime(2026, 8, 1, tzinfo=UTC))
        newer = record(created_at=datetime(2026, 8, 2, tzinfo=UTC))
        store.store_record(older)
        store.store_record(newer)
        assert store.latest() == newer

    def test_latest_empty_store_is_none(self, tmp_path: Path) -> None:
        store = RecommendationStore(tmp_path / "recs")
        store.initialize()
        assert store.latest() is None

    def test_rejects_symlinked_document(self, tmp_path: Path) -> None:
        import os

        if not hasattr(os, "symlink"):
            pytest.skip("os.symlink unavailable")
        store = RecommendationStore(tmp_path / "recs")
        store.initialize()
        item = record()
        store.store_record(item)
        target = tmp_path / "recs" / "raw" / item.record_id
        try:
            target.unlink()
            os.symlink("../manifest.json", target, target_is_directory=False)
        except OSError:
            pytest.skip("symlink creation not permitted")
        with pytest.raises(OwnedPathError, match="symbolic link"):
            store.load_record(item.record_id)

    def test_rejects_bad_record_id(self, tmp_path: Path) -> None:
        store = RecommendationStore(tmp_path / "recs")
        store.initialize()
        with pytest.raises(RecommendationError):
            store.load_record("not-hex")

    def test_backup_and_restore(self, tmp_path: Path) -> None:
        store = RecommendationStore(tmp_path / "recs")
        store.initialize()
        item = record()
        store.store_record(item)
        store.backup(tmp_path / "backup")
        restored = RecommendationStore.restore(tmp_path / "backup", tmp_path / "recs2")
        assert restored.latest() == item

    def test_restore_rejects_non_store(self, tmp_path: Path) -> None:
        (tmp_path / "backup").mkdir()
        with pytest.raises(RecommendationError):
            RecommendationStore.restore(tmp_path / "backup", tmp_path / "recs2")
