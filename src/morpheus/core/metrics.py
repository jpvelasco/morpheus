from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MetricsSnapshot:
    values: dict[str, float]
    available_signals: frozenset[str]
    missing_signals: frozenset[str]
