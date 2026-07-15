from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

from morpheus.core.health import Evidence
from morpheus.core.models import ModelIdentity


@dataclass(slots=True)
class FakeClock:
    now: datetime = datetime(2026, 1, 1, tzinfo=UTC)
    monotonic_value: float = 0.0

    def utc_now(self) -> datetime:
        return self.now

    def monotonic(self) -> float:
        return self.monotonic_value


@dataclass(slots=True)
class FakeInference:
    health_result: Evidence
    model_results: tuple[ModelIdentity, ...]
    chunks: list[bytes] = field(default_factory=list)

    async def health(self) -> Evidence:
        return self.health_result

    async def models(self) -> tuple[ModelIdentity, ...]:
        return self.model_results

    async def forward_chat(self, body: bytes) -> AsyncIterator[bytes]:
        del body
        for chunk in self.chunks:
            yield chunk
