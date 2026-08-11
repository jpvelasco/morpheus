from __future__ import annotations

import shutil
import subprocess
import tomllib
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

    for key in (
        "MORPHEUS_API_KEY",
        "MORPHEUS_AGENT_KEY",
        "MORPHEUS_SESSION_SECRET",
        "MORPHEUS_UPSTREAM_API_KEY",
        "MORPHEUS_N8N_ENCRYPTION_KEY",
    ):
        assert values[key] == '""'


def test_secret_scan_ignores_only_the_reviewed_empty_example_false_positive() -> None:
    lines = (ROOT / ".gitleaksignore").read_text(encoding="utf-8").splitlines()
    fingerprints = [line for line in lines if line and not line.startswith("#")]
    assert fingerprints == [
        "786d14ea2e55a3d79a92f7a24169937eb7c2a02f:.env.example:generic-api-key:20"
    ]
    assert any("adjacent empty assignments" in line for line in lines if line.startswith("#"))

    config = tomllib.loads((ROOT / ".gitleaks.toml").read_text(encoding="utf-8"))
    assert config["extend"] == {"useDefault": True}
    assert config["allowlists"] == [
        {
            "description": "Reviewed secret-free environment template",
            "paths": [r"(?:^|[/!])\.env\.example$"],
        },
        {
            "description": "Official Python base-image public signing fingerprint",
            "regexTarget": "match",
            "regexes": [r"GPG_KEY=[0-9A-F]{40}"],
        },
    ]
