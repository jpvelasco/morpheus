from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "validation" / "smoke" / "telemetry.py"
STATE_PROBE = ROOT / "validation" / "smoke" / "telemetry_state.py"


def test_OPT_TEL_001_probe_is_loopback_only_and_covers_compatibility() -> None:
    source = PROBE.read_text(encoding="utf-8")
    compile(source, str(PROBE), "exec")

    assert "http://127.0.0.1" in source
    assert "qwopus-coder" not in source
    assert "/v1/chat/completions" in source
    for mode in ("unavailable", "slow", "empty_stream", "slow_stream"):
        assert mode in source
    assert "direct_nonstream.content == proxied_nonstream.content" in source
    assert "direct_stream.content == proxied_stream.content" in source
    assert 'settings.llm_base_url.removesuffix("/v1")' in source
    assert 'parser.add_argument("--container-mode", action="store_true")' in source
    assert "request_capacity_exhausted" in source
    assert 'sys.stdout.write("telemetry_smoke=passed\\n")' in source


def test_OPT_TEL_001_probe_requires_a_private_secret_file() -> None:
    source = PROBE.read_text(encoding="utf-8")
    assert "path.is_symlink()" in source
    assert "stat.S_IMODE(path.stat().st_mode) & 0o077" in source
    assert "get_secret_value()" in source


def test_OPT_TEL_001_state_probe_covers_outcomes_privacy_backup_and_retention() -> None:
    source = STATE_PROBE.read_text(encoding="utf-8")
    compile(source, str(STATE_PROBE), "exec")

    for outcome in (
        "success",
        "upstream_http_error",
        "upstream_protocol_error",
        "upstream_timeout",
        "canceled",
    ):
        assert outcome in source
    assert "telemetry-validation-backup.sqlite3" in source
    assert "morpheus-private-prompt-canary-opt-tel-001" in source
    assert "morpheus-retention-expired-canary" in source
    assert "prune_telemetry" not in source
    assert "telemetry_state=" in source
