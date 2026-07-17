from __future__ import annotations

import runpy
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
SCANNER = ROOT / "validation/browser/scan_evidence.py"
scan_evidence = cast(Callable[[Path], list[str]], runpy.run_path(str(SCANNER))["scan_evidence"])


def test_BROW_006_evidence_scanner_accepts_clean_plain_and_zip_files(tmp_path: Path) -> None:
    (tmp_path / "report.json").write_text('{"status":"passed"}', encoding="utf-8")
    with zipfile.ZipFile(tmp_path / "trace.zip", "w") as archive:
        archive.writestr("trace.txt", "synthetic clean trace")

    assert scan_evidence(tmp_path) == []


def test_BROW_006_evidence_scanner_rejects_plain_canary_without_echoing_it(tmp_path: Path) -> None:
    (tmp_path / "report.json").write_text("prefix-browser-test-key-suffix", encoding="utf-8")

    matches = scan_evidence(tmp_path)

    assert matches == ["report.json"]
    assert "browser-test-key" not in "".join(matches)


def test_BROW_006_evidence_scanner_rejects_canary_inside_trace_archive(tmp_path: Path) -> None:
    with zipfile.ZipFile(tmp_path / "trace.zip", "w") as archive:
        archive.writestr("network.log", "prefix-browser-test-key-suffix")

    matches = scan_evidence(tmp_path)

    assert "trace.zip:network.log" in matches
    assert "browser-test-key" not in "".join(matches)
