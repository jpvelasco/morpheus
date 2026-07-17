from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

CURRENT_SCHEMA_VERSION = 1
_VERSION = re.compile(r"^[0-9][A-Za-z0-9.+-]{0,63}$")
_BACKUP_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class LifecycleAction(StrEnum):
    INSTALL = "install"
    VALIDATE = "validate"
    START = "start"
    STOP = "stop"
    MIGRATE = "migrate"
    BACKUP = "backup"
    RESTORE_PREFLIGHT = "restore-preflight"
    UPGRADE = "upgrade"
    ROLLBACK = "rollback"
    UNINSTALL = "uninstall"


class LifecycleOutcome(StrEnum):
    APPLIED = "applied"
    ALREADY_SATISFIED = "already_satisfied"
    VALIDATED = "validated"


@dataclass(frozen=True, slots=True)
class LifecycleSnapshot:
    installed: bool = False
    running: bool = False
    active_version: str | None = None
    previous_version: str | None = None
    schema_version: int = 0
    backup_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.running and not self.installed:
            raise ValueError("a running lifecycle snapshot must be installed")
        for version in (self.active_version, self.previous_version):
            if version is not None and not _VERSION.fullmatch(version):
                raise ValueError("lifecycle snapshot contains an invalid version")
        if self.schema_version < 0:
            raise ValueError("schema version cannot be negative")
        if any(not _BACKUP_ID.fullmatch(item) for item in self.backup_ids):
            raise ValueError("lifecycle snapshot contains an invalid backup identifier")

    def public_dict(self) -> dict[str, object]:
        return {
            "active_version": self.active_version,
            "backup_count": len(self.backup_ids),
            "installed": self.installed,
            "previous_version": self.previous_version,
            "running": self.running,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class LifecycleRequest:
    action: LifecycleAction
    version: str | None = None
    backup_id: str | None = None
    confirmation: str | None = None
    lab_authorized: bool = False

    def __post_init__(self) -> None:
        if self.version is not None and not _VERSION.fullmatch(self.version):
            raise ValueError("version must be a bounded release identifier")
        if self.backup_id is not None and not _BACKUP_ID.fullmatch(self.backup_id):
            raise ValueError("backup_id must be a bounded identifier")
        if self.action in {LifecycleAction.INSTALL, LifecycleAction.UPGRADE} and not self.version:
            raise ValueError(f"{self.action.value} requires a version")
        if self.action in {LifecycleAction.BACKUP, LifecycleAction.RESTORE_PREFLIGHT}:
            if not self.backup_id:
                raise ValueError(f"{self.action.value} requires a backup_id")
        elif self.backup_id is not None:
            raise ValueError(f"{self.action.value} does not accept a backup_id")
        if (
            self.action
            not in {
                LifecycleAction.INSTALL,
                LifecycleAction.VALIDATE,
                LifecycleAction.UPGRADE,
            }
            and self.version is not None
        ):
            raise ValueError(f"{self.action.value} does not accept a version")
        if self.confirmation is not None:
            if self.action is not LifecycleAction.UNINSTALL:
                raise ValueError("purge confirmation is valid only for uninstall")
            if not self.lab_authorized:
                raise ValueError("purge requires explicit lab authorization")
        elif self.lab_authorized:
            raise ValueError("lab authorization is valid only with purge confirmation")

    @property
    def purge(self) -> bool:
        return self.confirmation is not None
