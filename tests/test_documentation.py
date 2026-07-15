from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[[^]]+]\(([^)]+)\)")


def test_local_documentation_links_resolve() -> None:
    missing: list[str] = []
    for document in sorted(ROOT.rglob("*.md")):
        relative_document = document.relative_to(ROOT)
        if {".git", ".venv", "node_modules"}.intersection(relative_document.parts):
            continue
        for target in LINK.findall(document.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            relative = target.split("#", 1)[0]
            if relative and not (document.parent / relative).resolve().exists():
                missing.append(f"{relative_document} -> {target}")
    assert missing == []
