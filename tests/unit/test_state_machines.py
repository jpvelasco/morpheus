from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from morpheus.core.state_machines import (
    MachineKind,
    MachineRecord,
    StateMachine,
    StateTransitionError,
    StateTransitionResult,
    decode_machine_record,
    encode_machine_record,
)

VALID_RECORD_ID = "plan-libri-gguf-q4-0001"


def _record(machine: MachineKind, state: str) -> MachineRecord:
    return MachineRecord(machine=machine, record_id=VALID_RECORD_ID, state=state)


VALID_CHAINS = (
    (
        MachineKind.ACQUISITION,
        ("planned", "acquiring", "verified", "staged"),
    ),
    (
        MachineKind.CAMPAIGN,
        ("planned", "authorized", "running", "succeeded"),
    ),
    (
        MachineKind.PROMOTION,
        ("proposed", "preflighted", "confirmed", "activating", "active"),
    ),
    (
        MachineKind.PROMOTION,
        ("proposed", "preflighted", "confirmed", "activating", "recovering", "rolled_back"),
    ),
    (
        MachineKind.ROLLBACK,
        ("requested", "preflighted", "restoring", "verified", "completed"),
    ),
    (
        MachineKind.ADOPTION,
        (
            "proposed",
            "pre_state_captured",
            "preflighted",
            "confirmed",
            "transferring",
            "validating",
            "adopted",
        ),
    ),
    (
        MachineKind.ADOPTION,
        (
            "proposed",
            "pre_state_captured",
            "preflighted",
            "confirmed",
            "transferring",
            "validating",
            "restoring",
            "restored",
        ),
    ),
)


@pytest.mark.parametrize(("machine", "chain"), VALID_CHAINS)
def test_RUNM_001_state_machines_follow_the_architecture_transition_tables(
    machine: MachineKind, chain: tuple[str, ...]
) -> None:
    record = _record(machine, chain[0])
    for target in chain[1:]:
        result = StateMachine.transition(record, target)
        assert result.accepted is True
        assert result.audit == ""
        record = result.record
        assert record.state == target

    assert record.terminal


@pytest.mark.parametrize(
    ("machine", "current", "target"),
    [
        (MachineKind.ACQUISITION, "planned", "verified"),
        (MachineKind.ACQUISITION, "acquiring", "staged"),
        (MachineKind.ACQUISITION, "planned", "failed"),
        (MachineKind.CAMPAIGN, "planned", "running"),
        (MachineKind.CAMPAIGN, "authorized", "succeeded"),
        (MachineKind.PROMOTION, "proposed", "activating"),
        (MachineKind.PROMOTION, "preflighted", "active"),
        (MachineKind.ROLLBACK, "requested", "restoring"),
        (MachineKind.ROLLBACK, "preflighted", "completed"),
        (MachineKind.ADOPTION, "proposed", "transferring"),
        (MachineKind.ADOPTION, "pre_state_captured", "confirmed"),
        (MachineKind.ADOPTION, "transferring", "adopted"),
    ],
)
def test_RUNM_001_invalid_transitions_leave_the_durable_record_unchanged(
    machine: MachineKind, current: str, target: str
) -> None:
    record = _record(machine, current)
    before = record

    result = StateMachine.transition(record, target)

    assert result.accepted is False
    assert result.record is before
    assert result.audit != ""
    assert result.record.state == current


def test_RUNM_001_terminal_records_never_transition_again() -> None:
    terminals = (
        (MachineKind.ACQUISITION, "staged"),
        (MachineKind.ACQUISITION, "cancelled"),
        (MachineKind.ACQUISITION, "failed"),
        (MachineKind.CAMPAIGN, "succeeded"),
        (MachineKind.CAMPAIGN, "aborted"),
        (MachineKind.PROMOTION, "active"),
        (MachineKind.PROMOTION, "rejected"),
        (MachineKind.PROMOTION, "rolled_back"),
        (MachineKind.ROLLBACK, "completed"),
        (MachineKind.ADOPTION, "adopted"),
        (MachineKind.ADOPTION, "restored"),
    )
    for machine, state in terminals:
        record = _record(machine, state)
        result = StateMachine.transition(record, "proposed")

        assert result.accepted is False
        assert "terminal" in result.audit


def test_RUNM_001_unknown_states_and_machines_are_rejected() -> None:
    with pytest.raises(ValueError):
        MachineRecord(machine=MachineKind.PROMOTION, record_id=VALID_RECORD_ID, state="invented")
    with pytest.raises(ValueError):
        MachineRecord(
            machine=MachineKind.ADOPTION,
            record_id=VALID_RECORD_ID,
            state="confirmed",
            schema_version=0,
        )


def test_RUNM_001_records_are_immutable_and_checkpointed_on_every_edge() -> None:
    record = _record(MachineKind.ROLLBACK, "requested")
    advanced = StateMachine.transition(record, "preflighted").record

    with pytest.raises(FrozenInstanceError):
        record.state = "preflighted"  # type: ignore[misc]
    assert advanced.checkpoint == record.checkpoint + 1


def test_RUNM_001_failed_transition_does_not_advance_the_checkpoint() -> None:
    record = _record(MachineKind.CAMPAIGN, "planned")

    result = StateMachine.transition(record, "running")

    assert result.accepted is False
    assert result.record.checkpoint == record.checkpoint


def test_RUNM_001_a_transition_in_one_machine_never_touches_another() -> None:
    campaign = _record(MachineKind.CAMPAIGN, "planned")
    adoption = _record(MachineKind.ADOPTION, "proposed")

    advanced_campaign = StateMachine.transition(campaign, "authorized").record

    assert advanced_campaign.state == "authorized"
    assert adoption.state == "proposed"
    assert StateMachine.transition(adoption, "transferring").accepted is False


def test_RUNM_001_adoption_is_the_only_machine_that_proposes_ownership_transfer() -> None:
    initial_states = {
        MachineKind.ACQUISITION: "planned",
        MachineKind.CAMPAIGN: "planned",
        MachineKind.PROMOTION: "proposed",
        MachineKind.ROLLBACK: "requested",
    }
    for machine, initial in initial_states.items():
        record = _record(machine, initial)
        result = StateMachine.transition(record, "transferring")

        assert result.accepted is False


def test_RUNM_001_promotion_and_adoption_require_confirmation_states() -> None:
    promotion = StateMachine.transition(
        _record(MachineKind.PROMOTION, "proposed"), "preflighted"
    ).record
    adoption = StateMachine.transition(
        StateMachine.transition(
            _record(MachineKind.ADOPTION, "proposed"), "pre_state_captured"
        ).record,
        "preflighted",
    ).record

    assert StateMachine.transition(promotion, "activating").accepted is False
    assert promotion.state == "preflighted"
    assert StateMachine.transition(adoption, "transferring").accepted is False
    assert adoption.state == "preflighted"

    confirmed_promotion = StateMachine.transition(promotion, "confirmed").record
    confirmed_adoption = StateMachine.transition(adoption, "confirmed").record

    assert StateMachine.transition(confirmed_promotion, "activating").accepted is True
    assert StateMachine.transition(confirmed_adoption, "transferring").accepted is True


def test_RUNM_001_state_transition_error_type_is_public() -> None:
    assert issubclass(StateTransitionError, ValueError)
    assert isinstance(
        StateTransitionResult(accepted=False, record=None, audit="no"), StateTransitionResult
    )


def test_RUNM_001_machine_kinds_are_exactly_the_five_separate_machines() -> None:
    assert {machine.value for machine in MachineKind} == {
        "acquisition",
        "campaign",
        "promotion",
        "rollback",
        "adoption",
    }


def test_RUNM_001_machine_record_codec_round_trips_exactly() -> None:
    record = _record(MachineKind.CAMPAIGN, "running")

    restored = decode_machine_record(encode_machine_record(record))

    assert restored == record
    assert restored.machine == MachineKind.CAMPAIGN
    assert restored.record_id == VALID_RECORD_ID
    assert restored.checkpoint == record.checkpoint


@pytest.mark.parametrize("mutation", ["record_type", "schema_version", "identity", "payload_field"])
def test_RUNM_001_machine_record_codec_rejects_tampered_envelopes(
    mutation: str,
) -> None:
    record = _record(MachineKind.ACQUISITION, "acquiring")
    document = json.loads(encode_machine_record(record).decode())

    if mutation == "record_type":
        document["record_type"] = "deployment_plan"
    elif mutation == "schema_version":
        document["schema_version"] = 0
    elif mutation == "identity":
        document["record_id"] = "plan-other-0001"
    elif mutation == "payload_field":
        document["payload"]["extra"] = 1

    with pytest.raises(ValueError, match="machine record"):
        decode_machine_record(json.dumps(document).encode())


def test_RUNM_001_machine_record_codec_rejects_non_object_envelope() -> None:
    with pytest.raises(ValueError, match="machine record"):
        decode_machine_record(b"[]")
    with pytest.raises(ValueError, match="machine record"):
        decode_machine_record(json.dumps({"record_type": "machine_record"}).encode())
    with pytest.raises(ValueError, match="machine record"):
        decode_machine_record(
            json.dumps({"record_type": "machine_record", "payload": {"partial": True}}).encode()
        )
