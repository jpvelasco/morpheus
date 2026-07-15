from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class TelemetryEvent:
    correlation_id: str
    model_requested: str
    started_at: float
    model_reported: str | None = None
    first_byte_seconds: float | None = None
    completed_seconds: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    finish_reason: str | None = None
    outcome: str = "in_progress"

    @classmethod
    def new(cls, *, correlation_id: str, model_requested: str, started_at: float) -> TelemetryEvent:
        if not correlation_id or not model_requested:
            raise ValueError("telemetry identity fields cannot be empty")
        return cls(
            correlation_id=correlation_id,
            model_requested=model_requested,
            started_at=started_at,
        )

    def observe_first_byte(self, now: float) -> None:
        if self.first_byte_seconds is None:
            self.first_byte_seconds = max(0.0, now - self.started_at)

    def complete(self, now: float, *, outcome: str = "success") -> None:
        self.completed_seconds = max(0.0, now - self.started_at)
        self.outcome = outcome

    def as_record(self) -> dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "model_requested": self.model_requested,
            "model_reported": self.model_reported,
            "started_at": self.started_at,
            "first_byte_seconds": self.first_byte_seconds,
            "completed_seconds": self.completed_seconds,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "finish_reason": self.finish_reason,
            "outcome": self.outcome,
        }
