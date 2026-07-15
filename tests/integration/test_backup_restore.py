from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from morpheus.ops.archive import ArchiveValidationError, BackupManager

pytestmark = pytest.mark.integration


def test_OPS_001_backup_contains_only_declared_owned_paths(tmp_path: Path) -> None:
    owned = tmp_path / "owned"
    owned.mkdir()
    (owned / "config.yaml").write_text("setting: safe\n", encoding="utf-8")
    external = tmp_path / "external-secret.txt"
    external.write_text("must-not-archive", encoding="utf-8")
    manager = BackupManager(owned_root=owned)
    archive = manager.create(tmp_path / "backup.zip")

    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        assert "files/config.yaml" in names
        assert "manifest.json" in names
        assert all("external" not in name for name in names)


def test_OPS_002_restore_round_trip_is_atomic(tmp_path: Path) -> None:
    owned = tmp_path / "owned"
    owned.mkdir()
    source = owned / "state.json"
    source.write_text('{"version":1}', encoding="utf-8")
    manager = BackupManager(owned_root=owned)
    archive = manager.create(tmp_path / "backup.zip")
    source.write_text('{"version":2}', encoding="utf-8")

    manager.restore(archive)
    assert source.read_text(encoding="utf-8") == '{"version":1}'


@pytest.mark.parametrize("entry", ["../escape", "/absolute", "files/../../escape"])
def test_SEC_006_restore_rejects_path_escape(tmp_path: Path, entry: str) -> None:
    owned = tmp_path / "owned"
    owned.mkdir()
    archive = tmp_path / "malicious.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(entry, "canary")
    with pytest.raises(ArchiveValidationError, match="unsafe archive path"):
        BackupManager(owned_root=owned).restore(archive)


def test_OPS_002_restore_rejects_corrupt_checksum_without_changing_state(tmp_path: Path) -> None:
    owned = tmp_path / "owned"
    owned.mkdir()
    state = owned / "state.txt"
    state.write_text("current", encoding="utf-8")
    archive = tmp_path / "corrupt.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("manifest.json", '{"version":1,"files":{"state.txt":"deadbeef"}}')
        bundle.writestr("files/state.txt", "replacement")
    with pytest.raises(ArchiveValidationError, match="checksum"):
        BackupManager(owned_root=owned).restore(archive)
    assert state.read_text(encoding="utf-8") == "current"
