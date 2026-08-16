"""Typed public settings catalog (OUI-005).

The catalog is derived from the settings model: every operator-editable
field is described with its kind, current value, source, default,
validation, and restart requirement. Secret fields are reported as
configured/unconfigured only and can never be edited through the operations
surface; they must be set in the secret env file. Validation of proposed
changes lives in the API layer next to the pydantic settings model, so this
module stays pure and dependency-free.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from morpheus.config import MorpheusSettings

#: Field keys the operator may never edit through the operations surface.
SECRET_FIELDS = ("api_key", "upstream_api_key", "agent_key", "session_secret", "diagnosis_api_key")

#: Build identity fields that are public but never operator-editable.
NON_EDITABLE_FIELDS = ("release_version", "source_commit")

URL_FIELDS = ("llm_base_url", "vllm_metrics_url", "runtime_agent_url", "diagnosis_endpoint")
PORT_FIELDS = ("api_port", "dashboard_port", "agent_port", "telemetry_port")

LABELS: dict[str, str] = {
    "project_id": "Project ID",
    "bind_address": "Bind address",
    "allow_lan": "Allow LAN",
    "api_port": "API port",
    "dashboard_port": "Dashboard port",
    "agent_port": "Runtime agent port",
    "telemetry_port": "Telemetry port",
    "runtime_agent_url": "Runtime agent URL",
    "runtime_agent_socket": "Runtime agent socket",
    "data_dir": "Data directory",
    "llm_base_url": "Inference base URL",
    "llm_model": "Inference model",
    "external_docker_network": "External Docker network",
    "session_ttl_seconds": "Session lifetime (seconds)",
    "session_cookie_secure": "Secure session cookie",
    "max_concurrent_requests": "Max concurrent requests",
    "max_requests_per_minute": "Max requests per minute",
    "retry_max_attempts": "Retry attempts",
    "retry_deadline_seconds": "Retry deadline (seconds)",
    "request_timeout_seconds": "Request timeout (seconds)",
    "max_request_bytes": "Max request bytes",
    "telemetry_retention_days": "Telemetry retention (days)",
    "metrics_retention_days": "Metrics retention (days)",
    "events_retention_days": "Events retention (days)",
    "metrics_collection_interval_seconds": "Metrics collection interval (seconds)",
    "vllm_metrics_url": "vLLM metrics URL",
    "enable_search": "Enable search",
    "enable_voice": "Enable voice",
    "enable_telemetry": "Enable telemetry",
    "enable_workflows": "Enable workflows",
    "enable_research": "Enable research",
    "enable_image_generation": "Enable image generation",
    "enable_lifecycle": "Enable runtime lifecycle",
    "lifecycle_deployment_root": "Lifecycle deployment root",
    "lifecycle_lab_authorized": "Lifecycle lab authorized",
    "diagnosis_mode": "Diagnosis provider mode",
    "diagnosis_provider": "Diagnosis provider name",
    "diagnosis_endpoint": "Diagnosis provider endpoint",
    "diagnosis_timeout_ms": "Diagnosis timeout (milliseconds)",
    "diagnosis_max_cost": "Diagnosis cost budget",
    "diagnosis_retention": "Diagnosis data retention",
    "diagnosis_consent": "Diagnosis data consent",
    "diagnosis_api_key": "Diagnosis API key",
    "access_profile": "Access profile",
    "api_key": "API key",
    "upstream_api_key": "Upstream API key",
    "agent_key": "Runtime agent key",
    "session_secret": "Session secret",
}

DESCRIPTIONS: dict[str, str] = {
    "project_id": "Unique project identifier used for ownership labels.",
    "bind_address": "Address the services bind to; loopback by default.",
    "allow_lan": "Allow non-loopback binding when a LAN bind address is set.",
    "api_port": "Port of the versioned Control API.",
    "dashboard_port": "Port of the operator dashboard.",
    "agent_port": "Port of the runtime agent.",
    "telemetry_port": "Port of the telemetry service.",
    "runtime_agent_url": "HTTP endpoint of the runtime agent.",
    "runtime_agent_socket": "Unix socket path of the runtime agent.",
    "data_dir": "Owned root that stores runtime data and evidence.",
    "llm_base_url": "Inference API base URL ending in /v1.",
    "llm_model": "Model identifier requested from the inference service.",
    "external_docker_network": "Docker network hosting the inference service.",
    "session_ttl_seconds": "Browser session lifetime before re-authentication.",
    "session_cookie_secure": "Require HTTPS before issuing session cookies.",
    "max_concurrent_requests": "Bounded inference concurrency slot count.",
    "max_requests_per_minute": "Per-client request rate bound.",
    "retry_max_attempts": "Idempotent request retry bound.",
    "retry_deadline_seconds": "Total retry time bound per request.",
    "request_timeout_seconds": "Per-request response timeout.",
    "max_request_bytes": "Accepted request body size bound.",
    "telemetry_retention_days": "Retention window for telemetry records.",
    "metrics_retention_days": "Retention window for metric samples.",
    "events_retention_days": "Retention window for log and event records.",
    "metrics_collection_interval_seconds": "Sampling interval for metrics collection.",
    "vllm_metrics_url": "Prometheus metrics endpoint of a vLLM engine.",
    "enable_search": "Enable the search control.",
    "enable_voice": "Enable the voice control.",
    "enable_telemetry": "Enable the telemetry control.",
    "enable_workflows": "Enable the workflows control.",
    "enable_research": "Enable the research control.",
    "enable_image_generation": "Enable the image generation control.",
    "enable_lifecycle": "Enable runtime lifecycle management.",
    "lifecycle_deployment_root": "Fixed deployment root for lifecycle actions.",
    "lifecycle_lab_authorized": "Allow disposable-lab lifecycle actions.",
    "diagnosis_mode": "Disabled, local-model, or external-API diagnosis provider.",
    "diagnosis_provider": "Display name of the selected diagnosis provider.",
    "diagnosis_endpoint": "HTTP(S) endpoint of the external diagnosis provider.",
    "diagnosis_timeout_ms": "Provider response time bound before diagnosis fails.",
    "diagnosis_max_cost": "Estimated cost budget per diagnosis request.",
    "diagnosis_retention": "Provider-side retention implication of the evidence.",
    "diagnosis_consent": "Explicit consent that evidence may leave the host.",
    "diagnosis_api_key": "Key presented to the external diagnosis provider.",
    "access_profile": "Loopback-only or SSH-tunnel access posture.",
    "api_key": "Key that authenticates API requests.",
    "upstream_api_key": "Key presented to the upstream inference service.",
    "agent_key": "Key that authenticates runtime agent calls.",
    "session_secret": "Key material for signed browser sessions.",
}

VALIDATION_NOTES: dict[str, str] = {
    "project_id": "lowercase start, 2-63 chars of a-z 0-9 _ -",
    "bind_address": "IPv4 or IPv6 address; non-loopback requires allow_lan",
    "api_port": "integer 1-65535; must be distinct from other service ports",
    "dashboard_port": "integer 1-65535; must be distinct from other service ports",
    "agent_port": "integer 1-65535; must be distinct from other service ports",
    "telemetry_port": "integer 1-65535; must be distinct from other service ports",
    "llm_base_url": "http(s) URL with host, no credentials, path /v1",
    "vllm_metrics_url": "http(s) URL with host, no credentials, no path",
    "runtime_agent_url": "http(s) URL with host, no credentials, no path",
    "runtime_agent_socket": "absolute filesystem path",
    "data_dir": "must resolve inside an owned root",
    "external_docker_network": "2-128 chars of A-Z a-z 0-9 _ . -",
    "lifecycle_deployment_root": "absolute filesystem path",
    "session_secret": "at least 16 bytes when configured",
    "api_key": "set in the secret env file, never through the UI",
    "upstream_api_key": "set in the secret env file, never through the UI",
    "agent_key": "set in the secret env file, never through the UI",
    "session_ttl_seconds": "integer 60-86400",
    "max_concurrent_requests": "integer 1-256",
    "max_requests_per_minute": "integer 1-10000",
    "retry_max_attempts": "integer 1-5",
    "retry_deadline_seconds": "number 0-120",
    "request_timeout_seconds": "number 0-120",
    "max_request_bytes": "integer 1024-67108864",
    "telemetry_retention_days": "integer 1-365",
    "metrics_retention_days": "integer 1-365",
    "events_retention_days": "integer 1-365",
    "metrics_collection_interval_seconds": "integer 5-3600",
    "diagnosis_mode": "disabled, local, or external",
    "diagnosis_provider": "2-128 characters",
    "diagnosis_endpoint": "http(s) URL with host, no credentials, no query",
    "diagnosis_timeout_ms": "integer 1000-300000",
    "diagnosis_max_cost": "integer 0-1000000",
    "diagnosis_retention": "64 characters or fewer",
    "diagnosis_api_key": "set in the secret env file, never through the UI",
    "access_profile": "loopback or ssh_tunnel; requires a loopback bind address",
}


def _kind_for(key: str, field: Any) -> str:
    if key in SECRET_FIELDS:
        return "secret"
    if key in PORT_FIELDS:
        return "port"
    if key in URL_FIELDS:
        return "url"
    annotation = field.annotation
    if annotation is bool:
        return "bool"
    if annotation is int:
        return "int"
    if annotation is float:
        return "float"
    if annotation is Path:
        return "path"
    return "str"


def _is_secret(value: Any) -> bool:
    return hasattr(value, "get_secret_value")


def settings_catalog(
    settings: MorpheusSettings,
    *,
    sources: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Describe every public setting with its kind, value, source, and rules."""
    entries: list[dict[str, Any]] = []
    for key, field in sorted(MorpheusSettings.model_fields.items()):
        if key in NON_EDITABLE_FIELDS:
            continue
        kind = _kind_for(key, field)
        value = getattr(settings, key)
        if kind == "secret":
            configured = bool(value.get_secret_value()) if _is_secret(value) else bool(value)
            entries.append(
                {
                    "key": key,
                    "kind": kind,
                    "label": LABELS[key],
                    "description": DESCRIPTIONS[key],
                    "current": None,
                    "configured": configured,
                    "value_redacted": True,
                    "editable": False,
                    "source": sources.get(key, "default"),
                    "default": None,
                    "restart_required": True,
                    "validation": VALIDATION_NOTES.get(key, ""),
                }
            )
            continue
        entries.append(
            {
                "key": key,
                "kind": kind,
                "label": LABELS[key],
                "description": DESCRIPTIONS[key],
                "current": value,
                "configured": True,
                "value_redacted": False,
                "editable": True,
                "source": sources.get(key, "default"),
                "default": field.default,
                "restart_required": True,
                "validation": VALIDATION_NOTES.get(key, ""),
            }
        )
    return entries


def detect_sources(
    *,
    environ: Mapping[str, Any],
    env_file: Mapping[str, Any],
    config_file: Mapping[str, Any],
    overrides: Mapping[str, Any],
) -> dict[str, str]:
    """Attribute each setting to the layer that provides it.

    Precedence is overrides (pending restart) > environment > env file >
    config file > default. Keys are matched with the same normalization
    ``load_settings`` uses.
    """

    def normalize(values: Mapping[str, Any]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        known = set(MorpheusSettings.model_fields)
        for raw_key, raw_value in values.items():
            key = raw_key.removeprefix("MORPHEUS_").lower()
            if key in known and raw_value is not None:
                normalized[key] = str(raw_value)
        return normalized

    layers: list[tuple[str, dict[str, str]]] = [
        ("overrides_pending", normalize(overrides)),
        ("environment", normalize(environ)),
        ("env_file", normalize(env_file)),
        ("config_file", normalize(config_file)),
    ]
    result: dict[str, str] = {}
    for key in MorpheusSettings.model_fields:
        for source, values in layers:
            if key in values:
                result[key] = source
                break
        else:
            result[key] = "default"
    return result
