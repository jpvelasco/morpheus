from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from morpheus.core.ownership import (
    AdoptionCandidate,
    InferenceIdentity,
    ManagedTarget,
    OwnershipMode,
    ResourceAction,
    ResourceIdentity,
    ResourceKind,
    lifecycle_identity_guard,
)

VALID_ID = "coder-model"
VALID_PLAN = "plan-libri-gguf-q4-0001"
VALID_ROOT = "/mnt/data/morpheus/models"
VALID_DIGEST = "a" * 64


def _external() -> InferenceIdentity:
    return InferenceIdentity(identity_id=VALID_ID, mode=OwnershipMode.EXTERNAL_OBSERVED)


def _managed() -> InferenceIdentity:
    return InferenceIdentity(
        identity_id="morpheus-libri-gguf-1", mode=OwnershipMode.MORPHEUS_MANAGED
    )


def _target() -> ManagedTarget:
    return ManagedTarget(
        identity_id="morpheus-libri-gguf-1",
        deployment_plan_id=VALID_PLAN,
        owned_root=VALID_ROOT,
    )


def test_RUNM_001_ownership_has_exactly_two_inference_modes() -> None:
    assert {mode.value for mode in OwnershipMode} == {"external_observed", "morpheus_managed"}


def test_RUNM_001_identity_mode_is_immutable_after_construction() -> None:
    identity = _external()

    with pytest.raises(FrozenInstanceError):
        identity.mode = OwnershipMode.MORPHEUS_MANAGED  # type: ignore[misc]


def test_RUNM_001_discovery_and_names_never_change_the_mode() -> None:
    for _ in range(3):
        identity = InferenceIdentity(
            identity_id=VALID_ID,
            mode=OwnershipMode.EXTERNAL_OBSERVED,
            discovery_source="ai_default/127.0.0.1:8000",
        )
        assert identity.mode is OwnershipMode.EXTERNAL_OBSERVED


@pytest.mark.parametrize(
    "value",
    [
        "",
        "with spaces",
        "..",
        "/absolute/path",
        "C:/drive/path",
        "name" + "x" * 200,
        "a;rm -rf /",
        "$(touch pwned)",
    ],
)
def test_RUNM_001_identity_ids_are_bounded_and_cannot_carry_arbitrary_targets(value: str) -> None:
    with pytest.raises(ValueError):
        InferenceIdentity(identity_id=value, mode=OwnershipMode.EXTERNAL_OBSERVED)


def test_RUNM_001_managed_identity_binds_one_exact_plan_and_owned_root() -> None:
    target = _target()

    assert target.deployment_plan_id == VALID_PLAN
    assert target.owned_root == VALID_ROOT


@pytest.mark.parametrize(
    "value",
    [
        "",
        "relative/path",
        "..",
        "C:/windows/system32",
        "plan;true",
        "x" * 300,
    ],
)
def test_RUNM_001_managed_target_rejects_unbounded_plan_and_root_values(value: str) -> None:
    with pytest.raises(ValueError):
        ManagedTarget(
            identity_id=value,
            deployment_plan_id=VALID_PLAN,
            owned_root=VALID_ROOT,
        )
    with pytest.raises(ValueError):
        ManagedTarget(identity_id=VALID_ID, deployment_plan_id=value, owned_root=VALID_ROOT)
    with pytest.raises(ValueError):
        ManagedTarget(identity_id=VALID_ID, deployment_plan_id=VALID_PLAN, owned_root=value)


def test_RUNM_001_adoption_candidate_binds_external_identity_pre_state_and_managed_target() -> None:
    candidate = AdoptionCandidate(
        candidate_id="adopt-coder-model-0001",
        external_identity=_external(),
        pre_state_digest=VALID_DIGEST,
        pre_state_scope=("container:coder-model", "port:8000"),
        proposed_target=_target(),
        confirmation="adopt coder-model",
        recovery_plan_id="recovery-cleanup-0001",
    )

    assert candidate.external_identity.mode is OwnershipMode.EXTERNAL_OBSERVED
    assert candidate.proposed_target.deployment_plan_id == VALID_PLAN
    assert candidate.pre_state_digest == VALID_DIGEST


def test_RUNM_001_adoption_candidate_is_not_an_ordinary_identity() -> None:
    candidate = AdoptionCandidate(
        candidate_id="adopt-coder-model-0001",
        external_identity=_external(),
        pre_state_digest=VALID_DIGEST,
        pre_state_scope=("container:coder-model",),
        proposed_target=_target(),
        confirmation="adopt coder-model",
        recovery_plan_id="recovery-cleanup-0001",
    )

    assert not isinstance(candidate, InferenceIdentity)


def test_RUNM_001_adoption_candidate_rejects_managed_external_identity() -> None:
    with pytest.raises(ValueError, match="external_observed"):
        AdoptionCandidate(
            candidate_id="adopt-coder-model-0001",
            external_identity=_managed(),
            pre_state_digest=VALID_DIGEST,
            pre_state_scope=("container:coder-model",),
            proposed_target=_target(),
            confirmation="adopt coder-model",
            recovery_plan_id="recovery-cleanup-0001",
        )


@pytest.mark.parametrize(
    ("digest", "scope", "confirmation"),
    [
        ("not-hex", ("container:coder-model",), "adopt coder-model"),
        (VALID_DIGEST, (), "adopt coder-model"),
        (VALID_DIGEST, ("container:coder-model",), ""),
    ],
)
def test_RUNM_001_adoption_candidate_requires_exact_pre_state_and_confirmation(
    digest: str, scope: tuple[str, ...], confirmation: str
) -> None:
    with pytest.raises(ValueError):
        AdoptionCandidate(
            candidate_id="adopt-coder-model-0001",
            external_identity=_external(),
            pre_state_digest=digest,
            pre_state_scope=scope,
            proposed_target=_target(),
            confirmation=confirmation,
            recovery_plan_id="recovery-cleanup-0001",
        )


def test_RUNM_001_proposed_managed_identity_is_a_new_identity_not_the_external_one() -> None:
    candidate = AdoptionCandidate(
        candidate_id="adopt-coder-model-0001",
        external_identity=_external(),
        pre_state_digest=VALID_DIGEST,
        pre_state_scope=("container:coder-model",),
        proposed_target=_target(),
        confirmation="adopt coder-model",
        recovery_plan_id="recovery-cleanup-0001",
    )

    assert candidate.proposed_target.identity_id != candidate.external_identity.identity_id


def test_RUNM_001_lifecycle_boundary_rejects_adoption_candidates() -> None:
    candidate = AdoptionCandidate(
        candidate_id="adopt-coder-model-0001",
        external_identity=_external(),
        pre_state_digest=VALID_DIGEST,
        pre_state_scope=("container:coder-model",),
        proposed_target=_target(),
        confirmation="adopt coder-model",
        recovery_plan_id="recovery-cleanup-0001",
    )

    with pytest.raises(TypeError, match="InferenceIdentity"):
        lifecycle_identity_guard(candidate)


def test_RUNM_001_lifecycle_boundary_accepts_only_inference_identities() -> None:
    identity = _managed()
    resource = ResourceIdentity(
        kind=ResourceKind.CONTAINER, name="morpheus-libri-gguf-1", labels={}
    )

    assert lifecycle_identity_guard(identity) is identity
    with pytest.raises(TypeError):
        lifecycle_identity_guard(resource)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        lifecycle_identity_guard("coder-model")  # type: ignore[arg-type]


def test_RUNM_001_existing_resource_policy_stays_read_only_for_owned_resources() -> None:
    resource = ResourceIdentity(
        kind=ResourceKind.CONTAINER, name="morpheus-libri-gguf-1", labels={}
    )
    from morpheus.core.ownership import OwnershipPolicy

    policy = OwnershipPolicy(project_id="test-project")

    assert policy.allows(action=ResourceAction.INSPECT, resource=resource) is False
    assert policy.allows(action=ResourceAction.START, resource=resource) is False
