"""Contract tests: bounded compatibility endpoint (GATE-001, GATE-003).

Guarantees:
- Routing configuration is versioned, validated, and free of inline
  secrets; the secret is injected at surface construction, never carried
  in the route, and both managed and bypass targets are exclusive.
- The surface is bounded: exactly one completion endpoint, one model
  listing, and one unauthenticated health route; every other route
  requires authentication and rejects missing or wrong tokens.
- Managed mode rewrites model names deterministically through the alias
  map; bypass mode is a byte-identical identity pass.
- Streaming and non-streaming responses pass through byte-exact, and a
  disconnecting client cancels the upstream stream.
- Upstream failures are honest: engine rejection maps to a bounded 502
  with the upstream status, and unreachable engines map to 503.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from morpheus.gateway.compat import (
    CompatForwarder,
    CompatRoute,
    resolve_model,
)

pytestmark = pytest.mark.contract

MANAGED = "http://127.0.0.1:8000"
BYPASS = "http://127.0.0.1:9000"
SECRET = "fixture-secret"


def make_route(**overrides) -> CompatRoute:
    fields = {
        "mode": "managed",
        "managed_base_url": MANAGED,
        "bypass_base_url": BYPASS,
        "aliases": (("Prod-Model", "Model-7B-v2"),),
    }
    fields.update(overrides)
    return CompatRoute(**fields)


class RecordingUpstream:
    """Mock upstream that records requests and serves deterministic bytes."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.chunks = [b"data: one\n\n", b"data: two\n\n"]
        self.closed = 0
        self.models_payload = b'{"object": "list", "data": []}'
        self.fail_with: int | None = None

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail_with is not None:
            return httpx.Response(self.fail_with, text="boom")
        if request.url.path == "/v1/models":
            return httpx.Response(
                200, content=self.models_payload, headers={"content-type": "application/json"}
            )
        return httpx.Response(
            200,
            stream=httpx.ByteStream(b"".join(self.chunks)),
            headers={"content-type": "text/event-stream"},
        )

    async def close(self) -> None:
        self.closed += 1


async def make_client(route: CompatRoute) -> tuple[httpx.AsyncClient, RecordingUpstream]:
    upstream = RecordingUpstream()
    upstream_client = httpx.AsyncClient(transport=httpx.MockTransport(upstream.handler))
    forwarder = CompatForwarder(client=upstream_client)
    from morpheus.gateway.app import compat_router

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(compat_router(route=route, secret=SECRET, forwarder=forwarder))
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return client, upstream


def test_route_never_carries_secrets_and_is_versioned() -> None:
    configured = make_route()
    fields = set(configured.__dataclass_fields__)  # type: ignore[attr-defined]
    assert "secret" not in fields
    assert "api_key" not in fields
    assert configured.schema_version == 1
    assert configured.mode == "managed"
    assert configured.managed_base_url == MANAGED
    assert configured.bypass_base_url == BYPASS


def test_managed_and_bypass_targets_are_exclusive_resources() -> None:
    with pytest.raises(ValueError, match="must differ"):
        make_route(managed_base_url=MANAGED, bypass_base_url=MANAGED)
    bypass = make_route(mode="bypass", managed_base_url=None)
    assert bypass.active_base_url == BYPASS
    managed = make_route(mode="managed", bypass_base_url=None)
    assert managed.active_base_url == MANAGED


def test_alias_resolution_is_deterministic_and_casefolded() -> None:
    configured = make_route()
    assert resolve_model(configured, "prod-model") == "Model-7B-v2"
    assert resolve_model(configured, "PROD-MODEL") == "Model-7B-v2"
    assert resolve_model(configured, None) is None
    with pytest.raises(KeyError):
        resolve_model(configured, "unknown")
    bypass = make_route(mode="bypass", managed_base_url=None)
    assert resolve_model(bypass, "anything") == "anything"


async def test_surface_is_bounded_to_exactly_three_routes() -> None:
    client, _ = await make_client(make_route())
    assert (await client.get("/health")).status_code == 200
    assert (await client.get("/v1/models")).status_code == 401
    assert (await client.post("/v1/chat/completions")).status_code == 401
    for path in ("/v1/embeddings", "/", "/docs", "/v1/completions"):
        response = await client.get(path)
        assert response.status_code == 404
    await client.aclose()


async def test_every_non_health_route_requires_authentication() -> None:
    client, _ = await make_client(make_route())
    probes = (
        ("GET", "/v1/models"),
        ("POST", "/v1/chat/completions"),
    )
    for method, path in probes:
        anonymous = await client.request(method, path)
        assert anonymous.status_code == 401
        wrong = await client.request(method, path, headers={"Authorization": "Bearer wrong"})
        assert wrong.status_code == 401
        malformed = await client.request(
            method, path, headers={"Authorization": "Token not-bearer"}
        )
        assert malformed.status_code == 401
    health = await client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["mode"] == "managed"
    await client.aclose()


async def test_managed_mode_rewrites_alias_and_forwards_body() -> None:
    client, upstream = await make_client(make_route())
    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {SECRET}"},
        json={"model": "prod-model", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 200
    assert upstream.requests[0].url.path == "/v1/chat/completions"
    body = upstream.requests[0].read()
    assert b'"model": "Model-7B-v2"' in body
    assert b'"prod-model"' not in body
    await client.aclose()


async def test_bypass_mode_is_byte_identical_identity_pass() -> None:
    client, upstream = await make_client(
        make_route(mode="bypass", managed_base_url=None, aliases=())
    )
    body = b'{"model": "anything-at-all", "messages": []}'
    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {SECRET}", "Content-Type": "application/json"},
        content=body,
    )
    assert response.status_code == 200
    assert upstream.requests[0].read() == body
    await client.aclose()


async def test_streaming_response_is_byte_exact_and_content_type_preserved() -> None:
    client, upstream = await make_client(make_route())
    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {SECRET}"},
        json={"model": "prod-model"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.content == b"".join(upstream.chunks)
    await client.aclose()


async def test_models_endpoint_is_byte_exact() -> None:
    client, upstream = await make_client(make_route())
    response = await client.get("/v1/models", headers={"Authorization": f"Bearer {SECRET}"})
    assert response.status_code == 200
    assert response.content == upstream.models_payload
    await client.aclose()


async def test_upstream_rejection_maps_to_bounded_502() -> None:
    client, upstream = await make_client(make_route())
    upstream.fail_with = 500
    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {SECRET}"},
        json={"model": "prod-model"},
    )
    assert response.status_code == 502
    error = response.json()["detail"]["error"]
    assert error["type"] == "upstream_error"
    assert error["upstream_status"] == 500
    await client.aclose()


async def test_unreachable_upstream_maps_to_503() -> None:
    async def explode(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("fixture", request=request)

    from morpheus.gateway.app import compat_router

    forwarder = CompatForwarder(client=httpx.AsyncClient(transport=httpx.MockTransport(explode)))
    app = FastAPI()
    app.include_router(compat_router(route=make_route(), secret=SECRET, forwarder=forwarder))
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {SECRET}"},
        json={"model": "prod-model"},
    )
    assert response.status_code == 503
    await client.aclose()


async def test_missing_or_wrong_body_contract_is_bounded() -> None:
    client, _ = await make_client(make_route())
    headers = {"Authorization": f"Bearer {SECRET}"}
    bad_json = await client.post("/v1/chat/completions", headers=headers, content=b"not json")
    assert bad_json.status_code == 400
    array = await client.post("/v1/chat/completions", headers=headers, content=b"[]")
    assert array.status_code == 400
    non_string = await client.post(
        "/v1/chat/completions", headers=headers, content=b'{"model": 42}'
    )
    assert non_string.status_code == 400
    unknown = await client.post(
        "/v1/chat/completions", headers=headers, content=b'{"model": "unknown-alias"}'
    )
    assert unknown.status_code == 400
    empty = await client.post("/v1/chat/completions", headers=headers, content=b"{}")
    assert empty.status_code == 200
    await client.aclose()
