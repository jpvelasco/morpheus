from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from morpheus.agent.auth import AgentAuthenticationError, AgentAuthenticator, sign_request
from morpheus.agent.protocol import AgentLifecycleRequest, AgentOperation, AgentRequest
from morpheus.core.lifecycle import LifecycleAction

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
KEY = b"agent-test-key-with-enough-entropy"


def request_body(operation: AgentOperation = AgentOperation.HOST_SUMMARY) -> bytes:
    return AgentRequest(request_id="req-123", operation=operation).model_dump_json().encode()


def test_SEC_001_agent_accepts_valid_signature_once() -> None:
    body = request_body()
    timestamp = str(int(NOW.timestamp()))
    nonce = "unique-nonce"
    signature = sign_request(KEY, timestamp=timestamp, nonce=nonce, body=body)
    authenticator = AgentAuthenticator(KEY, max_skew=timedelta(seconds=30))

    authenticator.verify(timestamp=timestamp, nonce=nonce, signature=signature, body=body, now=NOW)
    with pytest.raises(AgentAuthenticationError, match="replayed"):
        authenticator.verify(
            timestamp=timestamp, nonce=nonce, signature=signature, body=body, now=NOW
        )


@pytest.mark.parametrize("offset", [-31, 31])
def test_SEC_001_agent_rejects_expired_or_future_request(offset: int) -> None:
    body = request_body()
    timestamp = str(int((NOW + timedelta(seconds=offset)).timestamp()))
    signature = sign_request(KEY, timestamp=timestamp, nonce="nonce", body=body)
    authenticator = AgentAuthenticator(KEY, max_skew=timedelta(seconds=30))
    with pytest.raises(AgentAuthenticationError, match="timestamp"):
        authenticator.verify(
            timestamp=timestamp,
            nonce="nonce",
            signature=signature,
            body=body,
            now=NOW,
        )


def test_SEC_001_agent_rejects_modified_body() -> None:
    body = request_body()
    timestamp = str(int(NOW.timestamp()))
    signature = sign_request(KEY, timestamp=timestamp, nonce="nonce", body=body)
    authenticator = AgentAuthenticator(KEY)
    with pytest.raises(AgentAuthenticationError, match="signature"):
        authenticator.verify(
            timestamp=timestamp,
            nonce="nonce",
            signature=signature,
            body=request_body(AgentOperation.GPU_SUMMARY),
            now=NOW,
        )


def test_INV_003_agent_protocol_has_no_arbitrary_command_field() -> None:
    assert set(AgentRequest.model_fields) == {"request_id", "operation"}
    assert "shell" not in {operation.value for operation in AgentOperation}
    assert "exec" not in {operation.value for operation in AgentOperation}


def test_SEC_002_lifecycle_protocol_has_only_fixed_identifiers_and_actions() -> None:
    assert set(AgentLifecycleRequest.model_fields) == {
        "request_id",
        "action",
        "version",
        "backup_id",
        "confirmation",
        # RUNM-001: optional canonical plan identity; observed markers rejected.
        "plan_id",
    }
    assert {action.value for action in LifecycleAction} == {
        "backup",
        "install",
        "migrate",
        "restore-preflight",
        "rollback",
        "start",
        "stop",
        "uninstall",
        "upgrade",
        "validate",
    }
    assert not {"command", "path", "resource", "shell", "target"} & set(
        AgentLifecycleRequest.model_fields
    )
