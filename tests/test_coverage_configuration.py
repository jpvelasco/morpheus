"""R0 traceability: composition roots must be measured or route-matrix represented."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

COMPOSITION_ROOTS = ("src/morpheus/api/app.py", "src/morpheus/agent/app.py")


def test_composition_roots_are_not_omitted_from_coverage() -> None:
    """AUD-007: coverage must not silently exclude the real application boundary.

    ``api/app.py`` and ``agent/app.py`` are where routes, middleware, and agent
    operations are composed; if they are not measured, an equivalent complete
    route/operation decision matrix must exist (none does yet).
    """
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    omitted = config["tool"]["coverage"]["report"].get("omit", [])
    offenders = [entry for entry in omitted if entry in COMPOSITION_ROOTS]
    assert offenders == [], (
        f"composition roots excluded from coverage measurement: {offenders}; "
        "measure them or add a complete route/operation matrix first"
    )
