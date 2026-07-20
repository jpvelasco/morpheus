from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess  # nosec B404
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from morpheus.core.lifecycle import (
    CURRENT_SCHEMA_VERSION,
    LifecycleAction,
    LifecycleRequest,
    LifecycleSnapshot,
)
from morpheus.core.ownership import OwnershipPolicy, ResourceAction, ResourceIdentity, ResourceKind
from morpheus.core.paths import OwnedPathResolver
from morpheus.ops.archive import BackupManager

_STATE_FILE = ".lifecycle-state.json"
_OWNER_FILE = ".morpheus-owner.json"


class CommandRunner(Protocol):
    def run(
        self,
        command: tuple[str, ...],
        *,
        timeout: int,
        check: bool = True,
    ) -> str: ...


class SubprocessCommandRunner:
    def run(
        self,
        command: tuple[str, ...],
        *,
        timeout: int,
        check: bool = True,
    ) -> str:
        result = subprocess.run(  # noqa: S603  # nosec B603
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if check and result.returncode:
            raise RuntimeError("fixed lifecycle command failed")
        return result.stdout


@dataclass(frozen=True, slots=True)
class ReleaseDefinition:
    version: str
    directory: Path
    compose_files: tuple[Path, ...]


class DockerComposeLifecycleAdapter:
    """Execute fixed Compose actions against one labeled Morpheus project."""

    def __init__(
        self,
        *,
        project_id: str,
        deployment_root: Path,
        data_root: Path,
        external_network: str,
        runner: CommandRunner | None = None,
    ) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{1,62}", project_id):
            raise ValueError("project_id is invalid")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", external_network):
            raise ValueError("external network identity is invalid")
        if deployment_root.is_symlink() or data_root.is_symlink():
            raise ValueError("lifecycle roots must not be symbolic links")
        self._project_id = project_id
        self._deployment = deployment_root.resolve()
        self._data = data_root.resolve()
        if self._data == Path("/") or self._data == self._deployment:
            raise ValueError("data root is too broad for lifecycle operations")
        if self._deployment.is_symlink() or not self._deployment.is_dir():
            raise ValueError("deployment root must be a regular directory")
        if self._data.is_symlink():
            raise ValueError("data root must not be a symbolic link")
        self._environment = self._deployment / "morpheus.env"
        if self._environment.is_symlink() or not self._environment.is_file():
            raise ValueError("fixed lifecycle environment file is missing")
        self._external_network = external_network
        self._runner = runner or SubprocessCommandRunner()
        self._authorization = OwnershipPolicy(project_id=project_id)
        self._paths = OwnedPathResolver(self._data)
        self._backups = self._paths.staging_path("backups")
        self._transient_backup: Path | None = None
        self._transient_version: str | None = None

    def snapshot(self) -> LifecycleSnapshot:
        snapshot = self._snapshot_from_document(self._read_document())
        resources = self._owned_resources()
        running = any(item.get("state") == "running" for _, item in resources)
        backup_ids = (
            frozenset(
                path.stem
                for path in self._backups.glob("*.zip")
                if path.is_file() and not path.is_symlink()
            )
            if self._backups.is_dir() and not self._backups.is_symlink()
            else frozenset()
        )
        return replace(
            snapshot, running=running if snapshot.installed else False, backup_ids=backup_ids
        )

    def protected_runtime_identity(self) -> str:
        selected: list[str] = []
        container_template = (
            '{"id":{{json .Id}},"image":{{json .Image}},'
            '"restart_count":{{json .RestartCount}},"started_at":{{json .State.StartedAt}}}'
        )
        for name in ("history-coder", "open-webui"):
            selected.append(
                self._runner.run(
                    ("docker", "container", "inspect", "--format", container_template, "--", name),
                    timeout=5,
                    check=False,
                ).strip()
            )
        # Omit live endpoint membership: Morpheus joining the external network is
        # expected and must not look like protected-runtime mutation.
        network_template = (
            '{"id":{{json .Id}},"name":{{json .Name}},"driver":{{json .Driver}},'
            '"ipam":{{json .IPAM.Config}}}'
        )
        selected.append(
            self._runner.run(
                (
                    "docker",
                    "network",
                    "inspect",
                    "--format",
                    network_template,
                    "--",
                    self._external_network,
                ),
                timeout=5,
                check=False,
            ).strip()
        )
        return hashlib.sha256("\n".join(selected).encode()).hexdigest()

    def apply(self, request: LifecycleRequest) -> None:
        document = self._read_document()
        before = self._snapshot_from_document(document)
        action = request.action
        if action is LifecycleAction.VALIDATE:
            self._validate_release(request.version or before.active_version)
            return
        if action is LifecycleAction.INSTALL:
            assert request.version is not None
            self._ensure_owned_root()
            self._validate_release(request.version)
            self._owned_resources()
            self._transient_version = request.version
            self._compose(request.version, "create", "--no-build", "--pull", "never")
            self._write_snapshot(
                replace(
                    before,
                    installed=True,
                    running=False,
                    active_version=request.version,
                    schema_version=max(before.schema_version, CURRENT_SCHEMA_VERSION),
                )
            )
        elif action is LifecycleAction.START:
            self._owned_resources()
            self._compose(self._required_version(before), "start")
            self._write_snapshot(replace(before, running=True))
        elif action is LifecycleAction.STOP:
            self._owned_resources()
            self._compose(self._required_version(before), "stop", "--timeout", "30")
            self._write_snapshot(replace(before, running=False))
        elif action is LifecycleAction.MIGRATE:
            self._ensure_owned_root()
            self._write_snapshot(replace(before, schema_version=CURRENT_SCHEMA_VERSION))
        elif action is LifecycleAction.BACKUP:
            assert request.backup_id is not None
            self._ensure_owned_root()
            BackupManager(owned_root=self._data).create(Path(f"{request.backup_id}.zip"))
        elif action is LifecycleAction.RESTORE_PREFLIGHT:
            assert request.backup_id is not None
            self._ensure_owned_root()
            BackupManager(owned_root=self._data).restore_preflight(Path(f"{request.backup_id}.zip"))
        elif action is LifecycleAction.UPGRADE:
            assert request.version is not None
            self._upgrade(before, request.version)
        elif action is LifecycleAction.ROLLBACK:
            self._rollback(before, document)
        elif action is LifecycleAction.UNINSTALL:
            self._uninstall(before, purge=request.purge)
        self._transient_backup = None
        self._transient_version = None

    def recover(self, snapshot: LifecycleSnapshot) -> None:
        if self._transient_backup is not None and self._transient_backup.is_file():
            BackupManager(owned_root=self._data).restore(self._transient_backup)
        current = self._snapshot_from_document(self._read_document())
        version = snapshot.active_version
        if snapshot.installed and version is not None:
            command = (
                ("up", "-d", "--no-build", "--pull", "never", "--wait", "--wait-timeout", "120")
                if snapshot.running
                else ("create", "--no-build", "--pull", "never")
            )
            self._compose(version, *command)
            self._write_snapshot(snapshot)
        elif self._transient_version or current.active_version:
            self._compose(
                self._transient_version or current.active_version or "",
                "down",
                "--timeout",
                "30",
            )
            if snapshot.active_version is None and self._owned_marker_matches():
                shutil.rmtree(self._data)
            else:
                self._write_snapshot(snapshot)
        self._transient_backup = None
        self._transient_version = None

    def _upgrade(self, before: LifecycleSnapshot, target: str) -> None:
        current = self._required_version(before)
        self._validate_release(target)
        self._owned_resources()
        backup_id = self._automatic_backup_id("upgrade", current, target)
        self._ensure_owned_root()
        self._transient_backup = BackupManager(owned_root=self._data).create(
            Path(f"{backup_id}.zip")
        )
        self._transient_version = target
        if before.running:
            self._compose(
                target,
                "up",
                "-d",
                "--no-build",
                "--pull",
                "never",
                "--wait",
                "--wait-timeout",
                "120",
            )
        else:
            self._compose(target, "create", "--no-build", "--pull", "never")
        self._write_snapshot(
            replace(before, active_version=target, previous_version=current),
            rollback_backup=backup_id,
        )

    def _rollback(self, before: LifecycleSnapshot, document: dict[str, Any] | None) -> None:
        target = before.previous_version
        if target is None or document is None:
            raise RuntimeError("rollback state is unavailable")
        rollback_backup = document.get("rollback_backup")
        if not isinstance(rollback_backup, str):
            raise RuntimeError("rollback backup is unavailable")
        current = self._required_version(before)
        recovery_id = self._automatic_backup_id("recovery", current, target)
        self._transient_backup = BackupManager(owned_root=self._data).create(
            Path(f"{recovery_id}.zip")
        )
        self._transient_version = current
        if before.running:
            self._compose(current, "stop", "--timeout", "30")
        BackupManager(owned_root=self._data).restore(Path(f"{rollback_backup}.zip"))
        restored = self._snapshot_from_document(self._read_document())
        command = (
            ("up", "-d", "--no-build", "--pull", "never", "--wait", "--wait-timeout", "120")
            if restored.running
            else ("create", "--no-build", "--pull", "never")
        )
        self._compose(target, *command)
        self._write_snapshot(
            replace(restored, installed=True, active_version=target, previous_version=None)
        )

    def _uninstall(self, before: LifecycleSnapshot, *, purge: bool) -> None:
        self._owned_resources()
        command = ["down", "--timeout", "30"]
        if purge:
            command.append("--volumes")
        self._compose(self._required_version(before), *command)
        if purge:
            if not self._owned_marker_matches():
                raise PermissionError("Morpheus data ownership marker is missing")
            shutil.rmtree(self._data)
            if self._backups.exists():
                if self._backups.is_symlink():
                    raise PermissionError("backup workspace is a symbolic link")
                shutil.rmtree(self._backups)
            return
        self._write_snapshot(replace(before, installed=False, running=False))

    def _validate_release(self, version: str | None) -> None:
        if version is None:
            raise RuntimeError("no active or requested release is available")
        self._compose(version, "config", "--quiet")

    def _release(self, version: str) -> ReleaseDefinition:
        directory = self._deployment / "releases" / version
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("release manifest directory is invalid")
        manifest_path = directory / "release.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ValueError("release manifest is missing")
        try:
            value = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("release manifest is invalid") from error
        if not isinstance(value, dict) or set(value) != {"compose_files", "format", "version"}:
            raise ValueError("release manifest has invalid fields")
        if value.get("format") != 1 or value.get("version") != version:
            raise ValueError("release manifest identity is invalid")
        compose_files = value.get("compose_files")
        if not isinstance(compose_files, list) or not 1 <= len(compose_files) <= 8:
            raise ValueError("release manifest compose files are invalid")
        paths = OwnedPathResolver(directory)
        resolved: list[Path] = []
        for item in compose_files:
            if not isinstance(item, str):
                raise ValueError("release manifest compose file is invalid")
            try:
                path = paths.resolve_relative(item)
            except ValueError as error:
                raise ValueError("release manifest compose file escapes") from error
            if path.suffix not in {".yaml", ".yml"} or path.is_symlink() or not path.is_file():
                raise ValueError("release manifest compose file is invalid")
            resolved.append(path)
        return ReleaseDefinition(
            version=version, directory=directory, compose_files=tuple(resolved)
        )

    def _compose(self, version: str, *arguments: str) -> str:
        release = self._release(version)
        command = [
            "docker",
            "compose",
            "--project-name",
            self._project_id,
            "--project-directory",
            str(release.directory),
            "--env-file",
            str(self._environment),
        ]
        for path in release.compose_files:
            command.extend(("--file", str(path)))
        command.extend(arguments)
        return self._runner.run(tuple(command), timeout=180)

    def _owned_resources(self) -> list[tuple[ResourceIdentity, dict[str, Any]]]:
        resources: list[tuple[ResourceIdentity, dict[str, Any]]] = []
        definitions = (
            (
                ResourceKind.CONTAINER,
                "container",
                "{{json .Config.Labels}}",
                "{{json .State.Status}}",
            ),
            (ResourceKind.VOLUME, "volume", "{{json .Labels}}", "null"),
            (ResourceKind.NETWORK, "network", "{{json .Labels}}", "null"),
        )
        for kind, noun, labels_expression, state_expression in definitions:
            identifiers = self._runner.run(
                (
                    "docker",
                    noun,
                    "ls",
                    "--all" if noun == "container" else "--quiet",
                    *(("--quiet", "--no-trunc") if noun == "container" else ()),
                    "--filter",
                    f"label=com.docker.compose.project={self._project_id}",
                ),
                timeout=5,
            ).splitlines()
            template = (
                '{"name":{{json .Name}},"labels":'
                + labels_expression
                + ',"state":'
                + state_expression
                + "}"
            )
            for identifier in (item.strip() for item in identifiers if item.strip()):
                value = json.loads(
                    self._runner.run(
                        ("docker", noun, "inspect", "--format", template, "--", identifier),
                        timeout=5,
                    )
                )
                labels = value.get("labels") if isinstance(value, dict) else None
                if not isinstance(labels, dict):
                    raise PermissionError("resource ownership labels are invalid")
                resource = ResourceIdentity(
                    kind=kind,
                    name=str(value.get("name", "")).removeprefix("/"),
                    labels={str(key): str(item) for key, item in labels.items()},
                )
                self._authorization.authorize(action=ResourceAction.INSPECT, resource=resource)
                resources.append((resource, value))
        return resources

    def _read_document(self) -> dict[str, Any] | None:
        if not self._data.exists():
            return None
        if self._data.is_symlink() or not self._data.is_dir():
            raise PermissionError("Morpheus data root is unsafe")
        marker = self._data / _OWNER_FILE
        state = self._data / _STATE_FILE
        if not marker.exists():
            if any(self._data.iterdir()):
                raise PermissionError("Morpheus data ownership marker is missing")
            return None
        if not self._owned_marker_matches() or state.is_symlink() or not state.is_file():
            raise PermissionError("Morpheus lifecycle state is not owned")
        try:
            value = json.loads(state.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError("Morpheus lifecycle state is invalid") from error
        if not isinstance(value, dict):
            raise RuntimeError("Morpheus lifecycle state is invalid")
        return value

    def _snapshot_from_document(self, value: dict[str, Any] | None) -> LifecycleSnapshot:
        if value is None:
            return LifecycleSnapshot()
        required = {
            "active_version",
            "format",
            "installed",
            "previous_version",
            "project_id",
            "rollback_backup",
            "running",
            "schema_version",
        }
        if (
            set(value) != required
            or value.get("format") != 1
            or value.get("project_id") != self._project_id
        ):
            raise RuntimeError("Morpheus lifecycle state is invalid")
        try:
            if (
                not isinstance(value.get("installed"), bool)
                or not isinstance(value.get("running"), bool)
                or not isinstance(value.get("schema_version"), int)
            ):
                raise TypeError("invalid lifecycle state types")
            return LifecycleSnapshot(
                installed=value["installed"],
                running=value["running"],
                active_version=value["active_version"],
                previous_version=value["previous_version"],
                schema_version=value["schema_version"],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError("Morpheus lifecycle state is invalid") from error

    def _ensure_owned_root(self) -> None:
        document = self._read_document()
        if document is not None:
            return
        self._data.mkdir(parents=True, exist_ok=True)
        self._atomic_json(
            self._data / _OWNER_FILE,
            {"format": 1, "project_id": self._project_id},
        )
        self._write_snapshot(LifecycleSnapshot())

    def _owned_marker_matches(self) -> bool:
        marker = self._data / _OWNER_FILE
        if marker.is_symlink() or not marker.is_file():
            return False
        try:
            value = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return False
        return bool(value == {"format": 1, "project_id": self._project_id})

    def _write_snapshot(
        self,
        snapshot: LifecycleSnapshot,
        *,
        rollback_backup: str | None = None,
    ) -> None:
        self._data.mkdir(parents=True, exist_ok=True)
        if not self._owned_marker_matches():
            raise PermissionError("Morpheus data ownership marker is missing")
        state_path = self._data / _STATE_FILE
        current = (
            self._read_document() if state_path.is_file() and not state_path.is_symlink() else None
        )
        if rollback_backup is None and current is not None:
            existing = current.get("rollback_backup")
            rollback_backup = existing if isinstance(existing, str) else None
        self._atomic_json(
            self._data / _STATE_FILE,
            {
                "active_version": snapshot.active_version,
                "format": 1,
                "installed": snapshot.installed,
                "previous_version": snapshot.previous_version,
                "project_id": self._project_id,
                "rollback_backup": rollback_backup,
                "running": snapshot.running,
                "schema_version": snapshot.schema_version,
            },
        )

    @staticmethod
    def _automatic_backup_id(operation: str, source: str, target: str) -> str:
        digest = hashlib.sha256(f"{operation}:{source}:{target}".encode()).hexdigest()[:16]
        return f"{operation}-{digest}"

    @staticmethod
    def _required_version(snapshot: LifecycleSnapshot) -> str:
        if snapshot.active_version is None:
            raise RuntimeError("no active release is available")
        return snapshot.active_version

    @staticmethod
    def _atomic_json(path: Path, value: dict[str, Any]) -> None:
        temporary = path.with_name(f".{path.name}.tmp")
        data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        try:
            with temporary.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
            descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            temporary.unlink(missing_ok=True)
