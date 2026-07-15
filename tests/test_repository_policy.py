from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_SUFFIXES = {".db", ".key", ".log", ".pem", ".sqlite", ".sqlite3"}
FORBIDDEN_NAMES = {".env", "id_rsa", "id_ed25519"}
FORBIDDEN_PARTS = {"artifacts", "data", "dist", "node_modules", "secrets"}


def tracked_files() -> list[Path]:
    git = shutil.which("git")
    assert git is not None
    result = subprocess.run(  # noqa: S603
        [git, "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [Path(item) for item in result.stdout.split("\0") if item]


def test_repository_does_not_track_private_or_generated_files() -> None:
    violations = [
        path
        for path in tracked_files()
        if path.name in FORBIDDEN_NAMES
        or path.suffix in FORBIDDEN_SUFFIXES
        or FORBIDDEN_PARTS.intersection(path.parts)
    ]
    assert violations == []


def test_example_environment_contains_no_functional_secret() -> None:
    values = {}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value

    for key in ("MORPHEUS_API_KEY", "MORPHEUS_AGENT_KEY", "MORPHEUS_SESSION_SECRET"):
        assert values[key] == ""
