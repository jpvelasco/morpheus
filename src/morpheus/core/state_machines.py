from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, fields
from enum import StrEnum
from types import MappingProxyType

from morpheus.core.records import _IDENTIFIER, CURRENT_SCHEMA_VERSION

_INITIAL = {
    "acquisition": "planned",
    "campaign": "planned",
    "promotion": "proposed",
    "rollback": "requested",
    "adoption": "proposed",
}

_TRANSITIONS: Mapping[str, Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "acquisition": MappingProxyType(
            {
                "planned": ("acquiring", "cancelled"),
                "acquiring": ("verified", "cancelled", "failed"),
                "verified": ("staged", "failed"),
            }
        ),
        "campaign": MappingProxyType(
            {
                "planned": ("authorized", "cancelled"),
                "authorized": ("running", "cancelled"),
                "running": ("succeeded", "cancelled", "aborted", "failed"),
            }
        ),
        "promotion": MappingProxyType(
            {
                "proposed": ("preflighted", "rejected"),
                "preflighted": ("confirmed", "rejected"),
                "confirmed": ("activating",),
                "activating": ("active", "recovering"),
                "recovering": ("rolled_back", "failed"),
            }
        ),
        "rollback": MappingProxyType(
            {
                "requested": ("preflighted", "rejected"),
                "preflighted": ("restoring", "rejected"),
                "restoring": ("verified", "failed"),
                "verified": ("completed", "failed"),
            }
        ),
        "adoption": MappingProxyType(
            {
                "proposed": ("pre_state_captured", "rejected"),
                "pre_state_captured": ("preflighted", "rejected"),
                "preflighted": ("confirmed", "rejected"),
                "confirmed": ("transferring",),
                "transferring": ("validating", "restoring"),
                "validating": ("adopted", "restoring"),
                "restoring": ("restored", "failed"),
            }
        ),
    }
)

_TERMINAL = {
    "acquisition": frozenset({"staged", "cancelled", "failed"}),
    "campaign": frozenset({"succeeded", "cancelled", "aborted", "failed"}),
    "promotion": frozenset({"active", "rejected", "rolled_back", "failed"}),
    "rollback": frozenset({"completed", "rejected", "failed"}),
    "adoption": frozenset({"adopted", "rejected", "restored", "failed"}),
}

_STATES = {
    machine: frozenset(_TRANSITIONS[machine])
    | _TERMINAL[machine]
    | frozenset(target for allowed in _TRANSITIONS[machine].values() for target in allowed)
    for machine in _TRANSITIONS
}


class MachineKind(StrEnum):
    ACQUISITION = "acquisition"
    CAMPAIGN = "campaign"
    PROMOTION = "promotion"
    ROLLBACK = "rollback"
    ADOPTION = "adoption"


class StateTransitionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MachineRecord:
    machine: MachineKind
    record_id: str
    state: str
    schema_version: int = CURRENT_SCHEMA_VERSION
    checkpoint: int = 0

    def __post_init__(self) -> None:
        if self.machine.value not in _STATES:
            raise ValueError(f"unknown machine kind {self.machine.value!r}")
        if self.schema_version != CURRENT_SCHEMA_VERSION:
            raise ValueError(
                f"machine record schema version {self.schema_version} is not supported"
            )
        if self.checkpoint < 0:
            raise ValueError("checkpoint cannot be negative")
        if self.state not in _STATES[self.machine.value]:
            raise StateTransitionError(
                f"{self.state!r} is not a state of the {self.machine.value} machine"
            )
        if not _IDENTIFIER.fullmatch(self.record_id):
            raise ValueError("record_id must be a bounded identifier")

    @property
    def terminal(self) -> bool:
        return self.state in _TERMINAL[self.machine.value]

    def public_dict(self) -> dict[str, object]:
        return {
            "machine": self.machine.value,
            "record_id": self.record_id,
            "state": self.state,
            "schema_version": self.schema_version,
            "checkpoint": self.checkpoint,
        }


@dataclass(frozen=True, slots=True)
class StateTransitionResult:
    accepted: bool
    record: MachineRecord | None
    audit: str


class StateMachine:
    @staticmethod
    def transition(record: MachineRecord, target: str) -> StateTransitionResult:
        """Apply one durable edge or reject it without touching the record.

        Failures that are not listed in the architecture transition table
        leave the current durable record unchanged and produce a separate
        audit result; adapters cannot invent a transition.
        """
        if not isinstance(record, MachineRecord):
            raise TypeError("transitions require an exact MachineRecord")
        machine = record.machine.value
        if record.terminal:
            return StateTransitionResult(
                accepted=False,
                record=record,
                audit=f"{record.state} is terminal; terminal records never transition",
            )
        if target not in _STATES[machine]:
            return StateTransitionResult(
                accepted=False,
                record=record,
                audit=f"{target!r} is not a state of the {machine} machine",
            )
        allowed = _TRANSITIONS[machine].get(record.state, ())
        if target not in allowed:
            return StateTransitionResult(
                accepted=False,
                record=record,
                audit=f"no {record.state} -> {target} transition is defined",
            )
        advanced = MachineRecord(
            machine=record.machine,
            record_id=record.record_id,
            state=target,
            schema_version=record.schema_version,
            checkpoint=record.checkpoint + 1,
        )
        return StateTransitionResult(accepted=True, record=advanced, audit="")


def encode_machine_record(record: MachineRecord) -> bytes:
    """Canonical durable checkpoint encoding with the shared schema rules."""
    return json.dumps(
        {
            "record_type": "machine_record",
            "schema_version": record.schema_version,
            "record_id": record.record_id,
            "payload": record.public_dict(),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def decode_machine_record(data: bytes) -> MachineRecord:
    document = json.loads(data.decode())
    if not isinstance(document, dict):
        raise ValueError("machine record must be a JSON object")
    if document.get("record_type") != "machine_record":
        raise ValueError("envelope is not a machine record")
    payload = document.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("machine record payload must be an object")
    expected = {field.name for field in fields(MachineRecord)}
    if set(payload) != expected:
        raise ValueError("machine record payload must contain exactly its declared fields")
    record = MachineRecord(
        machine=MachineKind(payload["machine"]),
        record_id=payload["record_id"],
        state=payload["state"],
        schema_version=payload["schema_version"],
        checkpoint=payload["checkpoint"],
    )
    if record.schema_version != document.get("schema_version"):
        raise ValueError("machine record schema version mismatch")
    if record.record_id != document.get("record_id"):
        raise ValueError("machine record identity mismatch")
    return record
