from __future__ import annotations

import pytest

from morpheus.core.ownership import (
    AdoptionCandidate,
    InferenceIdentity,
    ManagedTarget,
    OwnershipMode,
    OwnershipPolicy,
    ResourceAction,
    ResourceIdentity,
    ResourceKind,
    lifecycle_identity_guard,
)
from morpheus.core.state_machines import MachineKind, MachineRecord, StateMachine

pytestmark = pytest.mark.acceptance

DIGEST = "d" * 64


def test_RUNM_001_observe_mode_stays_read_only_for_existing_ubuntu-1_operations() -> None:
    policy = OwnershipPolicy(project_id="morpheus-ubuntu-1")
    owned = ResourceIdentity(
        kind=ResourceKind.CONTAINER,
        name="morpheus-agent",
        labels={"io.morpheus.project": "morpheus-ubuntu-1"},
    )
    external = ResourceIdentity(kind=ResourceKind.CONTAINER, name="history-coder", labels={})

    assert policy.allows(action=ResourceAction.INSPECT, resource=owned) is True
    for action in ResourceAction:
        if action is ResourceAction.INSPECT:
            continue
        assert policy.allows(action=action, resource=owned) is False
    for action in ResourceAction:
        assert policy.allows(action=action, resource=external) is False


def test_RUNM_001_managed_promotion_requires_its_own_confirmation() -> None:
    record = MachineRecord(
        machine=MachineKind.PROMOTION, record_id="plan-libri-gguf-q4-0001", state="proposed"
    )

    preflighted = StateMachine.transition(record, "preflighted").record
    assert StateMachine.transition(preflighted, "activating").accepted is False

    confirmed = StateMachine.transition(preflighted, "confirmed").record
    activated = StateMachine.transition(confirmed, "activating").record
    assert activated.state == "activating"

    active = StateMachine.transition(activated, "active").record
    assert active.terminal
    assert StateMachine.transition(active, "preflighted").accepted is False


def test_RUNM_001_adoption_requires_capture_preflight_and_confirmation() -> None:
    external = InferenceIdentity(identity_id="history-coder", mode=OwnershipMode.EXTERNAL_OBSERVED)
    candidate = AdoptionCandidate(
        candidate_id="adopt-history-coder-0001",
        external_identity=external,
        pre_state_digest=DIGEST,
        pre_state_scope=("container:history-coder", "port:8000"),
        proposed_target=ManagedTarget(
            identity_id="morpheus-libri-gguf-1",
            deployment_plan_id="plan-libri-gguf-q4-0001",
            owned_root="/mnt/data/morpheus/models",
        ),
        confirmation="adopt history-coder",
        recovery_plan_id="recovery-cleanup-0001",
    )
    record = MachineRecord(
        machine=MachineKind.ADOPTION, record_id=candidate.candidate_id, state="proposed"
    )

    captured = StateMachine.transition(record, "pre_state_captured").record
    preflighted = StateMachine.transition(captured, "preflighted").record
    assert StateMachine.transition(preflighted, "transferring").accepted is False

    confirmed = StateMachine.transition(preflighted, "confirmed").record
    transferring = StateMachine.transition(confirmed, "transferring").record
    validating = StateMachine.transition(transferring, "validating").record
    adopted = StateMachine.transition(validating, "adopted").record

    assert adopted.terminal
    assert StateMachine.transition(adopted, "restoring").accepted is False
    with pytest.raises(TypeError):
        lifecycle_identity_guard(candidate)
