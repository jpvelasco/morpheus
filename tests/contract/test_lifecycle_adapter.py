from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from morpheus.adapters.runtime import lifecycle as lifecycle_module
from morpheus.adapters.runtime.lifecycle import (
    DockerComposeLifecycleAdapter,
    SubprocessCommandRunner,
)
from morpheus.core.lifecycle import LifecycleAction, LifecycleOutcome, LifecycleRequest
from morpheus.ops.lifecycle import LifecycleCoordinator

pytestmark = pytest.mark.contract


class FakeCommandRunner:
    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self.commands: list[tuple[str, ...]] = []
        self.container_present = False
        self.running = False
        self.inspect_name = "morpheus-api"
        self.inspect_project = project_id
        self.external_revision = "external-stable"
        self.fail_action: str | None = None
        self.failed = False
        self.invalid_owned_inspect: object | None = None

    def run(
        self,
        command: tuple[str, ...],
        *,
        timeout: int,
        check: bool = True,
    ) -> str:
        del timeout, check
        self.commands.append(command)
        if command[:4] == ("docker", "container", "ls", "--all"):
            return "a" * 64 + "\n" if self.container_present else ""
        if command[:4] == ("docker", "volume", "ls", "--quiet"):
            return ""
        if command[:4] == ("docker", "network", "ls", "--quiet"):
            return ""
        if command[:3] == ("docker", "container", "inspect"):
            target = command[-1]
            if target in {"history-coder", "open-webui"}:
                return json.dumps(
                    {
                        "id": target,
                        "image": self.external_revision,
                        "restart_count": 0,
                        "started_at": "fixed",
                    },
                    sort_keys=True,
                )
            if self.invalid_owned_inspect is not None:
                return json.dumps(self.invalid_owned_inspect)
            return json.dumps(
                {
                    "labels": {"io.morpheus.project": self.inspect_project},
                    "name": f"/{self.inspect_name}",
                    "state": "running" if self.running else "exited",
                }
            )
        if command[:3] == ("docker", "network", "inspect"):
            return json.dumps({"id": "external-network", "revision": self.external_revision})
        if command[:2] == ("docker", "compose"):
            if self.fail_action in command and not self.failed:
                self.failed = True
                raise RuntimeError("injected compose failure")
            if "create" in command:
                self.container_present = True
                self.running = False
            elif "start" in command or "up" in command:
                self.container_present = True
                self.running = True
            elif "stop" in command:
                self.running = False
            elif "down" in command:
                self.container_present = False
                self.running = False
            return ""
        raise AssertionError(f"unexpected command: {command}")


def stage_release(root: Path, version: str) -> None:
    release = root / "releases" / version
    release.mkdir(parents=True)
    (release / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    (release / "candidate.yaml").write_text("services: {}\n", encoding="utf-8")
    (release / "release.json").write_text(
        json.dumps(
            {
                "compose_files": ["compose.yaml", "candidate.yaml"],
                "format": 1,
                "version": version,
            }
        ),
        encoding="utf-8",
    )


def lifecycle(
    tmp_path: Path,
) -> tuple[
    LifecycleCoordinator,
    DockerComposeLifecycleAdapter,
    FakeCommandRunner,
    Path,
    Path,
]:
    deployment = tmp_path / "deployment"
    deployment.mkdir()
    (deployment / "morpheus.env").write_text("MORPHEUS_API_KEY=not-read\n", encoding="utf-8")
    stage_release(deployment, "0.1.0")
    stage_release(deployment, "0.2.0")
    data = tmp_path / "data"
    runner = FakeCommandRunner("morpheus-lab")
    adapter = DockerComposeLifecycleAdapter(
        project_id="morpheus-lab",
        deployment_root=deployment,
        data_root=data,
        external_network="ai_default",
        runner=runner,
    )
    return (
        LifecycleCoordinator(adapter=adapter, project_id="morpheus-lab"),
        adapter,
        runner,
        deployment,
        data,
    )


def compose_actions(runner: FakeCommandRunner) -> list[str]:
    return [
        action
        for command in runner.commands
        if command[:2] == ("docker", "compose")
        for action in ("config", "create", "start", "stop", "up", "down")
        if action in command
    ]


def test_REL_003_fixed_compose_install_start_stop_and_reinstall_are_idempotent(
    tmp_path: Path,
) -> None:
    coordinator, _, runner, _, data = lifecycle(tmp_path)

    install = LifecycleRequest(LifecycleAction.INSTALL, version="0.1.0")
    assert coordinator.execute(install).outcome is LifecycleOutcome.APPLIED
    assert coordinator.execute(install).outcome is LifecycleOutcome.ALREADY_SATISFIED
    assert (
        coordinator.execute(LifecycleRequest(LifecycleAction.START)).outcome
        is LifecycleOutcome.APPLIED
    )
    assert (
        coordinator.execute(LifecycleRequest(LifecycleAction.START)).outcome
        is LifecycleOutcome.ALREADY_SATISFIED
    )
    assert (
        coordinator.execute(LifecycleRequest(LifecycleAction.STOP)).outcome
        is LifecycleOutcome.APPLIED
    )
    assert (
        coordinator.execute(LifecycleRequest(LifecycleAction.STOP)).outcome
        is LifecycleOutcome.ALREADY_SATISFIED
    )

    assert compose_actions(runner) == ["config", "create", "start", "stop"]
    assert json.loads((data / ".morpheus-owner.json").read_text())["project_id"] == "morpheus-lab"


def test_REL_003_backup_preflight_upgrade_and_rollback_preserve_state(tmp_path: Path) -> None:
    coordinator, _, runner, _, data = lifecycle(tmp_path)
    coordinator.execute(LifecycleRequest(LifecycleAction.INSTALL, version="0.1.0"))
    coordinator.execute(LifecycleRequest(LifecycleAction.START))
    (data / "operator-state.txt").write_text("baseline", encoding="utf-8")

    backup = LifecycleRequest(LifecycleAction.BACKUP, backup_id="manual-baseline")
    assert coordinator.execute(backup).outcome is LifecycleOutcome.APPLIED
    assert coordinator.execute(backup).outcome is LifecycleOutcome.ALREADY_SATISFIED
    preflight = LifecycleRequest(
        LifecycleAction.RESTORE_PREFLIGHT,
        backup_id="manual-baseline",
    )
    assert coordinator.execute(preflight).outcome is LifecycleOutcome.VALIDATED

    upgraded = coordinator.execute(LifecycleRequest(LifecycleAction.UPGRADE, version="0.2.0"))
    assert upgraded.after.active_version == "0.2.0"
    (data / "operator-state.txt").write_text("candidate", encoding="utf-8")

    rolled_back = coordinator.execute(LifecycleRequest(LifecycleAction.ROLLBACK))
    assert rolled_back.after.active_version == "0.1.0"
    assert rolled_back.after.previous_version is None
    assert (data / "operator-state.txt").read_text(encoding="utf-8") == "baseline"
    assert "up" in compose_actions(runner)


def test_REL_003_uninstall_preserves_data_and_purge_requires_owned_marker(tmp_path: Path) -> None:
    coordinator, _, runner, _, data = lifecycle(tmp_path)
    coordinator.execute(LifecycleRequest(LifecycleAction.INSTALL, version="0.1.0"))
    (data / "operator-state.txt").write_text("preserve", encoding="utf-8")

    uninstall = LifecycleRequest(LifecycleAction.UNINSTALL)
    assert coordinator.execute(uninstall).outcome is LifecycleOutcome.APPLIED
    assert coordinator.execute(uninstall).outcome is LifecycleOutcome.ALREADY_SATISFIED
    assert (data / "operator-state.txt").read_text(encoding="utf-8") == "preserve"

    coordinator.execute(LifecycleRequest(LifecycleAction.INSTALL, version="0.1.0"))
    purge = LifecycleRequest(
        LifecycleAction.UNINSTALL,
        confirmation="purge:morpheus-lab",
        lab_authorized=True,
    )
    assert coordinator.execute(purge).outcome is LifecycleOutcome.APPLIED
    assert not data.exists()
    assert any("--volumes" in command for command in runner.commands)


def test_INV_002_forged_or_protected_compose_resource_blocks_every_mutation(
    tmp_path: Path,
) -> None:
    coordinator, _, runner, _, _ = lifecycle(tmp_path)
    runner.container_present = True
    runner.inspect_name = "history-coder"

    with pytest.raises(PermissionError, match="not authorized"):
        coordinator.execute(LifecycleRequest(LifecycleAction.INSTALL, version="0.1.0"))

    assert "create" not in compose_actions(runner)


@pytest.mark.parametrize(
    "manifest",
    [
        {"format": 1, "version": "0.1.0", "compose_files": ["../compose.yaml"]},
        {"format": 1, "version": "other", "compose_files": ["compose.yaml"]},
        {
            "format": 1,
            "version": "0.1.0",
            "compose_files": ["compose.yaml"],
            "unexpected": True,
        },
    ],
)
def test_SEC_006_release_catalog_rejects_ambiguous_or_escaping_manifests(
    tmp_path: Path,
    manifest: dict[str, object],
) -> None:
    coordinator, _, _, deployment, _ = lifecycle(tmp_path)
    (deployment / "releases" / "0.1.0" / "release.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="release manifest"):
        coordinator.execute(LifecycleRequest(LifecycleAction.VALIDATE, version="0.1.0"))


def test_INV_001_external_identity_capture_is_selected_and_never_reads_environment(
    tmp_path: Path,
) -> None:
    coordinator, _, runner, _, _ = lifecycle(tmp_path)
    coordinator.execute(LifecycleRequest(LifecycleAction.VALIDATE, version="0.1.0"))

    inspect_commands = [command for command in runner.commands if "inspect" in command]
    assert inspect_commands
    serialized = " ".join(" ".join(command) for command in inspect_commands)
    assert ".Config.Env" not in serialized
    assert "history-coder" in serialized
    assert "open-webui" in serialized


def test_REL_003_stopped_upgrade_migrate_and_rollback_use_create_without_start(
    tmp_path: Path,
) -> None:
    coordinator, _, runner, _, data = lifecycle(tmp_path)
    coordinator.execute(LifecycleRequest(LifecycleAction.INSTALL, version="0.1.0"))
    state_path = data / ".lifecycle-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["schema_version"] = 0
    state_path.write_text(json.dumps(state), encoding="utf-8")

    assert coordinator.execute(LifecycleRequest(LifecycleAction.MIGRATE)).after.schema_version == 1
    coordinator.execute(LifecycleRequest(LifecycleAction.UPGRADE, version="0.2.0"))
    coordinator.execute(LifecycleRequest(LifecycleAction.ROLLBACK))

    assert compose_actions(runner).count("create") == 3


def test_REL_003_failed_running_upgrade_restores_state_and_service_posture(
    tmp_path: Path,
) -> None:
    coordinator, _, runner, _, data = lifecycle(tmp_path)
    coordinator.execute(LifecycleRequest(LifecycleAction.INSTALL, version="0.1.0"))
    coordinator.execute(LifecycleRequest(LifecycleAction.START))
    (data / "operator-state.txt").write_text("baseline", encoding="utf-8")
    runner.fail_action = "up"

    with pytest.raises(RuntimeError, match="injected"):
        coordinator.execute(LifecycleRequest(LifecycleAction.UPGRADE, version="0.2.0"))

    recovered = coordinator.execute(LifecycleRequest(LifecycleAction.VALIDATE))
    assert recovered.before.active_version == "0.1.0"
    assert recovered.before.running is True
    assert (data / "operator-state.txt").read_text(encoding="utf-8") == "baseline"


def test_REL_003_failed_first_install_removes_only_new_owned_staging_state(
    tmp_path: Path,
) -> None:
    coordinator, _, runner, _, data = lifecycle(tmp_path)
    runner.fail_action = "create"

    with pytest.raises(RuntimeError, match="injected"):
        coordinator.execute(LifecycleRequest(LifecycleAction.INSTALL, version="0.1.0"))

    assert not data.exists()
    assert "down" in compose_actions(runner)


def test_SEC_002_invalid_owned_resource_labels_fail_closed(tmp_path: Path) -> None:
    coordinator, _, runner, _, _ = lifecycle(tmp_path)
    runner.container_present = True
    runner.invalid_owned_inspect = {"labels": None, "name": "morpheus-api", "state": "exited"}

    with pytest.raises(PermissionError, match="labels"):
        coordinator.execute(LifecycleRequest(LifecycleAction.VALIDATE, version="0.1.0"))


@pytest.mark.parametrize(
    "contents",
    [
        "not-json",
        json.dumps({"format": 1}),
        json.dumps(
            {
                "active_version": "0.1.0",
                "format": 1,
                "installed": "yes",
                "previous_version": None,
                "project_id": "morpheus-lab",
                "rollback_backup": None,
                "running": False,
                "schema_version": 1,
            }
        ),
    ],
)
def test_REL_003_corrupt_lifecycle_state_fails_closed(tmp_path: Path, contents: str) -> None:
    coordinator, _, _, _, data = lifecycle(tmp_path)
    coordinator.execute(LifecycleRequest(LifecycleAction.INSTALL, version="0.1.0"))
    (data / ".lifecycle-state.json").write_text(contents, encoding="utf-8")

    with pytest.raises(RuntimeError, match="state is invalid"):
        coordinator.execute(LifecycleRequest(LifecycleAction.STOP))


def test_INV_002_unmarked_nonempty_data_root_is_never_claimed(tmp_path: Path) -> None:
    coordinator, _, _, _, data = lifecycle(tmp_path)
    data.mkdir()
    (data / "external-canary").write_text("preserve", encoding="utf-8")

    with pytest.raises(PermissionError, match="ownership marker"):
        coordinator.execute(LifecycleRequest(LifecycleAction.INSTALL, version="0.1.0"))
    assert (data / "external-canary").read_text(encoding="utf-8") == "preserve"


@pytest.mark.parametrize(
    "manifest",
    [
        "not-json",
        json.dumps({"compose_files": [], "format": 1, "version": "0.1.0"}),
        json.dumps({"compose_files": [7], "format": 1, "version": "0.1.0"}),
        json.dumps({"compose_files": ["missing.yaml"], "format": 1, "version": "0.1.0"}),
    ],
)
def test_SEC_006_additional_release_manifest_failures_are_closed(
    tmp_path: Path, manifest: str
) -> None:
    coordinator, _, _, deployment, _ = lifecycle(tmp_path)
    (deployment / "releases" / "0.1.0" / "release.json").write_text(manifest, encoding="utf-8")

    with pytest.raises(ValueError, match="release manifest"):
        coordinator.execute(LifecycleRequest(LifecycleAction.VALIDATE, version="0.1.0"))


def test_SEC_006_lifecycle_adapter_rejects_broad_missing_or_symlinked_roots(
    tmp_path: Path,
) -> None:
    deployment = tmp_path / "deployment"
    deployment.mkdir()
    (deployment / "morpheus.env").write_text("", encoding="utf-8")
    link = tmp_path / "deployment-link"
    link.symlink_to(deployment, target_is_directory=True)

    with pytest.raises(ValueError, match="symbolic"):
        DockerComposeLifecycleAdapter(
            project_id="morpheus-lab",
            deployment_root=link,
            data_root=tmp_path / "data",
            external_network="ai_default",
        )
    with pytest.raises(ValueError, match="regular directory"):
        DockerComposeLifecycleAdapter(
            project_id="morpheus-lab",
            deployment_root=tmp_path / "missing",
            data_root=tmp_path / "data",
            external_network="ai_default",
        )
    with pytest.raises(ValueError, match="too broad"):
        DockerComposeLifecycleAdapter(
            project_id="morpheus-lab",
            deployment_root=deployment,
            data_root=deployment,
            external_network="ai_default",
        )


def test_SEC_002_subprocess_runner_uses_argv_and_normalizes_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        lifecycle_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="ok"),
    )
    runner = SubprocessCommandRunner()
    assert runner.run(("docker", "info"), timeout=1) == "ok"

    monkeypatch.setattr(
        lifecycle_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="private detail"),
    )
    with pytest.raises(RuntimeError, match="fixed lifecycle command failed"):
        runner.run(("docker", "info"), timeout=1)
    assert runner.run(("docker", "info"), timeout=1, check=False) == "private detail"
