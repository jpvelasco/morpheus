from __future__ import annotations

import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from morpheus.ops import archive as archive_module
from morpheus.ops.archive import ArchiveValidationError, BackupManager

MORPHEUS_OWNED_REQUIREMENTS = frozenset({"OPS-001", "OPS-002", "SEC-006"})
pytestmark = pytest.mark.integration


def test_OPS_001_backup_contains_only_declared_owned_paths(tmp_path: Path) -> None:
    owned = tmp_path / "owned"
    owned.mkdir()
    (owned / "config.yaml").write_text("setting: safe\n", encoding="utf-8")
    external = tmp_path / "external-secret.txt"
    external.write_text("must-not-archive", encoding="utf-8")
    manager = BackupManager(owned_root=owned)
    archive = manager.create(Path("backup.zip"))

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
    archive = manager.create(Path("backup.zip"))
    source.write_text('{"version":2}', encoding="utf-8")

    manager.restore(archive)
    assert source.read_text(encoding="utf-8") == '{"version":1}'
    assert archive.is_file()


@pytest.mark.parametrize("entry", ["../escape", "/absolute", "files/../../escape"])
def test_SEC_006_restore_rejects_path_escape(tmp_path: Path, entry: str) -> None:
    owned = tmp_path / "owned"
    owned.mkdir()
    archive = tmp_path / ".owned.backups" / "malicious.zip"
    archive.parent.mkdir()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(entry, "canary")
    with pytest.raises(ArchiveValidationError, match="unsafe archive path"):
        BackupManager(owned_root=owned).restore(archive)


def test_OPS_002_restore_rejects_corrupt_checksum_without_changing_state(tmp_path: Path) -> None:
    owned = tmp_path / "owned"
    owned.mkdir()
    state = owned / "state.txt"
    state.write_text("current", encoding="utf-8")
    archive = tmp_path / ".owned.backups" / "corrupt.zip"
    archive.parent.mkdir()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(
            "manifest.json",
            '{"version":2,"schema_version":1,"files":{"state.txt":"deadbeef"}}',
        )
        bundle.writestr("files/state.txt", "replacement")
    with pytest.raises(ArchiveValidationError, match="checksum"):
        BackupManager(owned_root=owned).restore(archive)
    assert state.read_text(encoding="utf-8") == "current"


def test_SEC_006_backup_rejects_an_archive_destination_outside_the_owned_root(
    tmp_path: Path,
) -> None:
    owned = tmp_path / "owned"
    owned.mkdir()

    with pytest.raises(ValueError, match="escapes"):
        BackupManager(owned_root=owned).create(tmp_path / "outside.zip")


def test_OPS_002_restore_preflight_reports_compatible_archive_without_mutating_state(
    tmp_path: Path,
) -> None:
    owned = tmp_path / "owned"
    owned.mkdir()
    state = owned / "state.txt"
    state.write_text("saved", encoding="utf-8")
    manager = BackupManager(owned_root=owned)
    archive = manager.create(Path("backup.zip"))
    state.write_text("current", encoding="utf-8")

    preflight = manager.restore_preflight(archive)

    assert preflight.file_count == 1
    assert preflight.total_bytes == len(b"saved")
    assert preflight.schema_version == 1
    assert state.read_text(encoding="utf-8") == "current"


def test_OPS_002_restore_rejects_incompatible_schema_before_state_mutation(tmp_path: Path) -> None:
    owned = tmp_path / "owned"
    owned.mkdir()
    state = owned / "state.txt"
    state.write_text("current", encoding="utf-8")
    archive = tmp_path / ".owned.backups" / "incompatible.zip"
    archive.parent.mkdir()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("manifest.json", '{"version":2,"schema_version":99,"files":{}}')

    with pytest.raises(ArchiveValidationError, match="schema version"):
        BackupManager(owned_root=owned).restore(archive)
    assert state.read_text(encoding="utf-8") == "current"


def test_OPS_002_restore_rejects_insufficient_staging_space_before_state_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    owned = tmp_path / "owned"
    owned.mkdir()
    state = owned / "state.txt"
    state.write_text("saved", encoding="utf-8")
    manager = BackupManager(owned_root=owned)
    archive = manager.create(Path("backup.zip"))
    state.write_text("current", encoding="utf-8")
    monkeypatch.setattr(archive_module.shutil, "disk_usage", lambda path: SimpleNamespace(free=0))

    with pytest.raises(ArchiveValidationError, match="insufficient free space"):
        manager.restore(archive)
    assert state.read_text(encoding="utf-8") == "current"


def test_OPS_002_restore_rolls_back_when_root_swap_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    owned = tmp_path / "owned"
    owned.mkdir()
    state = owned / "state.txt"
    state.write_text("saved", encoding="utf-8")
    manager = BackupManager(owned_root=owned)
    archive = manager.create(Path("backup.zip"))
    state.write_text("current", encoding="utf-8")
    original_replace = archive_module.os.replace
    calls = 0

    def replace(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected root swap failure")
        original_replace(source, destination)

    monkeypatch.setattr(archive_module.os, "replace", replace)

    with pytest.raises(OSError, match="injected"):
        manager.restore(archive)
    assert state.read_text(encoding="utf-8") == "current"
