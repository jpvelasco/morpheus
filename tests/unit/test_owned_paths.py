from __future__ import annotations

from pathlib import Path

import pytest

from morpheus.core.paths import OwnedPathError, OwnedPathResolver


def test_SEC_006_resolves_relative_paths_beneath_the_canonical_owned_root(tmp_path: Path) -> None:
    resolver = OwnedPathResolver(tmp_path / "owned" / "nested" / "..")

    resolved = resolver.resolve_relative("data/morpheus.sqlite3")

    assert resolver.root == (tmp_path / "owned").resolve()
    assert resolved == resolver.root / "data" / "morpheus.sqlite3"


@pytest.mark.parametrize("value", ["../outside", "/var/outside", "", ".", "dir\\file"])
def test_SEC_006_rejects_paths_that_escape_or_are_not_relative_children(
    tmp_path: Path, value: str
) -> None:
    resolver = OwnedPathResolver(tmp_path / "owned")

    with pytest.raises(OwnedPathError):
        resolver.resolve_relative(value)


def test_SEC_006_rejects_an_existing_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "owned"
    root.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    (root / "link").symlink_to(external, target_is_directory=True)
    resolver = OwnedPathResolver(root)

    with pytest.raises(OwnedPathError, match="escapes"):
        resolver.resolve_relative("link/output.txt")


def test_SEC_006_creates_restore_staging_only_at_the_allowlisted_sibling(tmp_path: Path) -> None:
    resolver = OwnedPathResolver(tmp_path / "owned")

    staging = resolver.create_staging_directory("restore")

    assert staging.parent == resolver.root.parent
    assert staging.name.startswith(".owned.restore-")
    staging.rmdir()


def test_SEC_006_resolves_archives_only_in_the_dedicated_owned_workspace(tmp_path: Path) -> None:
    resolver = OwnedPathResolver(tmp_path / "owned")

    archive = resolver.workspace_path("backups", "release.zip")

    assert archive == tmp_path / ".owned.backups" / "release.zip"
    with pytest.raises(OwnedPathError, match="escapes"):
        resolver.workspace_path("backups", tmp_path / "outside.zip")
