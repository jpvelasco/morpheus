from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from morpheus.core.metrics_history import (
    MAX_BUCKETS,
    MetricBucket,
    MetricSample,
    MetricsHistoryError,
    freshness_state,
    gaps,
    retention_cutoff,
    rollup,
    unit_for_signal,
)

NOW = "2026-08-15T12:00:00+00:00"


def sample(offset_seconds: int, *, signal: str = "gpu_cache_usage", value: float) -> MetricSample:
    observed_at = (
        datetime(2026, 8, 15, 12, tzinfo=UTC) + timedelta(seconds=offset_seconds)
    ).isoformat()
    return MetricSample(observed_at=observed_at, source="vllm", signal=signal, value=value)


def test_unit_catalog_has_explicit_units_for_expected_signals() -> None:
    assert unit_for_signal("gpu_cache_usage") == "percent"
    assert unit_for_signal("memory_available_bytes") == "bytes"
    assert unit_for_signal("requests_running") == "count"
    assert unit_for_signal("prompt_tokens_total") == "tokens"


def test_unit_catalog_defaults_unknown_signals_to_count() -> None:
    assert unit_for_signal("some_novel_signal") == "count"


def test_sample_rejects_naive_timestamp() -> None:
    with pytest.raises(MetricsHistoryError):
        MetricSample(
            observed_at="2026-08-15T12:00:00",
            source="vllm",
            signal="gpu_cache_usage",
            value=42.0,
        )


def test_sample_rejects_non_finite_value() -> None:
    with pytest.raises(MetricsHistoryError):
        sample(0, value=math.inf)


def test_sample_rejects_malformed_source_and_signal() -> None:
    with pytest.raises(MetricsHistoryError):
        MetricSample(observed_at=NOW, source="bad source!", signal="gpu_cache_usage", value=1.0)
    with pytest.raises(MetricsHistoryError):
        MetricSample(observed_at=NOW, source="vllm", signal="", value=1.0)


def test_rollup_aggregates_per_window_with_all_statistics() -> None:
    samples = [
        sample(0, value=10.0),
        sample(1, value=20.0),
        sample(2, value=30.0),
        sample(61, value=5.0),
        sample(119, value=7.0),
    ]
    buckets = rollup(
        samples,
        window_seconds=60,
        start="2026-08-15T11:59:30+00:00",
        end="2026-08-15T12:02:00+00:00",
    )
    assert len(buckets) == 2
    first, second = buckets
    assert first.start == "2026-08-15T12:00:00+00:00"
    assert first.end == "2026-08-15T12:01:00+00:00"
    assert first.count == 3
    assert first.min == 10.0
    assert first.max == 30.0
    assert first.mean == 20.0
    assert first.p50 == 20.0
    assert first.p95 == 30.0
    assert second.count == 2
    assert second.min == 5.0
    assert second.max == 7.0
    assert second.mean == 6.0
    assert second.p95 == 7.0


def test_rollup_single_sample_bucket_reports_its_value_everywhere() -> None:
    buckets = rollup(
        [sample(0, value=42.0)],
        window_seconds=60,
        start="2026-08-15T12:00:00+00:00",
        end="2026-08-15T12:01:00+00:00",
    )
    assert len(buckets) == 1
    bucket = buckets[0]
    assert (bucket.min, bucket.max, bucket.mean, bucket.p50, bucket.p95) == (42.0,) * 5


def test_rollup_ignores_samples_outside_range() -> None:
    buckets = rollup(
        [sample(-10, value=1.0), sample(0, value=2.0), sample(200, value=3.0)],
        window_seconds=60,
        start="2026-08-15T12:00:00+00:00",
        end="2026-08-15T12:01:00+00:00",
    )
    assert len(buckets) == 1
    assert buckets[0].count == 1
    assert buckets[0].min == 2.0


def test_rollup_normalizes_sample_timezones_into_utc_windows() -> None:
    offset_plus_two = MetricSample(
        observed_at="2026-08-15T14:00:30+02:00",
        source="host",
        signal="utilization_percent",
        value=55.0,
    )
    buckets = rollup(
        [offset_plus_two],
        window_seconds=60,
        start="2026-08-15T12:00:00+00:00",
        end="2026-08-15T12:01:00+00:00",
    )
    assert len(buckets) == 1
    assert buckets[0].min == 55.0


def test_rollup_rejects_ranges_exceeding_max_buckets() -> None:
    samples = [sample(0, value=1.0)]
    with pytest.raises(MetricsHistoryError):
        rollup(
            samples,
            window_seconds=60,
            start="2026-08-15T12:00:00+00:00",
            end="2026-08-15T14:00:00+00:00",
            max_buckets=60,
        )


def test_rollup_rejects_invalid_window_and_range() -> None:
    with pytest.raises(MetricsHistoryError):
        rollup([], window_seconds=0, start=NOW, end=NOW)
    with pytest.raises(MetricsHistoryError):
        rollup(
            [],
            window_seconds=60,
            start="2026-08-15T12:01:00+00:00",
            end="2026-08-15T12:00:00+00:00",
        )
    with pytest.raises(MetricsHistoryError):
        rollup([], window_seconds=60, start="not-a-time", end=NOW)


def test_gaps_reports_missing_windows_in_order() -> None:
    missing = gaps(
        [sample(0, value=1.0), sample(181, value=2.0)],
        window_seconds=60,
        start="2026-08-15T12:00:00+00:00",
        end="2026-08-15T12:04:00+00:00",
    )
    assert missing == (
        ("2026-08-15T12:01:00+00:00", "2026-08-15T12:02:00+00:00"),
        ("2026-08-15T12:02:00+00:00", "2026-08-15T12:03:00+00:00"),
    )


def test_gaps_empty_when_windows_contiguous() -> None:
    missing = gaps(
        [sample(0, value=1.0), sample(60, value=2.0), sample(120, value=3.0)],
        window_seconds=60,
        start="2026-08-15T12:00:00+00:00",
        end="2026-08-15T12:03:00+00:00",
    )
    assert missing == ()


def test_rollup_handles_unsorted_samples() -> None:
    buckets = rollup(
        [sample(50, value=3.0), sample(0, value=1.0), sample(30, value=2.0)],
        window_seconds=60,
        start="2026-08-15T12:00:00+00:00",
        end="2026-08-15T12:02:00+00:00",
    )
    assert len(buckets) == 1
    assert (buckets[0].count, buckets[0].min, buckets[0].max, buckets[0].mean) == (3, 1.0, 3.0, 2.0)


def test_freshness_states() -> None:
    now = "2026-08-15T12:00:00+00:00"
    assert freshness_state(None, now=now) == "unavailable"
    assert freshness_state("2026-08-15T11:59:30+00:00", now=now) == "fresh"
    assert freshness_state("2026-08-15T11:57:00+00:00", now=now) == "stale"
    assert freshness_state("2026-08-15T11:57:00+00:00", now=now, grace_seconds=300) == "fresh"
    with pytest.raises(MetricsHistoryError):
        freshness_state(NOW, now=now, grace_seconds=-1)


def test_retention_cutoff_moves_now_back_by_days() -> None:
    cutoff = retention_cutoff(NOW, retention_days=7)
    expected = (datetime(2026, 8, 8, 12, tzinfo=UTC)).isoformat()
    assert cutoff == expected


def test_retention_cutoff_rejects_out_of_bounds_days() -> None:
    with pytest.raises(MetricsHistoryError):
        retention_cutoff(NOW, retention_days=0)
    with pytest.raises(MetricsHistoryError):
        retention_cutoff(NOW, retention_days=366)


def test_metric_bucket_rejects_nonsense() -> None:
    with pytest.raises(MetricsHistoryError):
        MetricBucket(
            start="x", end="y", count=-1, min=None, max=None, mean=None, p50=None, p95=None
        )


def test_max_buckets_constant_is_bounded() -> None:
    assert 1 <= MAX_BUCKETS <= 10_000
