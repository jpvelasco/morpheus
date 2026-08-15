"""Unit tests: bounded compatibility endpoint (GATE-001, GATE-003)."""

from __future__ import annotations

import httpx
import pytest

from morpheus.gateway.compat import (
    COMPAT_SCHEMA_VERSION,
    CompatError,
    CompatForwarder,
    CompatRoute,
    CompatUpstreamError,
    UpstreamStream,
    authenticate,
    build_forward_url,
    resolve_model,
)

MANAGED = "http://127.0.0.1:8000"
BYPASS = "http://127.0.0.1:9000"


def route(**overrides) -> CompatRoute:
    fields = {
        "mode": "managed",
        "managed_base_url": MANAGED,
        "bypass_base_url": BYPASS,
        "aliases": (("prod-model", "Model-7B-v2"),),
    }
    fields.update(overrides)
    return CompatRoute(**fields)


def test_route_defaults_are_bounded_and_versioned() -> None:
    configured = route()
    assert configured.schema_version == COMPAT_SCHEMA_VERSION == 1
    assert configured.mode == "managed"
    assert configured.active_base_url == MANAGED
    assert configured.base_urls == frozenset({MANAGED, BYPASS})


def test_route_rejects_invalid_configuration() -> None:
    with pytest.raises(CompatError, match="schema version"):
        CompatRoute(schema_version=2, mode="managed", managed_base_url=MANAGED)
    with pytest.raises(CompatError, match="mode"):
        CompatRoute(mode="routed", managed_base_url=MANAGED)
    with pytest.raises(CompatError, match="bare http"):
        CompatRoute(mode="managed", managed_base_url="http://127.0.0.1:8000/v1")
    with pytest.raises(CompatError, match="bare http"):
        CompatRoute(mode="managed", managed_base_url="ftp://127.0.0.1:8000")
    with pytest.raises(CompatError, match="requires a managed"):
        CompatRoute(mode="managed")
    with pytest.raises(CompatError, match="requires a bypass"):
        CompatRoute(mode="bypass")
    with pytest.raises(CompatError, match="must differ"):
        CompatRoute(mode="managed", managed_base_url=MANAGED, bypass_base_url=MANAGED)
    with pytest.raises(CompatError, match="unique"):
        route(aliases=(("a", "x"), ("a", "y")))
    with pytest.raises(CompatError, match="non-empty"):
        route(aliases=(("", "x"),))


def test_route_alias_map_is_deterministic_and_casefolded() -> None:
    configured = route(aliases=(("Prod-Model", "Model-7B-v2"), ("dev", "Model-7B-dev")))
    assert configured.alias_map.resolve("prod-model") == "Model-7B-v2"
    assert configured.alias_map.resolve("PROD-MODEL") == "Model-7B-v2"


def test_authenticate_is_constant_time_and_requires_secret() -> None:
    assert authenticate("secret-456", "secret-456") is True
    assert authenticate("secret-457", "secret-456") is False
    assert authenticate(None, "secret-456") is False
    assert authenticate("secret-456", "") is False
    assert authenticate("secret-456", None) is False


def test_resolve_model_managed_resolves_aliases_bypass_is_identity() -> None:
    configured = route(mode="managed")
    assert resolve_model(configured, "prod-model") == "Model-7B-v2"
    with pytest.raises(KeyError):
        resolve_model(configured, "unknown-alias")
    assert resolve_model(configured, None) is None
    bypass = route(mode="bypass", bypass_base_url=BYPASS)
    assert resolve_model(bypass, "whatever-name") == "whatever-name"


def test_build_forward_url_is_bounded() -> None:
    assert build_forward_url(MANAGED, "/v1/chat/completions") == (f"{MANAGED}/v1/chat/completions")
    assert build_forward_url(MANAGED, "/v1/models", b"limit=1") == f"{MANAGED}/v1/models?limit=1"
    with pytest.raises(CompatError, match="bounded"):
        build_forward_url(MANAGED, "v1/models")
    with pytest.raises(CompatError, match="bounded"):
        build_forward_url(MANAGED, "/v1/../etc/passwd")
    with pytest.raises(CompatError, match="unsafe"):
        build_forward_url(MANAGED, "/v1/models", b"x=1&y=2;rm -rf")


async def test_forwarder_open_stream_passes_bytes_and_cancels_on_close() -> None:
    chunks = [b"data: one\n\n", b"data: two\n\n"]
    calls: list[httpx.Request] = []
    bodies: list[bytes] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        bodies.append(request.read())
        return httpx.Response(
            200,
            stream=httpx.ByteStream(b"".join(chunks)),
            headers={"content-type": "text/event-stream"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    forwarder = CompatForwarder(client=client)
    stream = await forwarder.open_stream(
        method="POST",
        url=f"{MANAGED}/v1/chat/completions",
        headers={"content-type": "application/json"},
        content=b'{"model": "m"}',
    )
    assert isinstance(stream, UpstreamStream)
    assert stream.status_code == 200
    assert stream.headers["content-type"] == "text/event-stream"
    collected = b"".join([chunk async for chunk in stream.aiter_raw()])
    assert collected == b"".join(chunks)
    await stream.aclose()
    await forwarder.aclose()
    assert calls[0].url.path == "/v1/chat/completions"
    assert bodies[0] == b'{"model": "m"}'


async def test_forwarder_maps_upstream_rejection_and_network_failure() -> None:
    async def reject(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(500, text="boom")

    client = httpx.AsyncClient(transport=httpx.MockTransport(reject))
    forwarder = CompatForwarder(client=client)
    with pytest.raises(CompatUpstreamError) as error:
        await forwarder.open_stream(method="POST", url=f"{MANAGED}/v1/chat/completions", headers={})
    assert error.value.status_code == 500
    await forwarder.aclose()

    def explode(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("fixture", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(explode))
    forwarder = CompatForwarder(client=client)
    with pytest.raises(httpx.ConnectError):
        await forwarder.open_stream(method="POST", url=f"{MANAGED}/v1/chat/completions", headers={})
    await forwarder.aclose()


async def test_forwarder_forward_once_returns_byte_exact_body() -> None:
    payload = b'{"data": ["a", "b"]}'

    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, content=payload, headers={"content-type": "application/json"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    forwarder = CompatForwarder(client=client)
    response = await forwarder.forward_once(method="GET", url=f"{MANAGED}/v1/models", headers={})
    assert response.content == payload
    await forwarder.aclose()
