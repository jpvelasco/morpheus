from __future__ import annotations

import json

import pytest

from morpheus.adapters.persistence.settings import (
    SettingsJournal,
    SettingsJournalError,
)


def test_apply_writes_overrides_atomically_with_metadata(tmp_path) -> None:
    journal = SettingsJournal(tmp_path / "overrides.env")
    result = journal.apply({"api_port": "7411", "llm_model": "qwen2.5"})
    assert result["applied"] == {"api_port": "7411", "llm_model": "qwen2.5"}
    assert result["restart_required"] is True
    assert journal.current() == {"api_port": "7411", "llm_model": "qwen2.5"}
    assert journal.last_applied()["applied_at"]
    assert journal.last_applied()["restart_required"] is True


def test_apply_replaces_previous_values(tmp_path) -> None:
    journal = SettingsJournal(tmp_path / "overrides.env")
    journal.apply({"api_port": "7411"})
    journal.apply({"api_port": "7412", "llm_model": "qwen"})
    assert journal.current() == {"api_port": "7412", "llm_model": "qwen"}


def test_rollback_restores_the_previous_snapshot(tmp_path) -> None:
    journal = SettingsJournal(tmp_path / "overrides.env")
    journal.apply({"api_port": "7411"})
    journal.apply({"api_port": "7412"})
    assert journal.rollback() is True
    assert journal.current() == {"api_port": "7411"}
    assert journal.last_applied() is None
    assert journal.rollback_available() is False


def test_rollback_without_prior_snapshot_raises(tmp_path) -> None:
    journal = SettingsJournal(tmp_path / "overrides.env")
    journal.apply({"api_port": "7411"})
    with pytest.raises(SettingsJournalError):
        journal.rollback()
    assert journal.rollback_available() is False


def test_secret_fields_are_never_written(tmp_path) -> None:
    journal = SettingsJournal(tmp_path / "overrides.env")
    result = journal.apply({"api_port": "7411", "api_key": "should-not-persist"})
    assert "api_key" not in result["applied"]
    assert journal.current() == {"api_port": "7411"}
    raw = (tmp_path / "overrides.env").read_text(encoding="utf-8")
    assert "should-not-persist" not in raw
    assert "api_key" not in raw


def test_current_rejects_unknown_keys(tmp_path) -> None:
    journal = SettingsJournal(tmp_path / "overrides.env")
    with pytest.raises(SettingsJournalError):
        journal.apply({"not_a_setting": "x"})


def test_snapshot_file_is_restored_after_rollback(tmp_path) -> None:
    journal = SettingsJournal(tmp_path / "overrides.env")
    journal.apply({"api_port": "7411"})
    first_apply = (tmp_path / "overrides.env").read_text(encoding="utf-8")
    journal.apply({"api_port": "7412"})
    journal.rollback()
    assert (tmp_path / "overrides.env").read_text(encoding="utf-8") == first_apply
    meta = json.loads((tmp_path / "journal.json").read_text(encoding="utf-8"))
    assert meta["last_applied"] is None
