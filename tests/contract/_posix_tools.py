from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_PROBE = ROOT / "validation" / "load" / "dev_rehearsal.sh"


def _find_usable_bash() -> str | None:
    bash = shutil.which("bash")
    if bash is None:
        return None
    try:
        completed = subprocess.run(  # noqa: S603 - guarded by shutil.which above
            [bash, "-n", _PROBE], capture_output=True, check=False, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return bash if completed.returncode == 0 else None


USABLE_BASH = _find_usable_bash()

NEEDS_USABLE_BASH = pytest.mark.skipif(
    USABLE_BASH is None,
    reason="the available bash cannot parse repository shell scripts on this host",
)
