from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any, Self

import httpx

from morpheus.core.health import Evidence, HealthState
from morpheus.core.models import ModelIdentity
from morpheus.ports.protocols import Clock


class InferenceContractError(ValueError):
    """The inference endpoint returned an incompatible public contract."""


class OpenAIInferenceAdapter:
    def __init__(
        self,
        *,
        base_url: str,
        clock: Clock,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
        api_key: str = "",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._clock = clock
        self._timeout = httpx.Timeout(timeout_seconds)
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = client or httpx.AsyncClient()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self._client.aclose()

    async def models(self) -> tuple[ModelIdentity, ...]:
        response = await self._client.get(
            f"{self._base_url}/models", headers=self._headers, timeout=self._timeout
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except json.JSONDecodeError as error:
            raise InferenceContractError("models response is not valid JSON") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise InferenceContractError("models response must contain a data list")

        grouped: dict[str, dict[str, Any]] = {}
        for item in payload["data"]:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
                raise InferenceContractError("every model entry must contain a string id")
            root_value = item.get("root")
            if root_value is not None and not isinstance(root_value, str):
                raise InferenceContractError("model root must be a string when present")
            root = root_value or item["id"]
            context = _context_window(item)
            current = grouped.setdefault(root, {"root": root_value, "aliases": [], "contexts": []})
            current["aliases"].append(item["id"])
            if context is not None:
                current["contexts"].append(context)

        return tuple(
            ModelIdentity(
                root=entry["root"],
                aliases=tuple(entry["aliases"]),
                context_window=max(entry["contexts"], default=None),
            )
            for entry in grouped.values()
        )

    async def health(self) -> Evidence:
        started = self._clock.monotonic()
        now = self._clock.utc_now()
        state = HealthState.UNKNOWN
        code = "inference_unknown"
        summary = "Inference health could not be determined"
        try:
            models = await self.models()
            if models:
                state = HealthState.READY
                code = "inference_models_ready"
                summary = "Inference API returned one or more served models"
            else:
                state = HealthState.STARTING
                code = "inference_no_models"
                summary = "Inference API is reachable but has no served model"
        except InferenceContractError:
            state = HealthState.INCOMPATIBLE
            code = "inference_contract_incompatible"
            summary = "Inference API returned an incompatible models response"
        except httpx.HTTPStatusError as error:
            state = (
                HealthState.STARTING
                if error.response.status_code in {425, 429, 503}
                else HealthState.DEGRADED
            )
            code = "inference_starting" if state is HealthState.STARTING else "inference_http_error"
            summary = (
                "Inference API is not ready"
                if state is HealthState.STARTING
                else "Inference API returned an error"
            )
        except (httpx.TimeoutException, httpx.NetworkError):
            state = HealthState.UNREACHABLE
            code = "inference_unreachable"
            summary = "Inference API is unreachable"

        duration = max(0.0, self._clock.monotonic() - started)
        return Evidence(
            state=state,
            reason_code=code,
            summary=summary,
            observed_at=now,
            duration=timedelta(seconds=duration),
            source="openai_models",
            expires_at=now + timedelta(seconds=30),
        )

    async def forward_chat(self, body: bytes) -> AsyncIterator[bytes]:
        async with self._client.stream(
            "POST",
            f"{self._base_url}/chat/completions",
            content=body,
            headers={"Content-Type": "application/json", **self._headers},
            timeout=self._timeout,
        ) as response:
            response.raise_for_status()
            async for chunk in response.aiter_raw():
                yield chunk


def _context_window(item: dict[str, Any]) -> int | None:
    for field in ("max_model_len", "max_context_length", "context_length"):
        value = item.get(field)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise InferenceContractError(f"{field} must be a positive integer")
        return int(value)
    return None
