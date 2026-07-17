from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from morpheus.adapters.runtime.agent import RuntimeAgentClient
from morpheus.agent.auth import AgentAuthenticator
from morpheus.agent.protocol import AgentOperation
from morpheus.core.lifecycle import LifecycleAction, LifecycleRequest

pytestmark = pytest.mark.contract
KEY = b"runtime-agent-contract-key"


@pytest.mark.asyncio
async def test_SEC_001_client_signs_typed_agent_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/inspect"
        timestamp = request.headers["X-Morpheus-Timestamp"]
        body = request.content
        AgentAuthenticator(KEY).verify(
            timestamp=timestamp,
            nonce=request.headers["X-Morpheus-Nonce"],
            signature=request.headers["X-Morpheus-Signature"],
            body=body,
            now=datetime.fromtimestamp(int(timestamp), tz=UTC),
        )
        payload = json.loads(body)
        return httpx.Response(
            200,
            json={
                "request_id": payload["request_id"],
                "operation": payload["operation"],
                "result": {"gpus": []},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        response = await RuntimeAgentClient(
            base_url="http://agent.test", key=KEY, client=http
        ).inspect(AgentOperation.GPU_SUMMARY)

    assert response.operation is AgentOperation.GPU_SUMMARY
    assert response.result == {"gpus": []}


@pytest.mark.asyncio
async def test_SEC_001_client_rejects_incompatible_agent_response() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"result": {}}))
    async with httpx.AsyncClient(transport=transport) as http:
        client = RuntimeAgentClient(base_url="http://agent.test", key=KEY, client=http)
        with pytest.raises(ValidationError):
            await client.inspect(AgentOperation.HOST_SUMMARY)


@pytest.mark.asyncio
async def test_SEC_001_client_rejects_mismatched_agent_response_identity() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "request_id": "different-request",
                "operation": "host_summary",
                "result": {},
            },
        )
    )
    async with httpx.AsyncClient(transport=transport) as http:
        client = RuntimeAgentClient(base_url="http://agent.test", key=KEY, client=http)
        with pytest.raises(ValueError, match="mismatched"):
            await client.inspect(AgentOperation.HOST_SUMMARY)


@pytest.mark.asyncio
async def test_SEC_001_client_rejects_ambiguous_injected_transport() -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="Unix socket"):
            RuntimeAgentClient(
                key=KEY,
                uds=Path("/run/morpheus-agent/agent.sock"),
                client=client,
            )


@pytest.mark.asyncio
async def test_REL_003_client_signs_typed_lifecycle_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/lifecycle"
        timestamp = request.headers["X-Morpheus-Timestamp"]
        AgentAuthenticator(KEY).verify(
            timestamp=timestamp,
            nonce=request.headers["X-Morpheus-Nonce"],
            signature=request.headers["X-Morpheus-Signature"],
            body=request.content,
            now=datetime.fromtimestamp(int(timestamp), tz=UTC),
        )
        payload = json.loads(request.content)
        assert set(payload) == {
            "action",
            "backup_id",
            "confirmation",
            "request_id",
            "version",
        }
        return httpx.Response(
            200,
            json={
                "request_id": payload["request_id"],
                "action": payload["action"],
                "result": {
                    "action": "backup",
                    "outcome": "applied",
                    "protected_external_runtime": "unchanged",
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        response = await RuntimeAgentClient(
            base_url="http://agent.test", key=KEY, client=http
        ).lifecycle(
            LifecycleRequest(
                action=LifecycleAction.BACKUP,
                backup_id="before-upgrade",
            )
        )

    assert response.action is LifecycleAction.BACKUP
    assert response.result["outcome"] == "applied"
