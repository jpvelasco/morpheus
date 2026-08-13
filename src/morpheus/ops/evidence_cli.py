from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import signal

# Commands are explicit argument vectors and never pass through a shell.
import subprocess  # nosec B404
import sys
import zipfile
from collections.abc import Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from threading import Thread
from typing import Any, BinaryIO, cast

from morpheus.ops.evidence import (
    CanaryGuard,
    CanaryLeakError,
    EvidenceRun,
    EvidenceRunSpec,
    EvidenceStatus,
    RedactedEvidenceStream,
)

_CANARY_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="morpheus-evidence",
        description="Run one validation command and create privacy-safe release evidence.",
    )
    parser.add_argument("--root", type=Path, default=Path("artifacts/release-validation"))
    parser.add_argument("--run-id")
    parser.add_argument("--task", action="append", required=True, dest="task_ids")
    parser.add_argument("--requirement", action="append", default=[], dest="requirement_ids")
    parser.add_argument(
        "--environment",
        required=True,
        choices=("DEV", "VM", "HOST-RO", "HOST-MAINT"),
    )
    parser.add_argument("--source-commit")
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--authorization-ref")
    parser.add_argument("--canary-file", type=Path)
    parser.add_argument("--tool", action="append", default=[], metavar="NAME=VERSION")
    parser.add_argument("--artifact", action="append", default=[], metavar="SOURCE=DESTINATION")
    parser.add_argument("--candidate", action="append", default=[], metavar="SOURCE=LABEL")
    parser.add_argument("--pre-state-digest")
    parser.add_argument("--post-state-digest")
    parser.add_argument("--safe-summary")
    parser.add_argument("--timeout", type=float)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command.pop(0)
    if not command:
        raise ValueError("an evidence command is required after --")
    if args.environment.startswith("HOST-") and not args.authorization_ref:
        raise ValueError("HOST evidence requires an explicit authorization reference")

    canaries = _load_canaries(args.canary_file)
    guard = CanaryGuard(canaries)
    started_at = datetime.now(UTC)
    source_commit = args.source_commit or _git_commit()
    run_id = args.run_id or f"{started_at:%Y%m%dT%H%M%SZ}-{source_commit[:8]}"
    supplied_tools = _bindings(args.tool, option="--tool")
    reserved_tools = {"evidence-runner", "python"} & supplied_tools.keys()
    if reserved_tools:
        raise ValueError(f"reserved tool inventory name: {sorted(reserved_tools)[0]}")
    tools = {
        "evidence-runner": "1",
        "python": platform.python_version(),
        **supplied_tools,
    }
    candidates = {
        label: f"sha256:{_sha256(Path(source))}"
        for source, label in _binding_pairs(args.candidate, option="--candidate")
    }
    artifacts = _binding_pairs(args.artifact, option="--artifact")
    run = EvidenceRun.create(
        args.root,
        run_id,
        EvidenceRunSpec(
            task_ids=tuple(args.task_ids),
            requirement_ids=tuple(args.requirement_ids),
            environment=args.environment,
            source_commit=source_commit,
            reviewer=args.reviewer,
            authorization_ref=args.authorization_ref,
        ),
        guard=guard,
        started_at=started_at,
    )
    environment = os.environ.copy()
    for name, value in canaries.items():
        environment[f"MORPHEUS_EVIDENCE_CANARY_{name.upper()}"] = value

    status = EvidenceStatus.PASS
    exit_code = 0
    timed_out = False
    try:
        process = subprocess.Popen(  # noqa: S603  # nosec B603
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            **(_spawn_kwargs()),
        )
        if process.stdout is None or process.stderr is None:
            raise RuntimeError("validation command pipes were not created")
        stream_errors: list[BaseException] = []
        with (
            run.open_redacted_stream("logs/stdout.log") as stdout_stream,
            run.open_redacted_stream("logs/stderr.log") as stderr_stream,
        ):
            threads = [
                Thread(
                    target=_drain_pipe,
                    args=(process.stdout, stdout_stream, stream_errors),
                    name="morpheus-evidence-stdout",
                ),
                Thread(
                    target=_drain_pipe,
                    args=(process.stderr, stderr_stream, stream_errors),
                    name="morpheus-evidence-stderr",
                ),
            ]
            for thread in threads:
                thread.start()
            try:
                exit_code = process.wait(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                _kill_process_tree(process)
                process.wait()
                timed_out = True
                exit_code = 124
                status = EvidenceStatus.FAIL
            finally:
                for thread in threads:
                    thread.join()
            if stream_errors:
                raise stream_errors[0]
        if exit_code:
            status = EvidenceStatus.FAIL
    except OSError as error:
        run.write_text("logs/stdout.log", "")
        run.write_text("logs/stderr.log", f"command unavailable: {type(error).__name__}\n")
        exit_code = 125
        status = EvidenceStatus.BLOCKED

    run.write_json(
        "results/command.json",
        {
            "argument_count": len(command),
            "executable": Path(command[0]).name,
            "exit_code": exit_code,
            "timed_out": timed_out,
        },
    )

    try:
        for source, destination in artifacts:
            run.import_artifact(Path(source), destination)
    except (CanaryLeakError, ValueError, OSError, zipfile.BadZipFile) as error:
        run.write_json(
            "results/artifact-rejection.json",
            {
                "error_type": type(error).__name__,
                "safe_summary": "artifact rejected by evidence privacy or integrity checks",
            },
        )
        status = EvidenceStatus.FAIL
        exit_code = exit_code or 1

    default_summary = {
        EvidenceStatus.PASS: "validation command passed",
        EvidenceStatus.FAIL: "validation command or artifact check failed",
        EvidenceStatus.BLOCKED: "validation command could not start",
        EvidenceStatus.DEFERRED: "validation command was deferred",
    }[status]
    manifest = run.finalize(
        status,
        ended_at=datetime.now(UTC),
        safe_summary=args.safe_summary or default_summary,
        tool_versions=tools,
        candidate_checksums=candidates,
        pre_state_digest=args.pre_state_digest,
        post_state_digest=args.post_state_digest,
    )
    sys.stdout.write(f"evidence_manifest={manifest}\n")
    return exit_code


def entrypoint() -> None:
    raise SystemExit(main())


def _load_canaries(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    if path.is_symlink() or not path.is_file():
        raise ValueError("canary file must be a regular file")
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise ValueError("canary file permissions must deny group and other access")
    value: Any = json.loads(path.read_text())
    if not isinstance(value, dict) or any(
        not isinstance(name, str) or not _CANARY_NAME.fullmatch(name) or not isinstance(canary, str)
        for name, canary in value.items()
    ):
        raise ValueError("canary file must map lowercase canary classes to string values")
    return cast(dict[str, str], value)


def _git_commit() -> str:
    # This fixed command only reads the current Git object ID.
    completed = subprocess.run(  # nosec B603 B607
        ["git", "rev-parse", "HEAD"],  # noqa: S607 - fixed local Git inspection
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _bindings(values: list[str], *, option: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for name, value in _binding_pairs(values, option=option):
        if name in result:
            raise ValueError(f"duplicate {option} name: {name}")
        result[name] = value
    return result


def _binding_pairs(values: list[str], *, option: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for value in values:
        left, separator, right = value.partition("=")
        if not separator or not left or not right:
            raise ValueError(f"{option} values must use NAME=VALUE form")
        pairs.append((left, right))
    return pairs


def _sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"candidate must be a regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _drain_pipe(
    source: BinaryIO,
    destination: RedactedEvidenceStream,
    errors: list[BaseException],
) -> None:
    try:
        while chunk := source.read(1024 * 1024):
            destination.write(chunk)
    except BaseException as error:
        errors.append(error)


def _spawn_kwargs() -> dict[str, Any]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _kill_process_tree(process: subprocess.Popen[bytes]) -> None:
    if os.name == "nt":
        subprocess.run(  # noqa: S603  # nosec B603
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],  # noqa: S607 - fixed Windows process-tree killer on PATH
            capture_output=True,
            check=False,
        )
        return
    with suppress(ProcessLookupError):
        killpg = getattr(os, "killpg", None)
        if killpg is not None:
            killpg(process.pid, getattr(signal, "SIGKILL", 9))
