from __future__ import annotations

from morpheus.api.settings_plan import plan_settings
from morpheus.config import MorpheusSettings
from morpheus.core.settings_catalog import (
    detect_sources,
    settings_catalog,
)


def make_settings(**overrides: object) -> MorpheusSettings:
    return MorpheusSettings.model_validate(overrides)


def test_catalog_lists_editable_fields_with_kinds_and_restart() -> None:
    entries = settings_catalog(make_settings(), sources={})
    by_key = {entry["key"]: entry for entry in entries}
    assert by_key["api_port"]["kind"] == "port"
    assert by_key["api_port"]["restart_required"] is True
    assert by_key["enable_telemetry"]["kind"] == "bool"
    assert by_key["enable_telemetry"]["default"] is False
    assert by_key["llm_base_url"]["kind"] == "url"
    assert by_key["llm_model"]["kind"] == "str"
    assert by_key["metrics_retention_days"]["kind"] == "int"
    assert by_key["retry_deadline_seconds"]["kind"] == "float"
    assert by_key["data_dir"]["kind"] == "path"
    assert by_key["session_cookie_secure"]["kind"] == "bool"
    assert set(by_key) - {"api_key", "upstream_api_key", "agent_key", "session_secret"}


def test_catalog_reports_current_values_and_descriptions() -> None:
    settings = make_settings(api_port=7411, enable_telemetry=True, llm_model="qwen-test")
    by_key = {entry["key"]: entry for entry in settings_catalog(settings, sources={})}
    assert by_key["api_port"]["current"] == 7411
    assert by_key["enable_telemetry"]["current"] is True
    assert by_key["llm_model"]["current"] == "qwen-test"
    assert by_key["api_port"]["label"]
    assert by_key["api_port"]["description"]
    assert by_key["api_port"]["validation"]


def test_catalog_excludes_build_identity_fields() -> None:
    keys = {entry["key"] for entry in settings_catalog(make_settings(), sources={})}
    assert "release_version" not in keys
    assert "source_commit" not in keys


def test_catalog_reports_secrets_as_configured_only() -> None:
    settings = make_settings(api_key="set-in-env")
    by_key = {entry["key"]: entry for entry in settings_catalog(settings, sources={})}
    secret = by_key["api_key"]
    assert secret["kind"] == "secret"
    assert secret["current"] is None
    assert secret["configured"] is True
    assert secret["value_redacted"] is True
    assert not secret["editable"]
    assert by_key["agent_key"]["configured"] is False


def test_detect_sources_prefers_environment_over_files_over_default() -> None:
    sources = detect_sources(
        environ={"MORPHEUS_API_PORT": "7405"},
        env_file={"MORPHEUS_LLM_MODEL": "env-model"},
        config_file={"MORPHEUS_LLM_MODEL": "yaml-model", "MORPHEUS_ALLOW_LAN": "true"},
        overrides={"MORPHEUS_ENABLE_TELEMETRY": "true"},
    )
    assert sources["api_port"] == "environment"
    assert sources["llm_model"] == "env_file"
    assert sources["allow_lan"] == "config_file"
    assert sources["enable_telemetry"] == "overrides_pending"
    assert sources["project_id"] == "default"


def test_plan_reports_valid_diff_with_before_after_and_restart() -> None:
    plan = plan_settings(
        make_settings(api_port=7400),
        changes={"api_port": 7405},
    )
    assert plan["valid"] is True
    assert plan["restart_required"] is True
    assert plan["issues"] == []
    assert plan["changes"] == [
        {
            "key": "api_port",
            "before": 7400,
            "after": 7405,
            "restart_required": True,
            "kind": "port",
        }
    ]


def test_plan_reports_validation_issues_without_applying() -> None:
    plan = plan_settings(
        make_settings(),
        changes={"api_port": 99_999, "bind_address": "not-an-address"},
    )
    assert plan["valid"] is False
    assert plan["changes"] == []
    messages = {issue["key"]: issue["message"] for issue in plan["issues"]}
    assert "api_port" in messages
    assert "bind_address" in messages
    assert "less than or equal to 65535" in messages["api_port"]


def test_plan_rejects_unknown_and_secret_fields() -> None:
    plan = plan_settings(
        make_settings(),
        changes={"not_a_setting": 1, "api_key": "should-not-work"},
    )
    assert plan["valid"] is False
    codes = {issue["key"]: issue["code"] for issue in plan["issues"]}
    assert codes["not_a_setting"] == "unknown_setting"
    assert codes["api_key"] == "secret_not_editable"


def test_plan_rejects_cross_field_invariants() -> None:
    plan = plan_settings(
        make_settings(),
        changes={"bind_address": "0.0.0.0"},  # noqa: S104
    )
    assert plan["valid"] is False
    assert any(issue["key"] == "bind_address" for issue in plan["issues"])


def test_plan_with_no_changes_is_valid_and_empty() -> None:
    plan = plan_settings(make_settings(), changes={})
    assert plan["valid"] is True
    assert plan["changes"] == []
    assert plan["restart_required"] is False


def test_catalog_entries_are_stable_and_sorted() -> None:
    entries = settings_catalog(make_settings(), sources={})
    assert entries == sorted(entries, key=lambda entry: entry["key"])
