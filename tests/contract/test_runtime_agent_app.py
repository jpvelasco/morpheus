from __future__ import annotations

import json
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from morpheus.agent.app import create_agent_app
from morpheus.agent.auth import sign_request
from morpheus.config import MorpheusSettings
from morpheus.core.lifecycle import LifecycleAction

pytestmark = pytest.mark.contract
KEY = b"runtime-agent-contract-key"


class FakeInspector:
    def inspect(self, operation: object) -> dict[str, Any]:
        return {"operation": str(operation)}


class DenyingInspector:
    def inspect(self, operation: object) -> dict[str, Any]:
        del operation
        raise PermissionError("resource action is not authorized")


class FakeLifecycle:
    def execute(self, request: object) -> object:
        action = request.action

        class Result:
            def as_dict(self) -> dict[str, object]:
                return {
                    "action": action.value,
                    "outcome": "already_satisfied",
                    "protected_external_runtime": "unchanged",
                }

        return Result()


def agent(
    *,
    inspector: object | None = None,
    lifecycle: object | None = None,
    **settings_overrides: object,
) -> TestClient:
    return TestClient(
        create_agent_app(
            settings=MorpheusSettings(agent_key=KEY.decode(), **settings_overrides),
            inspector=inspector or FakeInspector(),  # type: ignore[arg-type]
            lifecycle=lifecycle,  # type: ignore[arg-type]
        )
    )


def signed_headers(body: bytes, *, nonce: str = "unique-nonce") -> dict[str, str]:
    timestamp = str(int(time.time()))
    return {
        "Content-Type": "application/json",
        "X-Morpheus-Timestamp": timestamp,
        "X-Morpheus-Nonce": nonce,
        "X-Morpheus-Signature": sign_request(KEY, timestamp=timestamp, nonce=nonce, body=body),
    }


def test_SEC_003_agent_rejects_non_json_before_authentication() -> None:
    response = agent().post(
        "/v1/inspect",
        content=b"not-json",
        headers={
            "Content-Type": "text/plain",
            "X-Morpheus-Timestamp": "0",
            "X-Morpheus-Nonce": "x",
            "X-Morpheus-Signature": "x",
        },
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_content_type"


def test_SEC_003_agent_rejects_invalid_signed_schema() -> None:
    body = json.dumps({"request_id": "valid-request", "operation": "not-supported"}).encode()
    response = agent().post("/v1/inspect", content=body, headers=signed_headers(body))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_SEC_003_agent_rejects_malformed_content_length() -> None:
    response = agent().post(
        "/v1/inspect",
        content=b"{}",
        headers={
            "Content-Type": "application/json",
            "Content-Length": "invalid",
            "X-Morpheus-Timestamp": "0",
            "X-Morpheus-Nonce": "x",
            "X-Morpheus-Signature": "x",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_content_length"


def test_SEC_003_agent_rate_limits_before_inspection() -> None:
    payload = json.dumps({"request_id": "valid-request", "operation": "host_summary"}).encode()
    runtime_agent = agent(max_requests_per_minute=1)

    assert (
        runtime_agent.post(
            "/v1/inspect", content=payload, headers=signed_headers(payload)
        ).status_code
        == 200
    )
    limited = runtime_agent.post(
        "/v1/inspect", content=payload, headers=signed_headers(payload, nonce="other-nonce")
    )
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "request_rate_limited"


def test_SEC_002_agent_normalizes_authorization_denial() -> None:
    body = json.dumps({"request_id": "valid-request", "operation": "morpheus_services"}).encode()

    response = agent(inspector=DenyingInspector()).post(
        "/v1/inspect", content=body, headers=signed_headers(body)
    )

    assert response.status_code == 403
    assert response.json() == {"error": {"code": "authorization_denied"}}


def test_REL_003_agent_accepts_only_a_signed_typed_lifecycle_operation() -> None:
    body = json.dumps(
        {
            "request_id": "lifecycle-request",
            "action": LifecycleAction.START.value,
            "version": None,
            "backup_id": None,
            "confirmation": None,
        }
    ).encode()

    response = agent(lifecycle=FakeLifecycle()).post(
        "/v1/lifecycle", content=body, headers=signed_headers(body)
    )

    assert response.status_code == 200
    assert response.json() == {
        "request_id": "lifecycle-request",
        "action": "start",
        "result": {
            "action": "start",
            "outcome": "already_satisfied",
            "protected_external_runtime": "unchanged",
        },
    }


def test_REL_003_agent_fails_closed_when_lifecycle_is_not_configured() -> None:
    body = json.dumps(
        {
            "request_id": "lifecycle-request",
            "action": "start",
            "version": None,
            "backup_id": None,
            "confirmation": None,
        }
    ).encode()

    response = agent().post("/v1/lifecycle", content=body, headers=signed_headers(body))

    assert response.status_code == 503
    assert response.json() == {"error": {"code": "lifecycle_unavailable"}}


def test_SEC_002_agent_rejects_arbitrary_lifecycle_target_fields() -> None:
    body = json.dumps(
        {
            "request_id": "lifecycle-request",
            "action": "start",
            "target": "history-coder",
        }
    ).encode()

    response = agent(lifecycle=FakeLifecycle()).post(
        "/v1/lifecycle", content=body, headers=signed_headers(body)
    )

    assert response.status_code == 422
    assert response.json() == {"error": {"code": "invalid_request"}}
