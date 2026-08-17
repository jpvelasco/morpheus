"""Unit tests: checksummed History import with explicit limitation mapping."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

from morpheus.core.benchstore import BenchmarkStore
from morpheus.core.history_import import (
    HistoryImportContext,
    import_history,
    parse_history_line,
)
from morpheus.core.history_import import _line_digest as line_digest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "history"

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


@pytest.fixture()
def store(tmp_path) -> BenchmarkStore:
    return BenchmarkStore(tmp_path)


class TestParseHistoryLine:
    def test_valid_line(self) -> None:
        line, limitation = parse_history_line(
            '{"campaign": "speed", "model": "m", "engine": "e", "t": 1.5}'
        )
        assert limitation is None
        assert line is not None
        assert line.campaign == "speed"
        assert line.elapsed_seconds == 1.5

    def test_invalid_json(self) -> None:
        parsed, limitation = parse_history_line("not json")
        assert parsed is None
        assert "not valid JSON" in limitation or limitation is None

    def test_missing_required_fields(self) -> None:
        parsed, limitation = parse_history_line('{"campaign": "speed", "model": "m"}')
        assert parsed is None
        assert "missing required field(s)" in limitation or limitation is None

    def test_non_numeric_elapsed(self) -> None:
        parsed, limitation = parse_history_line(
            '{"campaign": "speed", "model": "m", "engine": "e", "t": "fast"}'
        )
        assert parsed is None
        assert "not numeric" in limitation or limitation is None

    def test_negative_metrics_rejected(self) -> None:
        parsed, limitation = parse_history_line(
            '{"campaign": "speed", "model": "m", "engine": "e", "t": 1.0, "ttft": -0.1}'
        )
        assert parsed is None
        assert "negative" in limitation or limitation is None

    def test_timestamp_parsed_as_utc(self) -> None:
        line, _ = parse_history_line(
            '{"campaign": "speed", "model": "m", "engine": "e", "t": 1.0,'
            ' "ts": "2026-07-01T10:00:00+02:00"}'
        )
        assert line is not None
        assert line.started_at is not None
        assert line.started_at.utcoffset().total_seconds() == 0

    def test_bad_timestamp_ignored(self) -> None:
        line, limitation = parse_history_line(
            '{"campaign": "speed", "model": "m", "engine": "e", "t": 1.0, "ts": "nope"}'
        )
        assert line is not None
        assert limitation is None
        assert line.started_at is None

    def test_config_pairs_mapped(self) -> None:
        line, _ = parse_history_line(
            '{"campaign": "tools", "model": "m", "engine": "e", "t": 1.0,'
            ' "config": [["tools", "enabled"]]}'
        )
        assert line is not None
        assert line.configuration == (("tools", "enabled"),)

    def test_error_line_kept(self) -> None:
        line, _ = parse_history_line(
            '{"campaign": "speed", "model": "m", "engine": "e", "t": 5.0, "error": "timeout"}'
        )
        assert line is not None
        assert line.error == "timeout"


class TestImportHistory:
    @pytest.mark.parametrize("name", GOLDEN)
    def test_golden_import(self, store: BenchmarkStore, name: str) -> None:
        raw = (FIXTURES / f"{name}.jsonl").read_text(encoding="utf-8")
        report = import_history(StringIO(raw), store, context())
        assert report.limitations == ()
        assert report.lines_seen == len(raw.splitlines())
        assert report.lines_mapped == len(raw.splitlines())
        assert report.digests == tuple(line_digest(line) for line in raw.splitlines())

    def test_golden_import_reproducible(self, store: BenchmarkStore, tmp_path) -> None:
        raw = (FIXTURES / "speed.jsonl").read_text(encoding="utf-8")
        first = import_history(StringIO(raw), store, context())
        second_store = BenchmarkStore(tmp_path / "second")
        second = import_history(StringIO(raw), second_store, context())
        assert first.run_ids == second.run_ids
        assert first.digests == second.digests

    def test_before_after_same_run_identity(self, store: BenchmarkStore) -> None:
        before = (FIXTURES / "supporting-software-before.jsonl").read_text(encoding="utf-8")
        after = (FIXTURES / "supporting-software-after.jsonl").read_text(encoding="utf-8")
        first = import_history(StringIO(before), store, context())
        second = import_history(StringIO(after), store, context())
        assert first.run_ids == second.run_ids

    def test_limitations_mapped_not_invented(self, store: BenchmarkStore) -> None:
        raw = (FIXTURES / "limitations.jsonl").read_text(encoding="utf-8")
        report = import_history(StringIO(raw), store, context())
        assert report.lines_seen == 6
        assert len(report.limitations) == 6
        assert any("not valid JSON" in item for item in report.limitations)
        assert any("missing required field(s): engine" in item for item in report.limitations)
        assert any("not numeric" in item for item in report.limitations)
        assert any("no timestamp" in item for item in report.limitations)
        assert any("unsupported campaign type" in item for item in report.limitations)
        assert report.lines_mapped == 0

    def test_source_never_rewritten(self, store: BenchmarkStore, tmp_path) -> None:
        raw = (FIXTURES / "speed.jsonl").read_text(encoding="utf-8")
        import_history(StringIO(raw), store, context())
        assert (FIXTURES / "speed.jsonl").read_text(encoding="utf-8") == raw

    def test_raw_lines_stored_content_addressed(self, store: BenchmarkStore) -> None:
        raw = (FIXTURES / "speed.jsonl").read_text(encoding="utf-8")
        report = import_history(StringIO(raw), store, context())
        for digest in report.digests:
            assert store.read_raw(digest) in raw.splitlines()

    def test_import_requires_bounded_context(self, store: BenchmarkStore) -> None:
        bad = HistoryImportContext(
            machine_id="not a bounded id",
            benchmark_revision="bench-2026.2",
            ownership_target="DEV",
        )
        with pytest.raises(ValueError):
            import_history(StringIO(""), store, bad)
