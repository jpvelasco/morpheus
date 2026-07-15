from __future__ import annotations

import secrets
import time

import httpx

from morpheus.agent.auth import sign_request
from morpheus.agent.protocol import AgentOperation, AgentRequest, AgentResponse


class RuntimeAgentClient:
    def __init__(
        self,
        *,
        base_url: str,
        key: bytes,
        timeout_seconds: float = 5,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._key = key
        self._timeout = timeout_seconds
        self._client = client

    async def inspect(self, operation: AgentOperation) -> AgentResponse:
        request = AgentRequest(request_id=secrets.token_hex(16), operation=operation)
        body = request.model_dump_json().encode()
        timestamp = str(int(time.time()))
        nonce = secrets.token_hex(16)
        signature = sign_request(self._key, timestamp=timestamp, nonce=nonce, body=body)
        headers = {
            "Content-Type": "application/json",
            "X-Morpheus-Timestamp": timestamp,
            "X-Morpheus-Nonce": nonce,
            "X-Morpheus-Signature": signature,
        }
        if self._client is None:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self._base_url}/v1/inspect",
                    content=body,
                    headers=headers,
                    timeout=self._timeout,
                )
        else:
            response = await self._client.post(
                f"{self._base_url}/v1/inspect",
                content=body,
                headers=headers,
                timeout=self._timeout,
            )
        response.raise_for_status()
        return AgentResponse.model_validate(response.json())
