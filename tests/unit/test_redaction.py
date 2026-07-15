from __future__ import annotations

from morpheus.core.redaction import REDACTED, redact


def test_INV_005_redacts_nested_adversarial_secret_names() -> None:
    value = {
        "safe": "visible",
        "nested": {
            "Api-Key": "key-canary",
            "AUTHORIZATION": "Bearer auth-canary",
            "sessionSecret": "session-canary",
            "ordinary": [
                {"password": "password-canary"},
                {"latency_ms": 12.4},
            ],
        },
    }

    sanitized = redact(value)

    assert sanitized["safe"] == "visible"
    assert sanitized["nested"]["Api-Key"] == REDACTED
    assert sanitized["nested"]["AUTHORIZATION"] == REDACTED
    assert sanitized["nested"]["sessionSecret"] == REDACTED
    assert sanitized["nested"]["ordinary"][0]["password"] == REDACTED
    assert sanitized["nested"]["ordinary"][1]["latency_ms"] == 12.4
    assert "canary" not in str(sanitized)


def test_INV_005_redacts_sensitive_content_fields_but_not_counters() -> None:
    sanitized = redact(
        {
            "prompt": "prompt-canary",
            "response": "response-canary",
            "audio_content": "audio-canary",
            "response_tokens": 91,
            "content_type": "application/json",
        }
    )

    assert sanitized["prompt"] == REDACTED
    assert sanitized["response"] == REDACTED
    assert sanitized["audio_content"] == REDACTED
    assert sanitized["response_tokens"] == 91
    assert sanitized["content_type"] == "application/json"
