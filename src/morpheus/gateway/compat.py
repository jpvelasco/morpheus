"""Bounded compatibility endpoint core (GATE-001, GATE-003).

When enabled, the compatibility layer exposes exactly one authenticated
endpoint for the selected managed runtime, with a documented direct bypass
path. It is not LiteLLM: no provider routing, one managed target and one
bypass target, deterministic alias resolution, versioned validated routing
configuration free of inline secrets.
"""

from __future__ import annotations

import hmac
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx

from morpheus.core.gateway import AliasMap

COMPAT_SCHEMA_VERSION = 1
MODES = ("managed", "bypass")

_URL_PATTERN = re.compile(r"^https?://[A-Za-z0-9_.:-]+(?::\d{1,5})?$")


class CompatError(ValueError):
    """Routing configuration or request violates the bounded contract."""


def _valid_base_url(value: str) -> bool:
    return bool(_URL_PATTERN.fullmatch(value))


@dataclass(frozen=True, slots=True)
class CompatRoute:
    """Versioned routing configuration; one managed target, one bypass."""

    schema_version: int = COMPAT_SCHEMA_VERSION
    mode: str = "managed"
    managed_base_url: str | None = None
    bypass_base_url: str | None = None
    aliases: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != COMPAT_SCHEMA_VERSION:
            raise CompatError("compat route schema version is unsupported")
        if self.mode not in MODES:
            raise CompatError(f"compat route mode must be one of {MODES}")
        for label, value in (
            ("managed base url", self.managed_base_url),
            ("bypass base url", self.bypass_base_url),
        ):
            if value is not None and not _valid_base_url(value):
                raise CompatError(f"{label} must be a bare http(s) URL without path or query")
        if self.mode == "managed" and not self.managed_base_url:
            raise CompatError("managed mode requires a managed base url")
        if self.mode == "bypass" and not self.bypass_base_url:
            raise CompatError("bypass mode requires a bypass base url")
        if (
            self.managed_base_url is not None
            and self.bypass_base_url is not None
            and self.managed_base_url.casefold() == self.bypass_base_url.casefold()
        ):
            raise CompatError("managed and bypass targets must differ (exclusive resources)")
        normalized: dict[str, str] = {}
        for alias, target in self.aliases:
            name = alias.strip().casefold()
            resolved = target.strip()
            if not name or not resolved or name in normalized:
                raise CompatError("aliases must be non-empty, unique, and resolve to a target")
            normalized[name] = resolved
        normalized_tuple = tuple((key, value) for key, value in normalized.items())
        object.__setattr__(self, "aliases", normalized_tuple)

    @property
    def alias_map(self) -> AliasMap:
        return AliasMap(dict(self.aliases))

    @property
    def active_base_url(self) -> str:
        base = self.managed_base_url if self.mode == "managed" else self.bypass_base_url
        if base is None:
            raise CompatError("no base url is configured for the active mode")
        return base

    @property
    def base_urls(self) -> frozenset[str]:
        return frozenset(
            url.casefold()
            for url in (self.managed_base_url, self.bypass_base_url)
            if url is not None
        )


def authenticate(token: str | None, secret: str) -> bool:
    """Constant-time bearer check; a secret is required and never inline."""
    if not secret or token is None:
        return False
    return hmac.compare_digest(token.encode(), secret.encode())


def resolve_model(route: CompatRoute, model: str | None) -> str | None:
    """Deterministic alias resolution for managed mode; bypass is identity."""
    if model is None:
        return None
    if route.mode == "managed":
        return route.alias_map.resolve(model)
    return model


def build_forward_url(base: str, path: str, query: bytes | None = None) -> str:
    if not re.fullmatch(r"/[A-Za-z0-9_.\-/]*", path) or ".." in path:
        raise CompatError("forward path is not a bounded token path")
    url = f"{base.rstrip('/')}{path}"
    if query:
        decoded = query.decode("ascii", "replace")
        if not re.fullmatch(r"[A-Za-z0-9_=&%.:+\-]*", decoded):
            raise CompatError("forward query contains unsafe characters")
        url = f"{url}?{decoded}"
    return url


class CompatForwarder:
    """Byte-exact forwarding; upstream stream closes on consumer disconnect."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def open_stream(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        content: bytes | None = None,
    ) -> UpstreamStream:
        request = self._client.build_request(method, url, headers=headers, content=content)
        response = await self._client.send(request, stream=True)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            await response.aclose()
            raise CompatUpstreamError(
                error.response.status_code,
                f"upstream runtime returned {error.response.status_code}",
            ) from error
        return UpstreamStream(response)

    async def forward_once(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        content: bytes | None = None,
    ) -> httpx.Response:
        try:
            response = await self._client.request(
                method, url, headers=headers, content=content, timeout=self._client.timeout
            )
        except httpx.HTTPStatusError as error:
            raise CompatUpstreamError(
                error.response.status_code,
                f"upstream runtime returned {error.response.status_code}",
            ) from error
        return response


class UpstreamStream:
    """An open upstream response; close it to cancel the upstream request."""

    def __init__(self, response: httpx.Response) -> None:
        self._response = response
        self.status_code = response.status_code
        self.headers = response.headers

    async def aiter_raw(self) -> AsyncIterator[bytes]:
        async for chunk in self._response.aiter_raw():
            yield chunk

    async def aclose(self) -> None:
        await self._response.aclose()


class CompatUpstreamError(RuntimeError):
    """The upstream runtime rejected or dropped the forwarded request."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
