from __future__ import annotations

import pytest

from morpheus.core.events import (
    APPROVED_SOURCES,
    MAX_MESSAGE_CHARS,
    EventRecord,
    EventsError,
    bounded_limit,
    normalize_event,
    redact_text,
    sanitize_message,
    validate_event_filter,
)


def test_approved_sources_are_bounded_and_explicit() -> None:
    assert frozenset({"api", "engine", "agent"}) == APPROVED_SOURCES


def test_normalize_event_applies_redaction_before_persisting() -> None:
    event = normalize_event(
        source="engine",
        severity="warn",
        message="request failed with api_key=sk-abc123 and Bearer eyJhbGciOiJIUzI1NiJ9",
    )
    assert "sk-abc123" not in event.message
    assert "eyJhbGciOiJIUzI1NiJ9" not in event.message
    assert event.message.startswith("request failed")


def test_normalize_event_redacts_url_credentials() -> None:
    event = normalize_event(
        source="api", severity="info", message="calling https://alice:s3cret@gateway/v1"
    )
    assert "alice" not in event.message
    assert "s3cret" not in event.message
    assert "https://[REDACTED]@gateway/v1" in event.message


def test_normalize_event_rejects_unapproved_sources() -> None:
    with pytest.raises(EventsError):
        normalize_event(source="bogus", severity="info", message="x")


def test_normalize_event_normalizes_severity() -> None:
    assert normalize_event(source="api", severity="ERROR", message="x").severity == "error"
    assert normalize_event(source="api", severity="warning", message="x").severity == "warn"
    with pytest.raises(EventsError):
        normalize_event(source="api", severity="critical", message="x")


def test_normalize_event_collapses_forged_log_lines() -> None:
    event = normalize_event(
        source="agent",
        severity="info",
        message="legit\n2026-01-01T00:00:00+00:00 INFO forged entry",
    )
    assert "\n" not in event.message
    assert "forged entry" in event.message


def test_normalize_event_strips_ansi_escapes() -> None:
    event = normalize_event(source="engine", severity="info", message="\x1b[31mred\x1b[0m text")
    assert "\x1b" not in event.message
    assert event.message == "red text"


def test_normalize_event_truncates_oversized_messages() -> None:
    event = normalize_event(
        source="engine", severity="error", message="x" * (MAX_MESSAGE_CHARS + 100)
    )
    assert len(event.message) <= MAX_MESSAGE_CHARS
    assert event.message.endswith("...")


def test_normalize_event_keeps_correlation_and_links() -> None:
    event = normalize_event(
        source="api",
        severity="error",
        message="timeout",
        correlation_id="corr-123",
        deployment_id="deploy-1",
        campaign_id="campaign-9",
    )
    assert event.correlation_id == "corr-123"
    assert event.deployment_id == "deploy-1"
    assert event.campaign_id == "campaign-9"


def test_normalize_event_rejects_malformed_links() -> None:
    with pytest.raises(EventsError):
        normalize_event(source="api", severity="info", message="x", correlation_id="bad id!")


def test_normalize_event_rejects_naive_recorded_at() -> None:
    with pytest.raises(EventsError):
        normalize_event(
            source="api", severity="info", message="x", recorded_at="2026-08-15T12:00:00"
        )


def test_normalize_event_defaults_recorded_at_to_now() -> None:
    event = normalize_event(source="api", severity="info", message="x")
    assert event.recorded_at.endswith("+00:00")


def test_bounded_limit_clamps_to_query_bounds() -> None:
    assert bounded_limit(0) == 1
    assert bounded_limit(50) == 50
    assert bounded_limit(5_000) == 200


def test_validate_event_filter_rejects_unknown_values() -> None:
    validate_event_filter(
        source="engine", severity="warn", correlation_id="c-1", since="2026-01-01T00:00:00+00:00"
    )
    with pytest.raises(EventsError):
        validate_event_filter(source="bogus")
    with pytest.raises(EventsError):
        validate_event_filter(severity="fatal")
    with pytest.raises(EventsError):
        validate_event_filter(correlation_id="bad id")
    with pytest.raises(EventsError):
        validate_event_filter(since="not-a-time")


def test_event_record_rejects_blank_message() -> None:
    with pytest.raises(EventsError):
        EventRecord(
            recorded_at="2026-08-15T12:00:00+00:00", source="api", severity="info", message="   "
        )


def test_redact_text_and_sanitize_message_are_exported() -> None:
    assert redact_text("Bearer abc123") != "Bearer abc123"
    assert sanitize_message("a\nb") == "a b"
