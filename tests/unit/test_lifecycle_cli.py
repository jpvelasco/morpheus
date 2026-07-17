from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from morpheus.cli import lifecycle as lifecycle_cli
from morpheus.core.lifecycle import LifecycleAction, LifecycleRequest

runner = CliRunner()


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (["install", "0.1.0"], LifecycleRequest(LifecycleAction.INSTALL, version="0.1.0")),
        (["validate", "0.1.0"], LifecycleRequest(LifecycleAction.VALIDATE, version="0.1.0")),
        (["start"], LifecycleRequest(LifecycleAction.START)),
        (["stop"], LifecycleRequest(LifecycleAction.STOP)),
        (["migrate"], LifecycleRequest(LifecycleAction.MIGRATE)),
        (
            ["backup", "before-upgrade"],
            LifecycleRequest(LifecycleAction.BACKUP, backup_id="before-upgrade"),
        ),
        (
            ["restore-preflight", "before-upgrade"],
            LifecycleRequest(
                LifecycleAction.RESTORE_PREFLIGHT,
                backup_id="before-upgrade",
            ),
        ),
        (["upgrade", "0.2.0"], LifecycleRequest(LifecycleAction.UPGRADE, version="0.2.0")),
        (["rollback"], LifecycleRequest(LifecycleAction.ROLLBACK)),
        (["uninstall"], LifecycleRequest(LifecycleAction.UNINSTALL)),
    ],
)
def test_REL_003_lifecycle_cli_emits_fixed_typed_operations(
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
    expected: LifecycleRequest,
) -> None:
    observed: list[LifecycleRequest] = []

    def execute(request: LifecycleRequest) -> dict[str, object]:
        observed.append(request)
        return {
            "action": request.action.value,
            "outcome": "already_satisfied",
            "protected_external_runtime": "unchanged",
        }

    monkeypatch.setattr(lifecycle_cli, "_execute", execute)

    result = runner.invoke(lifecycle_cli.app, [*arguments, "--json"])

    assert result.exit_code == 0
    assert observed == [expected]
    assert json.loads(result.stdout)["protected_external_runtime"] == "unchanged"


def test_INV_004_lifecycle_cli_requires_exact_explicit_purge_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[LifecycleRequest] = []
    monkeypatch.setattr(
        lifecycle_cli,
        "_execute",
        lambda request: observed.append(request) or {"outcome": "applied"},
    )

    result = runner.invoke(
        lifecycle_cli.app,
        ["uninstall", "--purge-confirmation", "purge:morpheus-lab", "--json"],
    )

    assert result.exit_code == 0
    assert observed == [
        LifecycleRequest(
            LifecycleAction.UNINSTALL,
            confirmation="purge:morpheus-lab",
            lab_authorized=True,
        )
    ]


def test_REL_003_lifecycle_cli_help_lists_complete_separate_command_surface() -> None:
    result = runner.invoke(lifecycle_cli.app, ["--help"])

    assert result.exit_code == 0
    for command in (
        "backup",
        "install",
        "migrate",
        "restore-preflight",
        "rollback",
        "start",
        "stop",
        "uninstall",
        "upgrade",
        "validate",
    ):
        assert command in result.stdout


def test_REL_003_lifecycle_cli_normalizes_agent_failure_without_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        lifecycle_cli,
        "_execute",
        lambda request: (_ for _ in ()).throw(RuntimeError("private failure detail")),
    )

    result = runner.invoke(lifecycle_cli.app, ["start", "--json"])

    assert result.exit_code == 2
    assert json.loads(result.stdout) == {
        "action": "start",
        "error": "RuntimeError",
        "outcome": "failed",
    }
    assert "private failure detail" not in result.stdout


def test_REL_003_lifecycle_cli_human_output_is_structured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        lifecycle_cli,
        "_execute",
        lambda request: {"action": request.action.value, "outcome": "applied"},
    )

    result = runner.invoke(lifecycle_cli.app, ["start"])

    assert result.exit_code == 0
    assert result.stdout.startswith("{\n")


def test_REL_003_lifecycle_cli_uses_configured_signed_agent_transport(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    observed: dict[str, object] = {}

    class Secret:
        def get_secret_value(self) -> str:
            return "agent-key-with-enough-entropy"

    class Client:
        def __init__(self, **kwargs: object) -> None:
            observed.update(kwargs)

        async def lifecycle(self, request: LifecycleRequest) -> object:
            observed["request"] = request
            return SimpleNamespace(result={"outcome": "applied"})

    monkeypatch.setattr(
        lifecycle_cli,
        "load_settings",
        lambda: SimpleNamespace(
            agent_key=Secret(),
            runtime_agent_url="http://127.0.0.1:9000",
            runtime_agent_socket=tmp_path,
        ),
    )
    monkeypatch.setattr(lifecycle_cli, "RuntimeAgentClient", Client)

    payload = lifecycle_cli._execute(LifecycleRequest(LifecycleAction.START))

    assert payload == {"outcome": "applied"}
    assert observed["base_url"] == "http://127.0.0.1:9000"
    assert observed["key"] == b"agent-key-with-enough-entropy"


def test_REL_003_lifecycle_cli_fails_closed_without_agent_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        lifecycle_cli,
        "load_settings",
        lambda: SimpleNamespace(
            agent_key=SimpleNamespace(get_secret_value=lambda: ""),
            runtime_agent_url=None,
            runtime_agent_socket=None,
        ),
    )

    with pytest.raises(RuntimeError, match="authentication"):
        lifecycle_cli._execute(LifecycleRequest(LifecycleAction.START))
