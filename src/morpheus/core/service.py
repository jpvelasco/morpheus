"""Independently versioned backend service lifecycle (PLAT-003).

Backend services are separately versioned packages installed as per-user
background services by default; this layer owns the versioned install,
restart, upgrade, rollback, and uninstall orchestration with health gates
and ownership-bounded, durable state. Process supervision is an adapter
concern; the store gates transitions on injected health evidence.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from morpheus.core.durable import atomic_replace
from morpheus.core.packages import (
    PackageError,
    PackageManifest,
    PackageVersion,
    extract_package,
    package_digest,
    scan_package,
)
from morpheus.core.paths import OwnedPathResolver

SERVICE_SCHEMA_VERSION = 1
_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

SERVICE_NONE = "none"
SERVICE_INSTALLED = "installed"
SERVICE_STARTING = "starting"
SERVICE_HEALTHY = "healthy"
SERVICE_FAILED = "failed"

_SERVICE_STATUSES = frozenset(
    {SERVICE_NONE, SERVICE_INSTALLED, SERVICE_STARTING, SERVICE_HEALTHY, SERVICE_FAILED}
)


class ServiceError(ValueError):
    """A backend service lifecycle operation failed."""


@dataclass(frozen=True, slots=True)
class ServiceHealth:
    """Health evidence for one versioned service instance."""

    healthy: bool
    summary: str


class ServiceHealthProbe(Protocol):
    def probe(self, service_name: str, version: PackageVersion) -> ServiceHealth: ...


@dataclass(frozen=True, slots=True)
class BackendServiceState:
    name: str
    status: str
    current: PackageVersion | None
    previous: PackageVersion | None

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": SERVICE_SCHEMA_VERSION,
            "name": self.name,
            "status": self.status,
            "current": str(self.current) if self.current is not None else None,
            "previous": str(self.previous) if self.previous is not None else None,
        }

    @classmethod
    def from_json(cls, value: Any) -> BackendServiceState:
        if not isinstance(value, dict) or value.get("schema_version") != SERVICE_SCHEMA_VERSION:
            raise ServiceError("service state is incompatible")
        name = value.get("name")
        if not isinstance(name, str) or not _NAME_PATTERN.fullmatch(name):
            raise ServiceError("service state name is invalid")
        status = value.get("status")
        if status not in _SERVICE_STATUSES:
            raise ServiceError("service state status is invalid")
        return cls(
            name=name,
            status=status,
            current=_version_or_none(value.get("current")),
            previous=_version_or_none(value.get("previous")),
        )


def _version_or_none(value: Any) -> PackageVersion | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ServiceError("service state version is invalid")
    return PackageVersion.parse(value)


def current_platform_tag() -> str:
    """The host target tag, e.g. ``win32-x86_64`` (target-native packages)."""
    import platform

    system = {
        "win32": "win32",
        "linux": "linux",
        "darwin": "darwin",
    }.get(platform.system().lower(), "unknown")
    machine = {
        "x86_64": "x86_64",
        "AMD64": "x86_64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }.get(platform.machine(), "unknown")
    tag = f"{system}-{machine}"
    if tag.startswith("unknown"):
        raise ServiceError("host platform tag is unsupported")
    return tag


class BackendServiceStore:
    """Versioned, health-gated lifecycle for one service per name.

    Layout under the owned root: ``services/<name>/state.json`` and
    ``services/<name>/versions/<version>/``. Every state transition is
    durable and atomic; versions are immutable once installed.
    """

    def __init__(
        self,
        *,
        owned_root: Path,
        platform_tag: str | None = None,
        probe: ServiceHealthProbe | None = None,
    ) -> None:
        self._paths = OwnedPathResolver(owned_root)
        self._platform = platform_tag or current_platform_tag()
        self._probe = probe

    def _services_root(self) -> Path:
        root = self._paths.root / "services"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _state_path(self, name: str) -> Path:
        self._require_name(name)
        return self._services_root() / name / "state.json"

    def _versions_dir(self, name: str) -> Path:
        self._require_name(name)
        directory = self._services_root() / name / "versions"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    @staticmethod
    def _require_name(name: str) -> None:
        if not _NAME_PATTERN.fullmatch(name):
            raise ServiceError("service name is not a bounded identifier")

    def _read_state(self, name: str) -> BackendServiceState:
        path = self._state_path(name)
        if not path.is_file():
            return BackendServiceState(name=name, status=SERVICE_NONE, current=None, previous=None)
        try:
            return BackendServiceState.from_json(json.loads(path.read_text()))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ServiceError("service state is unreadable") from error

    def _write_state(self, state: BackendServiceState) -> None:
        atomic_replace(self._state_path(state.name), json.dumps(state.to_json()).encode())

    def list(self) -> tuple[BackendServiceState, ...]:
        states: list[BackendServiceState] = []
        for entry in sorted(self._services_root().iterdir()):
            if not entry.is_dir():
                continue
            try:
                state = self._read_state(entry.name)
            except ServiceError:
                continue
            if state.current is not None:
                states.append(state)
        return tuple(states)

    def status(self, name: str) -> BackendServiceState:
        return self._read_state(name)

    def _verified(
        self, name: str, artifact: Path, expected_artifact_digest: str | None
    ) -> tuple[PackageManifest, dict[str, bytes]]:
        if expected_artifact_digest is not None:
            try:
                actual = package_digest(artifact)
            except OSError as error:
                raise ServiceError("package artifact is unreadable") from error
            if actual != expected_artifact_digest:
                raise ServiceError("package artifact digest does not match its manifest")
        try:
            manifest, contents = scan_package(artifact)
        except (PackageError, OSError) as error:
            raise ServiceError(f"package verification failed: {error}") from error
        if manifest.name != name:
            raise ServiceError("package name does not match the requested service")
        if manifest.platform != self._platform:
            raise ServiceError(
                f"package platform {manifest.platform} does not match host {self._platform}"
            )
        return manifest, contents

    def _extract(self, name: str, manifest: PackageManifest, contents: dict[str, bytes]) -> None:
        destination = self._versions_dir(name) / str(manifest.version)
        if destination.exists():
            raise ServiceError(f"service version {manifest.version} is already installed")
        extract_package(manifest, contents, destination)

    def _settle(
        self, name: str, state: BackendServiceState, version: PackageVersion
    ) -> BackendServiceState:
        self._write_state(
            BackendServiceState(
                name=name,
                status=SERVICE_STARTING,
                current=version,
                previous=state.previous,
            )
        )
        if self._probe is None:
            raise ServiceError("no health probe is configured for health-gated operations")
        evidence = self._probe.probe(name, version)
        settled = BackendServiceState(
            name=name,
            status=SERVICE_HEALTHY if evidence.healthy else SERVICE_FAILED,
            current=version,
            previous=state.previous,
        )
        self._write_state(settled)
        return settled

    def _discard_version(self, name: str, version: PackageVersion) -> None:
        directory = self._versions_dir(name) / str(version)
        if directory.is_symlink() or directory.is_file():
            raise ServiceError("service version directory is unsafe to remove")
        shutil.rmtree(directory, ignore_errors=True)

    def install(
        self,
        name: str,
        artifact: Path,
        *,
        expected_artifact_digest: str | None = None,
    ) -> BackendServiceState:
        """Verify, extract, and health-gate a first install."""
        self._require_name(name)
        manifest, contents = self._verified(name, artifact, expected_artifact_digest)
        state = self._read_state(name)
        if state.current is not None:
            raise ServiceError("service is already installed; upgrade instead")
        self._extract(name, manifest, contents)
        installed = BackendServiceState(
            name=name,
            status=SERVICE_INSTALLED,
            current=manifest.version,
            previous=None,
        )
        self._write_state(installed)
        outcome = self._settle(name, installed, manifest.version)
        if outcome.status != SERVICE_HEALTHY:
            self._discard_version(name, manifest.version)
            self._write_state(
                BackendServiceState(name=name, status=SERVICE_NONE, current=None, previous=None)
            )
            raise ServiceError(f"install of {manifest.version} failed its health gate")
        return outcome

    def restart(self, name: str) -> BackendServiceState:
        """Health-gated restart of the current version."""
        state = self._read_state(name)
        if state.current is None:
            raise ServiceError("service is not installed")
        outcome = self._settle(name, state, state.current)
        if outcome.status != SERVICE_HEALTHY:
            raise ServiceError("restart failed its health gate")
        return outcome

    def upgrade(
        self,
        name: str,
        artifact: Path,
        *,
        expected_artifact_digest: str | None = None,
    ) -> BackendServiceState:
        """Health-gated upgrade; a failed candidate rolls back automatically."""
        self._require_name(name)
        manifest, contents = self._verified(name, artifact, expected_artifact_digest)
        state = self._read_state(name)
        if state.current is None:
            raise ServiceError("service is not installed; install it first")
        if state.current >= manifest.version:
            raise ServiceError("upgrade target must be newer than the installed version")
        self._extract(name, manifest, contents)
        candidate = BackendServiceState(
            name=name,
            status=SERVICE_STARTING,
            current=manifest.version,
            previous=state.current,
        )
        outcome = self._settle(name, candidate, manifest.version)
        if outcome.status != SERVICE_HEALTHY:
            self._discard_version(name, manifest.version)
            self._write_state(
                BackendServiceState(
                    name=name,
                    status=SERVICE_HEALTHY,
                    current=state.current,
                    previous=None,
                )
            )
            raise ServiceError(
                "upgrade to "
                f"{manifest.version} failed its health gate; rolled back to {state.current}"
            )
        return outcome

    def rollback(self, name: str) -> BackendServiceState:
        """Health-gated rollback to the previously installed version."""
        state = self._read_state(name)
        if state.current is None or state.previous is None:
            raise ServiceError("service has no previous version to roll back to")
        if state.previous == state.current:
            raise ServiceError("service has no distinct previous version")
        rolled = BackendServiceState(
            name=name,
            status=SERVICE_STARTING,
            current=state.previous,
            previous=state.current,
        )
        self._write_state(rolled)
        outcome = self._settle(name, rolled, state.previous)
        if outcome.status != SERVICE_HEALTHY:
            raise ServiceError("rollback failed its health gate")
        return outcome

    def uninstall(self, name: str) -> None:
        """Stop semantics: remove the versioned service and its state."""
        state = self._read_state(name)
        if state.current is None:
            raise ServiceError("service is not installed")
        self._require_name(name)
        directory = self._services_root() / name
        if directory.is_symlink() or directory.is_file():
            raise ServiceError("service directory is unsafe to remove")
        shutil.rmtree(directory)
        self._write_state(
            BackendServiceState(name=name, status=SERVICE_NONE, current=None, previous=None)
        )
