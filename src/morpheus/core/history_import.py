"""Checksummed JSONL history import with explicit limitation mapping (BENCH-003).

Accepted line contract (history v1 shape): one JSON object per line with
``campaign``, ``model``, ``engine``, and ``t`` (elapsed seconds). Optional
``ts`` (RFC 3339 timestamp), ``ttft``, ``tps``, ``tokens``, ``error``, and
``config`` pairs. Source files are only ever read; every line keeps its own
sha256 checksum, and lines that cannot map to a normalized run are recorded as
limitations instead of being silently defaulted.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TextIO

from morpheus.core.benchmark import (
    CAMPAIGN_TYPES,
    BenchmarkSample,
    CampaignDeclaration,
    RunIdentity,
    bounded_identifier,
)
from morpheus.core.benchstore import BenchmarkStore, CampaignRun, sha256_hex

_REQUIRED = ("campaign", "model", "engine", "t")


@dataclass(frozen=True, slots=True)
class HistoryLine:
    original: str
    digest: str
    campaign: str
    model_id: str
    engine_id: str
    elapsed_seconds: float
    ttft_seconds: float | None = None
    tokens_per_second: float | None = None
    generated_tokens: int | None = None
    error: str | None = None
    started_at: datetime | None = None
    configuration: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class HistoryImportReport:
    lines_seen: int
    lines_mapped: int
    run_ids: tuple[str, ...]
    digests: tuple[str, ...]
    limitations: tuple[str, ...]


def _line_digest(line: str) -> str:
    return sha256_hex(line.encode("utf-8"))


def _limitation(reason: str, campaign: str, digest: str) -> str:
    return f"{reason} (campaign={campaign}, digest={digest[:12]})"


def _bounded_slug(value: str) -> str:
    cleaned = "".join(character if character.isalnum() else "-" for character in value.lower())
    return cleaned[:64].strip("-") or "unknown"


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def parse_history_line(line: str) -> tuple[HistoryLine | None, str | None]:
    """Parse one JSONL line, returning (line, limitation). Exactly one side is
    populated; the original text is never modified."""
    digest = _line_digest(line)
    try:
        payload: Any = json.loads(line)
    except json.JSONDecodeError:
        return None, _limitation("line is not valid JSON", "unknown", digest)
    if not isinstance(payload, dict):
        return None, _limitation("line is not a JSON object", "unknown", digest)
    missing = [key for key in _REQUIRED if key not in payload]
    if missing:
        return (
            None,
            _limitation(f"missing required field(s): {', '.join(missing)}", "unknown", digest),
        )
    campaign = str(payload["campaign"])
    model = str(payload["model"])
    engine = str(payload["engine"])
    try:
        elapsed = float(payload["t"])
    except (TypeError, ValueError):
        return None, _limitation("elapsed time is not numeric", campaign, digest)
    if elapsed < 0:
        return None, _limitation("negative elapsed time", campaign, digest)
    try:
        ttft = float(payload["ttft"]) if payload.get("ttft") is not None else None
        tps = float(payload["tps"]) if payload.get("tps") is not None else None
        tokens = int(payload["tokens"]) if payload.get("tokens") is not None else None
    except (TypeError, ValueError):
        return None, _limitation("metric field is not numeric", campaign, digest)
    if any(value is not None and value < 0 for value in (ttft, tps, tokens)):
        return None, _limitation("negative metric value", campaign, digest)
    error = str(payload["error"]) if payload.get("error") is not None else None
    config_payload = payload.get("config", [])
    configuration: tuple[tuple[str, str], ...] = ()
    if isinstance(config_payload, list):
        configuration = tuple(
            (str(key), str(value))
            for key, value in config_payload
            if isinstance(key, str) and isinstance(value, str)
        )
    return (
        HistoryLine(
            original=line,
            digest=digest,
            campaign=campaign,
            model_id=model,
            engine_id=engine,
            elapsed_seconds=elapsed,
            ttft_seconds=ttft,
            tokens_per_second=tps,
            generated_tokens=tokens,
            error=error,
            started_at=_parse_timestamp(payload.get("ts")),
            configuration=configuration,
        ),
        None,
    )


@dataclass(frozen=True, slots=True)
class HistoryImportContext:
    """Operator-declared provenance for an import session (never invented)."""

    machine_id: str
    benchmark_revision: str
    ownership_target: str
    duration_seconds: int = 3_600
    concurrency: int = 1
    model_revision: str | None = None
    quantization: str | None = None
    engine_version: str | None = None


def import_history(
    stream: TextIO,
    store: BenchmarkStore,
    context: HistoryImportContext,
) -> HistoryImportReport:
    """Import a History JSONL history into the store without rewriting it."""
    store.initialize()
    bounded_identifier(context.machine_id, "machine id")
    bounded_identifier(context.benchmark_revision, "benchmark revision")
    runs: dict[str, tuple[list[BenchmarkSample], RunIdentity, str]] = {}
    limitations: list[str] = []
    digests: list[str] = []
    raw_lines: list[str] = []
    for raw_line in stream:
        line = raw_line.rstrip("\r\n")
        if not line:
            continue
        digests.append(_line_digest(line))
        raw_lines.append(line)
        parsed, limitation = parse_history_line(line)
        if limitation is not None:
            limitations.append(limitation)
            continue
        assert parsed is not None
        if parsed.campaign not in CAMPAIGN_TYPES:
            limitations.append(
                _limitation("unsupported campaign type", parsed.campaign, parsed.digest)
            )
            continue
        if parsed.started_at is None:
            limitations.append(
                _limitation(
                    "no timestamp; line kept as raw evidence only", parsed.campaign, parsed.digest
                )
            )
            continue
        key = f"{parsed.campaign}|{parsed.model_id}|{parsed.engine_id}"
        entry = runs.get(key)
        if entry is None:
            slug = _bounded_slug(parsed.campaign)
            run_id = f"History-{slug}-{hashlib.sha256(key.encode()).hexdigest()[:12]}"
            declaration = CampaignDeclaration(
                name=f"History-{slug}",
                campaign_type=parsed.campaign,
                benchmark_revision=context.benchmark_revision,
                duration_seconds=context.duration_seconds,
                concurrency=context.concurrency,
                ownership_target=context.ownership_target,
            )
            identity = RunIdentity(
                machine_id=context.machine_id,
                model_id=parsed.model_id,
                model_revision=context.model_revision or "imported",
                quantization=context.quantization or "unknown",
                engine_id=parsed.engine_id,
                engine_version=context.engine_version or "imported",
                benchmark_revision=context.benchmark_revision,
                launch_configuration=parsed.configuration,
            )
            store.store_run(
                CampaignRun(
                    run_id=run_id,
                    declaration=declaration,
                    identity=identity,
                    started_at=parsed.started_at,
                )
            )
            entry = ([], identity, run_id)
            runs[key] = entry
        samples, _, run_id = entry
        samples.append(
            BenchmarkSample(
                run_id=run_id,
                started_at=parsed.started_at,
                sequence_index=len(samples),
                duration_seconds=parsed.elapsed_seconds,
                ttft_seconds=parsed.ttft_seconds,
                tokens_per_second=parsed.tokens_per_second,
                generated_tokens=parsed.generated_tokens,
                error=parsed.error,
            )
        )
    for samples, _, _ in runs.values():
        if samples:
            store.store_samples(tuple(samples))
    store.store_raw_lines(tuple(raw_lines))
    return HistoryImportReport(
        lines_seen=len(digests),
        lines_mapped=sum(len(samples) for samples, _, _ in runs.values()),
        run_ids=tuple(sorted(run_id for _, _, run_id in runs.values())),
        digests=tuple(digests),
        limitations=tuple(limitations),
    )
