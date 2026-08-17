"""Known runbook registry (AID-001).

Diagnostic evidence packages reference runbooks by bounded identity, never
by arbitrary caller-supplied paths. The registry maps a stable id to a
repository-relative documentation path and title; anything else is
rejected, so log or prompt content cannot inject an unchecked reference.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RunbookReference:
    id: str
    path: str
    title: str

    def to_json(self) -> dict[str, str]:
        return {"id": self.id, "path": self.path, "title": self.title}


KNOWN_RUNBOOKS = (
    RunbookReference(
        id="ubuntu-operator",
        path="docs/runbooks/UBUNTU_OPERATOR.md",
        title="ubuntu-1 host operator runbook",
    ),
    RunbookReference(
        id="access-operator",
        path="docs/runbooks/ACCESS.md",
        title="Loopback and SSH-tunnel access runbook",
    ),
    RunbookReference(
        id="qualification-operator",
        path="docs/runbooks/QUALIFICATION.md",
        title="Frozen target and support matrix qualification runbook",
    ),
)


def known_runbook_reference(identifier: str) -> RunbookReference:
    """Return the bounded runbook reference for ``identifier``.

    Only registry ids are accepted; paths, absolute locations, and
    traversal attempts raise :class:`ValueError`.
    """
    for reference in KNOWN_RUNBOOKS:
        if reference.id == identifier:
            return reference
    raise ValueError(f"unknown runbook reference: {identifier!r}")
