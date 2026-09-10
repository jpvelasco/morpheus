"""Bounded background metrics collection independent of GET routes (R5)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from morpheus.adapters.metrics.collector import collect_metrics
from morpheus.adapters.metrics.vllm import VllmMetricsAdapter
from morpheus.adapters.persistence.sqlite import SqliteStore
from morpheus.config import MorpheusSettings
from morpheus.core.metrics_history import retention_cutoff
from morpheus.ports.protocols import Clock

HostSnapshot = Callable[[], Awaitable[dict[str, Any]]]


class MetricsCollectorLoop:
    """Persist the typed signal registry on an interval, without a browser."""

    def __init__(
        self,
        *,
        settings: MorpheusSettings,
        clock: Clock,
        host_snapshot: HostSnapshot,
    ) -> None:
        self._settings = settings
        self._clock = clock
        self._host_snapshot = host_snapshot
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self.last_error: str | None = None
        self.last_count: int | None = None

    async def collect_once(self) -> int:
        observed_at = self._clock.utc_now().isoformat()
        host = await self._host_snapshot()
        engine = (
            VllmMetricsAdapter(metrics_url=self._settings.vllm_metrics_url)
            if self._settings.vllm_metrics_url
            else None
        )
        samples, _sources = await collect_metrics(engine=engine, host=host, observed_at=observed_at)
        store = SqliteStore(
            self._settings.data_dir / "morpheus.sqlite3",
            owned_root=self._settings.data_dir,
        )
        await store.initialize()
        if samples:
            await store.record_metric_samples(samples)
        await store.prune_metrics(
            before=retention_cutoff(
                observed_at, retention_days=self._settings.metrics_retention_days
            )
        )
        return len(samples)

    def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run())

    async def aclose(self) -> None:
        self._stop.set()
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                return

    async def _run(self) -> None:
        interval = max(1, self._settings.metrics_collection_interval_seconds)
        while not self._stop.is_set():
            try:
                self.last_count = await self.collect_once()
                self.last_error = None
            except Exception as error:
                self.last_error = f"{type(error).__name__}: {error}"
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except TimeoutError:
                continue
