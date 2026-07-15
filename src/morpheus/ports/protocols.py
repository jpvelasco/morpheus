from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from morpheus.core.health import Evidence
from morpheus.core.models import ModelIdentity


class Clock(Protocol):
    def utc_now(self) -> datetime: ...

    def monotonic(self) -> float: ...


class InferencePort(Protocol):
    async def health(self) -> Evidence: ...

    async def models(self) -> tuple[ModelIdentity, ...]: ...

    def forward_chat(self, body: bytes) -> AsyncIterator[bytes]: ...


class MetricsPort(Protocol):
    async def collect(self) -> MappingResult: ...


class HostTelemetryPort(Protocol):
    async def snapshot(self) -> dict[str, Any]: ...


class PersistencePort(Protocol):
    async def initialize(self) -> None: ...

    async def backup(self, destination: Path) -> Path: ...


type MappingResult = dict[str, float]
