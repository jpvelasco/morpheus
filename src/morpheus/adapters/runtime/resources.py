from __future__ import annotations

import json
import re
import subprocess  # nosec B404
from dataclasses import replace
from typing import Any, Protocol

from morpheus.core.ownership import OwnershipPolicy, ResourceAction, ResourceIdentity, ResourceKind
from morpheus.core.performance import ContainerResourceSample
from morpheus.ops.performance import parse_docker_stats


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
            raise RuntimeError("fixed Docker resource observation failed")
        return result.stdout


class DockerResourceObserver:
    """Read one resource sample from exact labeled Morpheus containers."""

    def __init__(
        self,
        *,
        project_id: str,
        expected_source_commit: str | None = None,
        expected_release_version: str | None = None,
        runner: CommandRunner | None = None,
    ) -> None:
        if re.fullmatch(r"[a-z][a-z0-9_-]{1,62}", project_id) is None:
            raise ValueError("project_id is invalid")
        if (
            expected_source_commit is not None
            and re.fullmatch(r"[0-9a-f]{40,64}", expected_source_commit) is None
        ):
            raise ValueError("expected source commit is invalid")
        if (
            expected_release_version is not None
            and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", expected_release_version) is None
        ):
            raise ValueError("expected release version is invalid")
        self._project_id = project_id
        self._expected_source_commit = expected_source_commit
        self._expected_release_version = expected_release_version
        self._runner = runner or SubprocessCommandRunner()
        self._authorization = OwnershipPolicy(project_id=project_id)

    def observe(
        self,
        *,
        required_components: tuple[str, ...],
    ) -> tuple[ContainerResourceSample, ...]:
        if not required_components or len(set(required_components)) != len(required_components):
            raise ValueError("required components must be unique and non-empty")
        if any(
            re.fullmatch(r"[a-z][a-z0-9_-]{1,62}", item) is None for item in required_components
        ):
            raise ValueError("required component is invalid")
        host_cpu_count = self._host_cpu_count()
        output = self._runner.run(
            (
                "docker",
                "ps",
                "--quiet",
                "--no-trunc",
                "--filter",
                f"label=io.morpheus.project={self._project_id}",
            ),
            timeout=5,
        )
        container_ids = tuple(line.strip() for line in output.splitlines() if line.strip())
        if any(re.fullmatch(r"[0-9a-f]{64}", item) is None for item in container_ids):
            raise ValueError("Docker returned an invalid container identifier")
        observed: dict[str, ContainerResourceSample] = {}
        for container_id in container_ids:
            identity = self._identity(container_id)
            component = identity["component"]
            if component not in required_components:
                continue
            if component in observed:
                raise ValueError("Docker returned duplicate component containers")
            sample = self._stats(container_id, component, host_cpu_count=host_cpu_count)
            observed[component] = sample
        missing = tuple(component for component in required_components if component not in observed)
        if missing:
            raise ValueError("required Morpheus resource container is missing")
        return tuple(observed[component] for component in required_components)

    def _host_cpu_count(self) -> int:
        output = self._runner.run(
            ("docker", "info", "--format", "{{json .NCPU}}"),
            timeout=5,
        )
        value: Any = json.loads(output)
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 4096:
            raise ValueError("Docker returned an invalid logical CPU count")
        return int(value)

    def _identity(self, container_id: str) -> dict[str, str]:
        template = '{"id":{{json .Id}},"name":{{json .Name}},"labels":{{json .Config.Labels}}}'
        output = self._runner.run(
            ("docker", "container", "inspect", "--format", template, "--", container_id),
            timeout=5,
        )
        value = json.loads(output)
        if not isinstance(value, dict) or value.get("id") != container_id:
            raise ValueError("Docker container identity changed during resource observation")
        labels = value.get("labels")
        if not isinstance(labels, dict):
            raise ValueError("Docker container labels are invalid")
        string_labels = {str(key): str(item) for key, item in labels.items()}
        if string_labels.get("io.morpheus.project") != self._project_id:
            raise ValueError("Docker ownership label changed during resource observation")
        if (
            self._expected_source_commit is not None
            and string_labels.get("org.opencontainers.image.revision")
            != self._expected_source_commit
        ):
            raise ValueError("Docker source commit label does not match the candidate")
        if (
            self._expected_release_version is not None
            and string_labels.get("org.opencontainers.image.version")
            != self._expected_release_version
        ):
            raise ValueError("Docker release version label does not match the candidate")
        name = str(value.get("name", "")).removeprefix("/")
        self._authorization.authorize(
            action=ResourceAction.INSPECT,
            resource=ResourceIdentity(
                kind=ResourceKind.CONTAINER,
                name=name,
                labels=string_labels,
            ),
        )
        component = string_labels.get("io.morpheus.component", "")
        if re.fullmatch(r"[a-z][a-z0-9_-]{1,62}", component) is None:
            raise ValueError("Docker component label is invalid")
        return {"name": name, "component": component}

    def _stats(
        self,
        container_id: str,
        component: str,
        *,
        host_cpu_count: int,
    ) -> ContainerResourceSample:
        template = (
            '{"ID":{{json .ID}},"Name":{{json .Name}},'
            '"CPUPerc":{{json .CPUPerc}},"MemUsage":{{json .MemUsage}},'
            '"PIDs":{{json .PIDs}}}'
        )
        output = self._runner.run(
            (
                "docker",
                "stats",
                "--no-stream",
                "--format",
                template,
                "--",
                container_id,
            ),
            timeout=10,
        )
        value: Any = json.loads(output)
        sample = parse_docker_stats(value, component=component)
        if not container_id.startswith(sample.container_id):
            raise ValueError("Docker stats identity changed during resource observation")
        return replace(
            sample,
            container_id=container_id,
            cpu_percent=sample.cpu_percent / host_cpu_count,
        )
