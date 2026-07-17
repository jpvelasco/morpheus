from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "validation/smoke/core.py"


def test_CONT_002_core_probe_is_loopback_only_and_covers_behavior() -> None:
    source = PROBE.read_text(encoding="utf-8")
    compile(source, str(PROBE), "exec")
    assert "http://127.0.0.1" in source
    assert "qwopus-coder" not in source
    for route in (
        "/healthz",
        "/api/v1/health",
        "/api/v1/models",
        "/v1/chat/completions",
    ):
        assert route in source
    assert '"stream": True' in source
    assert "settings.telemetry_port" in source
    assert 'sys.stdout.write("core_smoke=passed\\n")' in source


def test_CONT_002_core_probe_requires_a_private_secret_file() -> None:
    source = PROBE.read_text(encoding="utf-8")
    assert "path.is_symlink()" in source
    assert "stat.S_IMODE(path.stat().st_mode) & 0o077" in source
