from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

FEATURE_FIELDS = {
    "search": "enable_search",
    "voice": "enable_voice",
    "telemetry": "enable_telemetry",
    "workflows": "enable_workflows",
    "research": "enable_research",
    "image_generation": "enable_image_generation",
}


class MorpheusSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str = Field(default="morpheus", pattern=r"^[a-z][a-z0-9_-]{1,62}$")
    bind_address: str = "127.0.0.1"
    allow_lan: bool = False
    api_port: int = Field(default=7400, ge=1, le=65535)
    dashboard_port: int = Field(default=7401, ge=1, le=65535)
    agent_port: int = Field(default=7402, ge=1, le=65535)
    runtime_agent_url: str | None = None
    runtime_agent_socket: Path | None = None
    release_version: str = ""
    source_commit: str = Field(default="", pattern=r"^(?:|[0-9a-f]{40,64})$")
    data_dir: Path = Path("./data")
    llm_base_url: str = "http://qwopus-coder:8000/v1"
    llm_model: str = "qwen36-27b-nvfp4"
    external_docker_network: str = "ai_default"
    api_key: SecretStr = SecretStr("")
    upstream_api_key: SecretStr = SecretStr("")
    agent_key: SecretStr = SecretStr("")
    session_secret: SecretStr = SecretStr("")
    session_ttl_seconds: int = Field(default=900, ge=60, le=86_400)
    session_cookie_secure: bool = True
    max_concurrent_requests: int = Field(default=16, ge=1, le=256)
    max_requests_per_minute: int = Field(default=120, ge=1, le=10_000)
    enable_search: bool = False
    enable_voice: bool = False
    enable_telemetry: bool = False
    enable_workflows: bool = False
    enable_research: bool = False
    enable_image_generation: bool = False
    request_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    max_request_bytes: int = Field(default=2_097_152, ge=1024, le=64 * 1024 * 1024)
    telemetry_retention_days: int = Field(default=30, ge=1, le=365)

    @field_validator("bind_address")
    @classmethod
    def validate_bind_address(cls, value: str) -> str:
        try:
            ipaddress.ip_address(value)
        except ValueError as error:
            raise ValueError("bind_address must be an IPv4 or IPv6 address") from error
        return value

    @field_validator("llm_base_url")
    @classmethod
    def validate_llm_base_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("llm_base_url must use http or https")
        if not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("llm_base_url must have a host and no embedded credentials")
        if parsed.query or parsed.fragment or parsed.path.rstrip("/") != "/v1":
            raise ValueError("llm_base_url must contain the /v1 API base path exactly once")
        return value.rstrip("/")

    @field_validator("runtime_agent_url", mode="before")
    @classmethod
    def validate_runtime_agent_url(cls, value: Any) -> str | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise ValueError("runtime_agent_url must be a string")
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("runtime_agent_url must use http or https")
        if not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("runtime_agent_url must have a host and no embedded credentials")
        if parsed.query or parsed.fragment or parsed.path.rstrip("/"):
            raise ValueError("runtime_agent_url must not contain a path, query, or fragment")
        return value.rstrip("/")

    @field_validator("runtime_agent_socket", mode="before")
    @classmethod
    def validate_runtime_agent_socket(cls, value: Any) -> Path | None:
        if value is None or value == "":
            return None
        path = Path(value)
        if not path.is_absolute():
            raise ValueError("runtime_agent_socket must be an absolute path")
        return path

    @field_validator("session_secret")
    @classmethod
    def validate_session_secret(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if secret and len(secret.encode()) < 16:
            raise ValueError("session_secret must contain at least 16 bytes when configured")
        return value

    @model_validator(mode="after")
    def validate_network_posture(self) -> MorpheusSettings:
        address = ipaddress.ip_address(self.bind_address)
        if not address.is_loopback and not self.allow_lan:
            raise ValueError("non-loopback binding requires allow_lan=true")
        if len({self.api_port, self.dashboard_port, self.agent_port}) != 3:
            raise ValueError("api, dashboard, and agent ports must be distinct")
        if self.runtime_agent_url and self.runtime_agent_socket:
            raise ValueError("configure only one runtime agent endpoint")
        return self

    def features(self) -> dict[str, bool]:
        return {name: bool(getattr(self, field)) for name, field in FEATURE_FIELDS.items()}

    def public_dict(self) -> dict[str, Any]:
        excluded = {"api_key", "upstream_api_key", "agent_key", "session_secret"}
        public = self.model_dump(mode="json", exclude=excluded)
        public["secrets_configured"] = {
            "agent_key": bool(self.agent_key.get_secret_value()),
            "api_key": bool(self.api_key.get_secret_value()),
            "session_secret": bool(self.session_secret.get_secret_value()),
        }
        return public

    def startup_report(self) -> dict[str, Any]:
        public = self.public_dict()
        public["features"] = self.features()
        public.pop("secrets_configured", None)
        return public


def _normalize_source(values: Mapping[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    known = set(MorpheusSettings.model_fields)
    for key, value in values.items():
        field = key.removeprefix("MORPHEUS_").lower()
        if field in known and value is not None:
            normalized[field] = value
    return normalized


def _read_yaml(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("configuration file must contain a mapping")
    return _normalize_source(data)


def load_settings(
    *,
    overrides: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    env_file: Path | None = Path(".env"),
    config_file: Path | None = Path("deploy/config/morpheus.yaml"),
) -> MorpheusSettings:
    values: dict[str, Any] = {}
    values.update(_read_yaml(config_file))
    if env_file is not None and env_file.exists():
        values.update(_normalize_source(dotenv_values(env_file)))
    values.update(_normalize_source(os.environ if environ is None else environ))
    values.update(_normalize_source(overrides or {}))
    return MorpheusSettings.model_validate(values)
