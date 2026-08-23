"""Unit tests: separate collected/selected/passed/skipped/deselected reporting (R0)."""

from __future__ import annotations

from tests.counting_plugin import build_count_report, lane_slug


def test_report_separates_collected_selected_and_outcomes() -> None:
    stats = {
        "passed": [object()] * 7,
        "failed": [object()],
        "skipped": [object()] * 2,
    }
    report = build_count_report(stats, collected=20, deselected=10, args=["tests/unit"])
    assert report == {
        "args": ["tests/unit"],
        "collected": 20,
        "selected": 10,
        "deselected": 10,
        "passed": 7,
        "failed": 1,
        "skipped": 2,
        "errors": 0,
    }


def test_selected_never_negative_and_missing_stat_keys_default_to_zero() -> None:
    report = build_count_report({}, collected=0, deselected=0, args=[])
    assert report["selected"] == 0
    assert report["errors"] == 0


def test_lane_slug_is_filesystem_safe_and_bounded() -> None:
    slug = lane_slug(["tests/contract", "-m", "contract", "--cov"])
    assert "/" not in slug and slug.startswith("tests_contract")
    assert len(lane_slug([f"very/long/{'x' * 200}"])) <= 80
    assert lane_slug([]) == "session"
