"""Contract tests: checksummed History import (BENCH-003)."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

from morpheus.core.benchstore import BenchmarkStore
from morpheus.core.history_import import HistoryImportContext, import_history

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "History"
GOLDEN = (
    "speed",
    "coding",
    "tools",
    "long-context",
    "context-bump",
    "mtp",
    "supporting-software-before",
    "supporting-software-after",
)


def context() -> HistoryImportContext:
    return HistoryImportContext(
        machine_id="fixture-machine",
        benchmark_revision="bench-2026.2",
        ownership_target="DEV",
    )


def _import_fixture(store: BenchmarkStore, name: str):
    raw = (FIXTURES / f"{name}.jsonl").read_text(encoding="utf-8")
    return import_history(StringIO(raw), store, context())


@pytest.mark.parametrize("name", GOLDEN)
def test_history_shape_imports_without_limitations(tmp_path, name: str) -> None:
    store = BenchmarkStore(tmp_path / name)
    report = _import_fixture(store, name)
    assert report.limitations == ()
    assert report.lines_seen == report.lines_mapped
    assert len(report.run_ids) == 1
    samples = store.load_samples(report.run_ids[0])
    assert len(samples) == report.lines_mapped
    run = store.load_run(report.run_ids[0])
    assert run.declaration.ownership_target == "DEV"
    assert run.identity.machine_id == "fixture-machine"


def test_original_checksums_preserved(tmp_path) -> None:
    store = BenchmarkStore(tmp_path)
    report = _import_fixture(store, "speed")
    raw = (FIXTURES / "speed.jsonl").read_text(encoding="utf-8")
    for digest, line in zip(report.digests, raw.splitlines(), strict=False):
        assert store.read_raw(digest) == line


def test_import_is_reproducible_across_stores(tmp_path) -> None:
    raw = (FIXTURES / "coding.jsonl").read_text(encoding="utf-8")
    first = import_history(StringIO(raw), BenchmarkStore(tmp_path / "a"), context())
    second = import_history(StringIO(raw), BenchmarkStore(tmp_path / "b"), context())
    assert first.run_ids == second.run_ids
    assert first.digests == second.digests
    assert first.limitations == second.limitations


def test_missing_provenance_never_invented(tmp_path) -> None:
    store = BenchmarkStore(tmp_path)
    raw = (FIXTURES / "limitations.jsonl").read_text(encoding="utf-8")
    report = import_history(StringIO(raw), store, context())
    assert len(report.limitations) == len(raw.splitlines())
    assert report.lines_mapped == 0
    assert report.run_ids == ()
