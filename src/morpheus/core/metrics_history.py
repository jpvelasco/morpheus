from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

SIGNAL_UNITS: dict[str, str] = {
    "free_bytes": "bytes",
    "generation_tokens_total": "tokens",
    "gpu_cache_usage": "percent",
    "load_average_1m": "count",
    "memory_available_bytes": "bytes",
    "memory_used_bytes": "bytes",
    "prompt_tokens_total": "tokens",
    "request_success_total": "count",
    "requests_running": "count",
    "requests_waiting": "count",
    "utilization_percent": "percent",
}
DEFAULT_UNIT = "count"
MAX_BUCKETS = 240
MAX_RETENTION_DAYS = 365

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class MetricsHistoryError(ValueError):
    pass


def _bounded(value: str, what: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise MetricsHistoryError(f"invalid {what}: {value!r}")
    return value


def _parse_iso(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise MetricsHistoryError(f"invalid ISO timestamp: {value!r}") from error
    if parsed.tzinfo is None:
        raise MetricsHistoryError(f"timestamp must be timezone-aware: {value!r}")
    return parsed.astimezone(UTC)


def unit_for_signal(signal: str) -> str:
    return SIGNAL_UNITS.get(signal, DEFAULT_UNIT)


@dataclass(frozen=True, slots=True)
class MetricSample:
    observed_at: str
    source: str
    signal: str
    value: float

    def __post_init__(self) -> None:
        _parse_iso(self.observed_at)
        _bounded(self.source, "source")
        _bounded(self.signal, "signal")
        if not math.isfinite(self.value):
            raise MetricsHistoryError(f"metric value must be finite: {self.value!r}")


@dataclass(frozen=True, slots=True)
class MetricBucket:
    start: str
    end: str
    count: int
    min: float | None
    max: float | None
    mean: float | None
    p50: float | None
    p95: float | None

    def __post_init__(self) -> None:
        if self.count < 0:
            raise MetricsHistoryError("bucket count must be non-negative")


def _windows(
    start_iso: str,
    end_iso: str,
    *,
    window_seconds: int,
    max_buckets: int,
) -> tuple[tuple[datetime, datetime], ...]:
    if window_seconds < 1:
        raise MetricsHistoryError("window_seconds must be at least 1")
    start = _parse_iso(start_iso)
    end = _parse_iso(end_iso)
    if start >= end:
        raise MetricsHistoryError("range start must be before range end")
    step = timedelta(seconds=window_seconds)
    first_epoch_start = start - timedelta(seconds=start.timestamp() % window_seconds)
    count = math.ceil((end - first_epoch_start) / step)
    if count > max_buckets:
        raise MetricsHistoryError(
            f"range would produce {count} windows; the bound is {max_buckets} "
            "(reduce the range or increase the window)"
        )
    return tuple(
        (window_start, window_end)
        for index in range(count)
        for window_start in (first_epoch_start + index * step,)
        for window_end in (min(window_start + step, end),)
        if window_start < window_end
    )


def _statistic(ordered: list[float], quantile: float) -> float | None:
    if not ordered:
        return None
    index = min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]


def _aggregate(values: list[float], start: datetime, end: datetime) -> MetricBucket:
    ordered = sorted(values)
    return MetricBucket(
        start=start.isoformat(),
        end=end.isoformat(),
        count=len(values),
        min=ordered[0] if ordered else None,
        max=ordered[-1] if ordered else None,
        mean=sum(values) / len(values) if values else None,
        p50=_statistic(ordered, 0.50),
        p95=_statistic(ordered, 0.95),
    )


def _bucket_index(timestamp: datetime, first_epoch_start: datetime, window_seconds: int) -> int:
    return int((timestamp - first_epoch_start).total_seconds() // window_seconds)


def _membership(index: int, windows: tuple[tuple[datetime, datetime], ...]) -> bool:
    if not 0 <= index < len(windows):
        return False
    return windows[index][0] < windows[index][1]


def rollup(
    samples: Sequence[MetricSample],
    *,
    window_seconds: int,
    start: str,
    end: str,
    max_buckets: int = MAX_BUCKETS,
) -> tuple[MetricBucket, ...]:
    windows = _windows(start, end, window_seconds=window_seconds, max_buckets=max_buckets)
    buckets: dict[int, list[float]] = {}
    for item in samples:
        timestamp = _parse_iso(item.observed_at)
        index = _bucket_index(timestamp, windows[0][0], window_seconds)
        if _membership(index, windows):
            buckets.setdefault(index, []).append(item.value)
    return tuple(
        _aggregate(buckets[index], *windows[index]) for index in sorted(buckets) if buckets[index]
    )


def gaps(
    samples: Sequence[MetricSample],
    *,
    window_seconds: int,
    start: str,
    end: str,
    max_buckets: int = MAX_BUCKETS,
) -> tuple[tuple[str, str], ...]:
    windows = _windows(start, end, window_seconds=window_seconds, max_buckets=max_buckets)
    present = {
        _bucket_index(_parse_iso(item.observed_at), windows[0][0], window_seconds)
        for item in samples
        if _membership(
            _bucket_index(_parse_iso(item.observed_at), windows[0][0], window_seconds), windows
        )
    }
    return tuple(
        (windows[index][0].isoformat(), windows[index][1].isoformat())
        for index in range(len(windows))
        if index not in present
    )


def freshness_state(
    latest_observed_at: str | None,
    *,
    now: str,
    grace_seconds: int = 120,
) -> str:
    if grace_seconds < 0:
        raise MetricsHistoryError("grace_seconds must be non-negative")
    if latest_observed_at is None:
        return "unavailable"
    latest = _parse_iso(latest_observed_at)
    age = (_parse_iso(now) - latest).total_seconds()
    if age <= grace_seconds:
        return "fresh"
    return "stale"


def retention_cutoff(now: str, *, retention_days: int) -> str:
    if retention_days < 1 or retention_days > MAX_RETENTION_DAYS:
        raise MetricsHistoryError("retention_days must be between 1 and 365")
    return (_parse_iso(now) - timedelta(days=retention_days)).isoformat()
