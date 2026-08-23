"""Pytest plugin: report collected/selected/passed/skipped/deselected counts separately.

Loaded through ``addopts = "-p tests.counting_plugin"``. Every invocation writes
one JSON report under ignored ``artifacts/test-counts/`` so gates can prove lane
volume honestly instead of quoting a single aggregate number.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

ARTIFACT_DIRNAME = Path("artifacts") / "test-counts"


def build_count_report(
    stats: dict[str, list], collected: int, deselected: int, args: list[str]
) -> dict[str, object]:
    passed = len(stats.get("passed", []))
    failed = len(stats.get("failed", []))
    skipped = len(stats.get("skipped", []))
    errors = len(stats.get("error", []))
    return {
        "args": list(args),
        "collected": collected,
        "selected": collected - deselected,
        "deselected": deselected,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "errors": errors,
    }


def lane_slug(args: list[str]) -> str:
    meaningful = [arg for arg in args if not str(arg).startswith("-")]
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", "_".join(meaningful) or "session").strip("_")
    return slug[:80] or "session"


class CountingPlugin:
    def __init__(self) -> None:
        self.selected = 0
        self.deselected = 0

    @property
    def collected(self) -> int:
        return self.selected + self.deselected

    def pytest_collection_finish(self, session) -> None:
        self.selected = len(session.items)

    def pytest_deselected(self, items) -> None:
        self.deselected += len(items)

    def pytest_terminal_summary(self, terminalreporter, exitstatus, config) -> None:
        stats = terminalreporter.stats
        report = build_count_report(stats, self.collected, self.deselected, config.args)
        target = Path(config.rootpath) / ARTIFACT_DIRNAME
        target.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = target / f"{stamp}_{lane_slug(config.args)}.json"
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


plugin = CountingPlugin()


def pytest_configure(config) -> None:
    config.pluginmanager.register(plugin)


def pytest_unconfigure(config) -> None:
    config.pluginmanager.unregister(plugin)
