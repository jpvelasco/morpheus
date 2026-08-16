"""Unit tests: desktop compatibility handshake core (DESK-002)."""

from __future__ import annotations

import pytest

from morpheus.core.compatibility import (
    CompatibilityError,
    desktop_compatibility,
    parse_semver,
    version_in_range,
)


def test_parse_semver_accepts_major_minor_patch() -> None:
    assert parse_semver("0.1.0") == (0, 1, 0)
    assert parse_semver("2.3.4") == (2, 3, 4)


def test_parse_semver_rejects_malformed_values() -> None:
    for value in ("", "1", "1.2", "1.2.3.4", "a.b.c", "1.2.3-beta", "v1.2.3", "1..2"):
        with pytest.raises(CompatibilityError):
            parse_semver(value)


def test_version_in_range_is_inclusive() -> None:
    assert version_in_range("0.1.0", "0.1.0", "0.1.0")
    assert version_in_range("0.2.0", "0.1.0", "0.3.0")
    assert version_in_range("0.1.5", "0.1.0", "0.2.0")
    assert not version_in_range("0.0.9", "0.1.0", "0.3.0")
    assert not version_in_range("0.4.0", "0.1.0", "0.3.0")


def test_version_in_range_rejects_malformed_values() -> None:
    with pytest.raises(CompatibilityError):
        version_in_range("nope", "0.1.0", "0.3.0")


def test_desktop_compatibility_compatible_when_in_range() -> None:
    result = desktop_compatibility(
        desktop_version="0.1.0",
        backend_version="0.1.0",
        desktop_minimum="0.1.0",
        desktop_maximum="0.1.0",
    )
    assert result["status"] == "compatible"
    assert result["desktop_version"] == "0.1.0"
    assert result["backend_version"] == "0.1.0"


def test_desktop_compatibility_unsupported_when_out_of_range() -> None:
    result = desktop_compatibility(
        desktop_version="0.2.0",
        backend_version="0.1.0",
        desktop_minimum="0.1.0",
        desktop_maximum="0.1.0",
    )
    assert result["status"] == "unsupported_desktop"
    assert result["supported_desktop_range"] == {"min": "0.1.0", "max": "0.1.0"}


def test_desktop_compatibility_missing_desktop_version_is_bounded() -> None:
    result = desktop_compatibility(
        desktop_version=None,
        backend_version="0.1.0",
        desktop_minimum="0.1.0",
        desktop_maximum="0.1.0",
    )
    assert result["status"] == "missing_desktop_version"
    assert result["backend_version"] == "0.1.0"
