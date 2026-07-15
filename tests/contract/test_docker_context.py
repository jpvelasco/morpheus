from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[2]


def test_docker_context_is_allowlisted_to_runtime_build_inputs() -> None:
    lines = [
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert lines[0] == "**"
    assert set(lines[1:]) == {
        "!.dockerignore",
        "!README.md",
        "!pyproject.toml",
        "!src/",
        "!src/**",
        "src/**/__pycache__/",
        "src/**/__pycache__/**",
        "src/**/*.py[cod]",
        "!deploy/",
        "deploy/**",
        "!deploy/Dockerfile",
        "!web/",
        "web/**",
        "!web/Dockerfile",
        "!web/index.html",
        "!web/package-lock.json",
        "!web/package.json",
        "!web/src/",
        "!web/src/**",
        "!web/tsconfig.app.json",
        "!web/tsconfig.json",
        "!web/tsconfig.node.json",
        "!web/vite.config.ts",
        "!validation/",
        "validation/**",
        "!validation/docker-context/",
        "validation/docker-context/**",
        "!validation/docker-context/Dockerfile",
    }


def test_context_equivalence_proof_uses_docker_and_representative_dirty_state() -> None:
    script = (ROOT / "validation" / "docker-context" / "verify.sh").read_text(encoding="utf-8")

    for excluded_path in (
        ".git/HEAD",
        ".env",
        "secrets/token",
        "artifacts/result.json",
        "data/morpheus.sqlite3",
        ".venv/bin/python",
        ".pytest_cache/state",
        "src/morpheus/__pycache__/module.pyc",
        "dist/package.whl",
        "web/node_modules/module.js",
        "web/coverage/index.html",
        "compose.override.yaml",
    ):
        assert excluded_path in script

    assert script.count("docker build") == 2
    assert '[[ "${clean_id}" == "${dirty_id}" ]]' in script
    assert "--pull=false" in script
