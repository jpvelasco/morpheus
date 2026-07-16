from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from morpheus.config import MorpheusSettings, load_settings


def test_CFG_001_configuration_precedence(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("api_port: 7100\nllm_base_url: http://config-llm:8000/v1\n", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text("MORPHEUS_API_PORT=7200\n", encoding="utf-8")

    settings = load_settings(
        config_file=config,
        env_file=env_file,
        environ={"MORPHEUS_API_PORT": "7300"},
        overrides={"api_port": 7400},
    )

    assert settings.api_port == 7400
    assert str(settings.llm_base_url) == "http://config-llm:8000/v1"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://llm.local/v1",
        "http://user:password@llm.local/v1",
        "http://llm.local",
        "http://llm.local/v1/v1",
        "http://llm.local/v1?token=secret",
        "http:///v1",
    ],
)
def test_CFG_003_rejects_unsafe_or_ambiguous_endpoint(url: str) -> None:
    with pytest.raises(ValidationError):
        MorpheusSettings(llm_base_url=url)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8082/v1",
        "https://[::1]:8082/v1",
        "http://qwopus-coder:8000/v1",
    ],
)
def test_CFG_003_accepts_supported_endpoint_shapes(url: str) -> None:
    assert str(MorpheusSettings(llm_base_url=url).llm_base_url) == url


def test_CFG_002_public_configuration_excludes_secret_values() -> None:
    settings = MorpheusSettings(
        api_key="api-canary",
        agent_key="agent-canary",
        session_secret="session-secret-canary",
    )

    public = settings.public_dict()
    serialized = str(public)
    assert "canary" not in serialized
    assert public["secrets_configured"] == {
        "agent_key": True,
        "api_key": True,
        "session_secret": True,
    }


@pytest.mark.parametrize("ttl_seconds", [59, 86_401])
def test_SEC_004_rejects_browser_session_lifetime_outside_safe_bounds(ttl_seconds: int) -> None:
    with pytest.raises(ValidationError):
        MorpheusSettings(session_ttl_seconds=ttl_seconds)


def test_SEC_004_rejects_an_unsafe_browser_session_secret() -> None:
    with pytest.raises(ValidationError, match="at least 16 bytes"):
        MorpheusSettings(session_secret="too-short")


def test_SEC_004_browser_sessions_default_to_short_lived_secure_cookies() -> None:
    settings = MorpheusSettings()

    assert settings.session_ttl_seconds == 900
    assert settings.session_cookie_secure is True


@pytest.mark.parametrize("limit", [0, 257])
def test_SEC_003_rejects_concurrency_limits_outside_safe_bounds(limit: int) -> None:
    with pytest.raises(ValidationError):
        MorpheusSettings(max_concurrent_requests=limit)


@pytest.mark.parametrize("limit", [0, 10_001])
def test_SEC_003_rejects_rate_limits_outside_safe_bounds(limit: int) -> None:
    with pytest.raises(ValidationError):
        MorpheusSettings(max_requests_per_minute=limit)


def test_CFG_004_startup_report_has_feature_decisions() -> None:
    settings = MorpheusSettings(enable_search=True)
    report = settings.startup_report()

    assert report["features"]["search"] is True
    assert report["features"]["image_generation"] is False
    assert "api_key" not in report


def test_SEC_006_canonicalizes_the_configured_owned_data_root(tmp_path: Path) -> None:
    settings = MorpheusSettings(data_dir=tmp_path / "owned" / "nested" / "..")

    assert settings.data_dir == (tmp_path / "owned").resolve()


@pytest.mark.parametrize(
    "url",
    [
        "unix:///run/morpheus.sock",
        "http://user:password@127.0.0.1:7402",
        "http://127.0.0.1:7402/v1",
        "http://127.0.0.1:7402?token=secret",
    ],
)
def test_CFG_003_rejects_unsafe_runtime_agent_endpoint(url: str) -> None:
    with pytest.raises(ValidationError):
        MorpheusSettings(runtime_agent_url=url)


def test_CFG_003_accepts_empty_or_http_runtime_agent_endpoint() -> None:
    assert MorpheusSettings(runtime_agent_url="").runtime_agent_url is None
    assert (
        MorpheusSettings(runtime_agent_url="http://127.0.0.1:7402/").runtime_agent_url
        == "http://127.0.0.1:7402"
    )


def test_CFG_003_rejects_multiple_runtime_agent_transports() -> None:
    with pytest.raises(ValidationError, match="only one runtime agent"):
        MorpheusSettings(
            runtime_agent_url="http://127.0.0.1:7402",
            runtime_agent_socket="/run/morpheus-agent/agent.sock",
        )


def test_CFG_003_runtime_agent_socket_is_optional_and_absolute() -> None:
    assert MorpheusSettings(runtime_agent_socket="").runtime_agent_socket is None
    with pytest.raises(ValidationError, match="absolute path"):
        MorpheusSettings(runtime_agent_socket="agent.sock")
