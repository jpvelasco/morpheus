from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "src/morpheus/core"
FORBIDDEN = {"fastapi", "httpx", "pydantic", "sqlalchemy", "subprocess"}


def test_core_has_no_infrastructure_imports() -> None:
    violations: list[str] = []
    for source in CORE.glob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".", 1)[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".", 1)[0]]
            else:
                continue
            for name in names:
                if name in FORBIDDEN:
                    violations.append(f"{source.name}:{node.lineno}:{name}")
    assert violations == []
