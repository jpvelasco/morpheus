"""Journaled settings overrides with one-level rollback (OUI-005).

Applied settings changes are written to an owned overrides file in
env-file format, atomically, with a snapshot of the previous content and a
journal metadata record. Rollback restores the previous snapshot exactly.
Secret fields are never accepted: they must be set in the secret env file,
so no secret value can ever be written by this adapter.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from morpheus.config import MorpheusSettings
from morpheus.core.paths import OwnedPathResolver
from morpheus.core.settings_catalog import SECRET_FIELDS

#: Env-file keys may be prefixed by MORPHEUS_ like other config layers.
_KNOWN_PREFIXES = ("MORPHEUS_", "")


class SettingsJournalError(RuntimeError):
    """Raised when an overrides file cannot be applied or rolled back."""


class SettingsJournal:
    """Atomic env-file overrides with a one-level rollback snapshot."""

    def __init__(self, path: Path, *, owned_root: Path | None = None) -> None:
        self._paths = OwnedPathResolver(owned_root or path.parent)
        self._path = self._paths.resolve(path)
        self._snapshot_path = self._path.with_suffix(self._path.suffix + ".previous")
        self._meta_path = self._path.parent / "journal.json"

    def current(self) -> dict[str, str]:
        return self._read(self._path)

    def apply(self, values: dict[str, str]) -> dict[str, Any]:
        safe = {
            key: value
            for key, value in values.items()
            if key in MorpheusSettings.model_fields and key not in SECRET_FIELDS
        }
        if not safe:
            raise SettingsJournalError("no editable settings were provided")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists():
            previous = self._path.read_text(encoding="utf-8")
            self._snapshot_path.write_text(previous, encoding="utf-8")
        lines = [f"{key.upper()}={value}" for key, value in sorted(safe.items())]
        temporary = self._path.with_suffix(self._path.suffix + ".tmp")
        temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(temporary, self._path)
        self._write_meta(
            {
                "applied_at": datetime.now(UTC).isoformat(),
                "applied": dict(sorted(safe.items())),
                "restart_required": True,
            }
        )
        last = self.last_applied()
        return {
            "applied": dict(sorted(safe.items())),
            "restart_required": True,
            "applied_at": last["applied_at"] if last else None,
        }

    def rollback(self) -> bool:
        if not self._snapshot_path.exists():
            raise SettingsJournalError("no previous settings snapshot exists to restore")
        os.replace(self._snapshot_path, self._path)
        self._write_meta(None)
        return True

    def rollback_available(self) -> bool:
        return self._snapshot_path.exists()

    def last_applied(self) -> dict[str, Any] | None:
        if not self._meta_path.exists():
            return None
        meta = json.loads(self._meta_path.read_text(encoding="utf-8"))
        last = meta.get("last_applied")
        return last if isinstance(last, dict) else None

    def _write_meta(self, last_applied: dict[str, Any] | None) -> None:
        self._meta_path.write_text(
            json.dumps({"last_applied": last_applied}, indent=2) + "\n", encoding="utf-8"
        )

    def _read(self, path: Path) -> dict[str, str]:
        if not path.exists():
            return {}
        values: dict[str, str] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            raw_key, value = line.split("=", 1)
            key = raw_key
            for prefix in _KNOWN_PREFIXES:
                if raw_key.startswith(prefix):
                    key = raw_key.removeprefix(prefix).lower()
                    break
            values[key] = value
        return values
