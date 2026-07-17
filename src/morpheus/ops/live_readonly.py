from __future__ import annotations

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from morpheus.adapters.inference.openai import InferenceContractError, OpenAIInferenceAdapter
from morpheus.adapters.metrics.vllm import VllmMetricsAdapter
from morpheus.core.concurrency import RetryPolicy


class LiveValidationError(ValueError):
    """The live validation lane is disabled or its target is unsafe."""


def safe_live_failure_code(error: BaseException) -> str:
    if isinstance(error, LiveValidationError):
        return "live_guard_rejected"
    if isinstance(error, httpx.TimeoutException):
        return "upstream_timeout"
    if isinstance(error, httpx.NetworkError):
        return "upstream_unreachable"
    if isinstance(error, httpx.HTTPStatusError):
        return "upstream_http_error"
    if isinstance(error, InferenceContractError | ValueError):
        return "upstream_contract_incompatible"
    return "live_probe_failed"


@dataclass(frozen=True, slots=True)
class LiveReadOnlyConfig:
    inference_base_url: str
    metrics_url: str
    timeout_seconds: float
    api_key: str = ""

    @property
    def models_url(self) -> str:
        return f"{self.inference_base_url}/models"

    @property
    def allowed_requests(self) -> frozenset[tuple[str, str]]:
        return frozenset({("GET", self.models_url), ("GET", self.metrics_url)})

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> LiveReadOnlyConfig:
        if environment.get("MORPHEUS_LIVE_TESTS") != "1":
            raise LiveValidationError("live validation requires explicit opt-in")
        if environment.get("MORPHEUS_LIVE_MUTATION") != "0":
            raise LiveValidationError("read-only validation requires mutation to be disabled")
        if environment.get("MORPHEUS_LIVE_COMPLETIONS", "0") != "0":
            raise LiveValidationError("completion requests are forbidden in the read-only lane")

        allowed_hosts = _allowed_hosts(environment.get("MORPHEUS_LIVE_ALLOWED_HOSTS", ""))
        inference_base_url = _validated_url(
            environment.get("MORPHEUS_LIVE_VLLM_URL", ""),
            allowed_hosts=allowed_hosts,
            required_path="/v1",
            name="inference",
        )
        metrics_url = _validated_url(
            environment.get("MORPHEUS_LIVE_VLLM_METRICS_URL", ""),
            allowed_hosts=allowed_hosts,
            required_path="/metrics",
            name="metrics",
        )
        try:
            timeout_seconds = float(environment.get("MORPHEUS_LIVE_TIMEOUT_SECONDS", "5"))
        except ValueError as error:
            raise LiveValidationError("live timeout must be numeric") from error
        if not 0 < timeout_seconds <= 10:
            raise LiveValidationError(
                "live timeout must be greater than zero and at most 10 seconds"
            )
        return cls(
            inference_base_url=inference_base_url,
            metrics_url=metrics_url,
            timeout_seconds=timeout_seconds,
            api_key=environment.get("MORPHEUS_LIVE_VLLM_API_KEY", ""),
        )


class LiveReadOnlyGuardTransport(httpx.AsyncBaseTransport):
    """Allow only exact, declared GET requests to reach the network transport."""

    def __init__(
        self,
        *,
        allowed_requests: frozenset[tuple[str, str]],
        inner: httpx.AsyncBaseTransport,
    ) -> None:
        self._allowed_requests = allowed_requests
        self._inner = inner
        self._request_count = 0

    @property
    def request_count(self) -> int:
        return self._request_count

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        identity = (request.method.upper(), str(request.url))
        if identity not in self._allowed_requests:
            raise LiveValidationError("live request is not on the read-only allowlist")
        self._request_count += 1
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


@dataclass(frozen=True, slots=True)
class LiveModelObservation:
    root: str | None
    aliases: tuple[str, ...]
    context_window: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "aliases": list(self.aliases),
            "context_window": self.context_window,
        }


@dataclass(frozen=True, slots=True)
class LiveMetricsObservation:
    available_signals: tuple[str, ...]
    missing_signals: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "available_signals": list(self.available_signals),
            "missing_signals": list(self.missing_signals),
        }


@dataclass(frozen=True, slots=True)
class LiveReadOnlyReport:
    models: tuple[LiveModelObservation, ...]
    metrics: LiveMetricsObservation
    request_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "pass",
            "health": "ready",
            "models": [model.to_dict() for model in self.models],
            "metrics": self.metrics.to_dict(),
            "request_count": self.request_count,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


async def run_live_readonly_probe(
    config: LiveReadOnlyConfig,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> LiveReadOnlyReport:
    inner = transport or httpx.AsyncHTTPTransport(retries=0)
    guard = LiveReadOnlyGuardTransport(
        allowed_requests=config.allowed_requests,
        inner=inner,
    )
    async with httpx.AsyncClient(transport=guard, follow_redirects=False) as client:
        inference = OpenAIInferenceAdapter(
            base_url=config.inference_base_url,
            client=client,
            clock=_LiveClock(),
            timeout_seconds=config.timeout_seconds,
            api_key=config.api_key,
            retry_policy=RetryPolicy(
                max_attempts=1,
                deadline_seconds=config.timeout_seconds,
                jitter_ratio=0,
            ),
        )
        models = await inference.models()
        if not models:
            raise LiveValidationError("live inference is reachable but has no served model")
        metrics = await VllmMetricsAdapter(
            metrics_url=config.metrics_url,
            timeout_seconds=config.timeout_seconds,
            client=client,
        ).collect()

    return LiveReadOnlyReport(
        models=tuple(
            LiveModelObservation(
                root=model.root,
                aliases=model.aliases,
                context_window=model.context_window,
            )
            for model in models
        ),
        metrics=LiveMetricsObservation(
            available_signals=tuple(sorted(metrics.available_signals)),
            missing_signals=tuple(sorted(metrics.missing_signals)),
        ),
        request_count=guard.request_count,
    )


class _LiveClock:
    def utc_now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()


def _allowed_hosts(value: str) -> frozenset[str]:
    hosts = frozenset(item.strip().lower().rstrip(".") for item in value.split(",") if item.strip())
    if not hosts:
        raise LiveValidationError("at least one live host must be explicitly allowlisted")
    if any(
        host == "*"
        or any(character.isspace() for character in host)
        or any(character in host for character in "/@?#")
        for host in hosts
    ):
        raise LiveValidationError("live host allowlist contains an invalid entry")
    return hosts


def _validated_url(
    value: str,
    *,
    allowed_hosts: frozenset[str],
    required_path: str,
    name: str,
) -> str:
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError as error:
        raise LiveValidationError(f"{name} URL is invalid") from error
    hostname = parsed.hostname.lower().rstrip(".") if parsed.hostname else ""
    if parsed.scheme.lower() not in {"http", "https"} or not hostname:
        raise LiveValidationError(f"{name} URL must use HTTP or HTTPS and include a host")
    if parsed.username is not None or parsed.password is not None:
        raise LiveValidationError(f"{name} URL must not contain credentials")
    if parsed.query or parsed.fragment or parsed.path != required_path:
        raise LiveValidationError(f"{name} URL must use the exact declared read-only route")
    if hostname not in allowed_hosts:
        raise LiveValidationError(f"{name} URL host is not allowlisted")

    rendered_host = f"[{hostname}]" if ":" in hostname else hostname
    netloc = f"{rendered_host}:{port}" if port is not None else rendered_host
    return urlunsplit((parsed.scheme.lower(), netloc, required_path, "", ""))
