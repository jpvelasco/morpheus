"""Unit tests: known runbook registry (AID-001)."""

from __future__ import annotations

import pytest

from morpheus.core.runbooks import (
    KNOWN_RUNBOOKS,
    RunbookReference,
    known_runbook_reference,
)

RUNBOOK_PATH = "docs/runbooks/BATWING_OPERATOR.md"


def test_registry_is_bounded_and_unique() -> None:
    ids = [entry.id for entry in KNOWN_RUNBOOKS]
    assert ids
    assert len(ids) == len(set(ids))
    assert len(ids) <= 16
    for entry in KNOWN_RUNBOOKS:
        assert entry.id and entry.path and entry.title
        assert not entry.path.startswith("/")
        assert ".." not in entry.path
        assert entry.path.endswith(".md")


def test_known_reference_returns_bounded_identity() -> None:
    reference = known_runbook_reference("batwing-operator")
    assert isinstance(reference, RunbookReference)
    assert reference.path == RUNBOOK_PATH


def test_unknown_runbook_is_rejected() -> None:
    with pytest.raises(ValueError):
        known_runbook_reference("not-a-runbook")


def test_path_injection_is_rejected_even_when_name_matches() -> None:
    with pytest.raises(ValueError):
        known_runbook_reference("../../etc/passwd")
