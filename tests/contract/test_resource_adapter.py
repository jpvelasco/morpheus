from __future__ import annotations

import json

import pytest

from morpheus.adapters.runtime.resources import DockerResourceObserver

pytestmark = pytest.mark.contract


class FakeRunner:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.commands: list[tuple[str, ...]] = []

    def run(self, command: tuple[str, ...], *, timeout: int, check: bool = True) -> str:
        del timeout, check
        self.commands.append(command)
        return self.responses.pop(0)


def _inspect(
    container_id: str,
    component: str,
    project: str = "morpheus-perf",
    *,
    source_commit: str | None = None,
    release_version: str | None = None,
) -> str:
    labels = {
        "io.morpheus.project": project,
        "io.morpheus.component": component,
    }
    if source_commit is not None:
        labels["org.opencontainers.image.revision"] = source_commit
    if release_version is not None:
        labels["org.opencontainers.image.version"] = release_version
    return json.dumps(
        {
            "id": container_id,
            "name": f"/{project}-{component}-1",
            "labels": labels,
        }
    )


def _stats(container_id: str, component: str) -> str:
    return json.dumps(
        {
            "ID": container_id,
            "Name": f"morpheus-perf-{component}-1",
            "CPUPerc": "0.10%",
            "MemUsage": "10MiB / 256MiB",
            "PIDs": "4",
        }
    )


def test_PERF_002_observer_discovers_only_owned_required_components() -> None:
    api_id = "a" * 64
    dashboard_id = "b" * 64
    runner = FakeRunner(
        [
            "8\n",
            f"{api_id}\n{dashboard_id}\n",
            _inspect(api_id, "api"),
            _stats(api_id, "api"),
            _inspect(dashboard_id, "dashboard"),
            _stats(dashboard_id, "dashboard"),
        ]
    )
    observer = DockerResourceObserver(project_id="morpheus-perf", runner=runner)

    samples = observer.observe(required_components=("api", "dashboard"))

    assert tuple(sample.component for sample in samples) == ("api", "dashboard")
    assert samples[0].cpu_percent == 0.0125
    assert runner.commands[0] == ("docker", "info", "--format", "{{json .NCPU}}")
    assert runner.commands[1][:4] == ("docker", "ps", "--quiet", "--no-trunc")
    assert "label=io.morpheus.project=morpheus-perf" in runner.commands[1]
    assert all("--" in command for command in runner.commands[2:])


@pytest.mark.parametrize(
    "responses",
    [
        ["8\n", "not-a-container-id\n"],
        ["8\n", f"{'a' * 64}\n", _inspect("a" * 64, "api", project="forged")],
        ["8\n", f"{'a' * 64}\n", _inspect("a" * 64, "unexpected")],
        ["0\n"],
    ],
)
def test_PERF_002_observer_rejects_invalid_identity_or_ownership(responses) -> None:
    observer = DockerResourceObserver(project_id="morpheus-perf", runner=FakeRunner(responses))

    with pytest.raises(ValueError):
        observer.observe(required_components=("api", "dashboard"))


def test_PERF_002_observer_rejects_invalid_project_and_component_inputs() -> None:
    with pytest.raises(ValueError, match="project"):
        DockerResourceObserver(project_id="bad project", runner=FakeRunner([]))
    observer = DockerResourceObserver(project_id="morpheus-perf", runner=FakeRunner([]))
    with pytest.raises(ValueError, match="component"):
        observer.observe(required_components=("api;stop",))


def test_SOAK_002_observer_binds_running_image_labels_to_exact_candidate() -> None:
    container_id = "a" * 64
    source_commit = "c" * 40
    runner = FakeRunner(
        [
            "8\n",
            f"{container_id}\n",
            _inspect(
                container_id,
                "api",
                source_commit=source_commit,
                release_version="0.1.0",
            ),
            _stats(container_id, "api"),
        ]
    )
    observer = DockerResourceObserver(
        project_id="morpheus-perf",
        expected_source_commit=source_commit,
        expected_release_version="0.1.0",
        runner=runner,
    )

    assert observer.observe(required_components=("api",))[0].component == "api"

    mismatch = DockerResourceObserver(
        project_id="morpheus-perf",
        expected_source_commit="d" * 40,
        expected_release_version="0.1.0",
        runner=FakeRunner(
            [
                "8\n",
                f"{container_id}\n",
                _inspect(
                    container_id,
                    "api",
                    source_commit=source_commit,
                    release_version="0.1.0",
                ),
            ]
        ),
    )
    with pytest.raises(ValueError, match="candidate"):
        mismatch.observe(required_components=("api",))
