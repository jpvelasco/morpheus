from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

APPROVED_SOURCES = frozenset({"api", "engine", "agent"})
SEVERITIES = frozenset({"info", "warn", "error"})
SEVERITY_ALIASES = {"warning": "warn"}
MAX_MESSAGE_CHARS = 512
MAX_EVENT_QUERY_LIMIT = 200

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_URL_CREDENTIALS = re.compile(r"(https?://)([^/@\s]+)@")
_BEARER_TOKEN = re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]+")
_KEY_VALUE_SECRET = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?key|password|secret|token)\s*[:=]\s*[^\s,;}\"]+"
)
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
REDACTED = "[REDACTED]"


class EventsError(ValueError):
    pass


def _bounded(value: str, what: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise EventsError(f"invalid {what}: {value!r}")
    return value


def _parse_iso(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise EventsError(f"invalid ISO timestamp: {value!r}") from error
    if parsed.tzinfo is None:
        raise EventsError(f"timestamp must be timezone-aware: {value!r}")
    return parsed.astimezone(UTC)


def redact_text(text: str) -> str:
    text = _ANSI_ESCAPE.sub("", text)
    text = _URL_CREDENTIALS.sub(r"\1[REDACTED]@", text)
    text = _BEARER_TOKEN.sub(REDACTED, text)
    return _KEY_VALUE_SECRET.sub(REDACTED, text)


def sanitize_message(text: str) -> str:
    text = _CONTROL_CHARS.sub("", text)
    text = " ".join(text.split())
    if len(text) > MAX_MESSAGE_CHARS:
        text = text[: MAX_MESSAGE_CHARS - 3] + "..."
    return text


@dataclass(frozen=True, slots=True)
class EventRecord:
    recorded_at: str
    source: str
    severity: str
    message: str
    correlation_id: str | None = None
    deployment_id: str | None = None
    campaign_id: str | None = None

    def __post_init__(self) -> None:
        _parse_iso(self.recorded_at)
        if self.source not in APPROVED_SOURCES:
            raise EventsError(f"unapproved event source: {self.source!r}")
        if self.severity not in SEVERITIES:
            raise EventsError(f"unknown event severity: {self.severity!r}")
        if not self.message.strip():
            raise EventsError("event message must not be blank")
        if self.correlation_id is not None:
            _bounded(self.correlation_id, "correlation id")
        if self.deployment_id is not None:
            _bounded(self.deployment_id, "deployment id")
        if self.campaign_id is not None:
            _bounded(self.campaign_id, "campaign id")


def normalize_event(
    *,
    source: str,
    severity: str,
    message: str,
    correlation_id: str | None = None,
    deployment_id: str | None = None,
    campaign_id: str | None = None,
    recorded_at: str | None = None,
) -> EventRecord:
    normalized = severity.lower()
    normalized = SEVERITY_ALIASES.get(normalized, normalized)
    if source not in APPROVED_SOURCES:
        raise EventsError(f"unapproved event source: {source!r}")
    if normalized not in SEVERITIES:
        raise EventsError(f"unknown event severity: {severity!r}")
    return EventRecord(
        recorded_at=recorded_at or datetime.now(UTC).isoformat(),
        source=source,
        severity=normalized,
        message=sanitize_message(redact_text(message)),
        correlation_id=correlation_id,
        deployment_id=deployment_id,
        campaign_id=campaign_id,
    )


def bounded_limit(limit: int) -> int:
    return min(max(limit, 1), MAX_EVENT_QUERY_LIMIT)


def validate_event_filter(
    *,
    source: str | None = None,
    severity: str | None = None,
    correlation_id: str | None = None,
    since: str | None = None,
) -> None:
    if source is not None and source not in APPROVED_SOURCES:
        raise EventsError(f"unapproved event source: {source!r}")
    if severity is not None and severity not in SEVERITIES:
        raise EventsError(f"unknown event severity: {severity!r}")
    if correlation_id is not None:
        _bounded(correlation_id, "correlation id")
    if since is not None:
        _parse_iso(since)
