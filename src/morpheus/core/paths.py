from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path


class OwnedPathError(ValueError):
    """A path is outside the declared Morpheus-owned workspace."""


@dataclass(frozen=True, slots=True)
class OwnedPathResolver:
    """Resolve application paths beneath one canonical, owned root.

    Relative inputs are always interpreted beneath ``root``.  Absolute inputs
    are accepted only when their canonical location remains beneath that root,
    which makes it safe for callers to retain an already-resolved path.
    """

    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", self.root.expanduser().resolve())

    def resolve(self, value: Path | str) -> Path:
        path = Path(value).expanduser()
        candidate = path if path.is_absolute() else self.root / path
        resolved = candidate.resolve(strict=False)
        if resolved != self.root and self.root not in resolved.parents:
            raise OwnedPathError("path escapes the Morpheus-owned root")
        return resolved

    def resolve_relative(self, value: Path | str) -> Path:
        path = Path(value)
        text = str(value)
        if (
            not text
            or bool(path.root)
            or bool(path.drive)
            or path == Path(".")
            or ".." in path.parts
            or (os.sep != "\\" and "\\" in text)
        ):
            raise OwnedPathError(
                "path must be a non-empty relative child of the Morpheus-owned root"
            )
        return self.resolve(path)

    def staging_path(self, name: str) -> Path:
        """Return an allowlisted sibling workspace for an atomic root swap."""
        if not re.fullmatch(r"[a-z0-9-]+", name):
            raise OwnedPathError("invalid Morpheus staging workspace name")
        candidate = self.root.parent / f".{self.root.name}.{name}"
        if candidate.is_symlink():
            raise OwnedPathError("Morpheus staging workspace must not be a symbolic link")
        return candidate

    def workspace_path(self, workspace: str, value: Path | str) -> Path:
        """Resolve a path inside a fixed, owned sibling workspace."""
        root = self.staging_path(workspace)
        return OwnedPathResolver(root).resolve(value)

    def create_staging_directory(self, name: str) -> Path:
        """Create an exclusive allowlisted sibling workspace for atomic work."""
        if not re.fullmatch(r"[a-z0-9-]+", name):
            raise OwnedPathError("invalid Morpheus staging workspace name")
        path = Path(
            tempfile.mkdtemp(
                prefix=f".{self.root.name}.{name}-",
                dir=self.root.parent,
            )
        )
        if path.parent != self.root.parent or path.is_symlink():
            path.rmdir()
            raise OwnedPathError("Morpheus staging workspace escaped its owned boundary")
        return path
