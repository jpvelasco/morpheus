from __future__ import annotations

import pytest

from morpheus.core.ownership import (
    OwnershipPolicy,
    ResourceAction,
    ResourceIdentity,
    ResourceKind,
)


def test_INV_002_name_alone_never_grants_ownership() -> None:
    policy = OwnershipPolicy(project_id="personal")
    forged = ResourceIdentity(
        kind=ResourceKind.CONTAINER,
        name="morpheus-api",
        labels={},
    )
    assert policy.is_owned(forged) is False


@pytest.mark.parametrize("name", ["coder-model", "open-webui", "ai_default"])
def test_INV_001_protected_external_resources_are_rejected_even_with_forged_label(
    name: str,
) -> None:
    policy = OwnershipPolicy(project_id="personal")
    resource = ResourceIdentity(
        kind=ResourceKind.CONTAINER,
        name=name,
        labels={"io.morpheus.project": "personal"},
    )
    assert policy.is_owned(resource) is False


def test_INV_002_matching_label_grants_only_morpheus_resource_ownership() -> None:
    policy = OwnershipPolicy(project_id="personal")
    resource = ResourceIdentity(
        kind=ResourceKind.VOLUME,
        name="personal_morpheus_data",
        labels={"io.morpheus.project": "personal"},
    )
    assert policy.is_owned(resource) is True


def test_SEC_002_requires_an_explicit_allowed_action_for_the_resource_type() -> None:
    policy = OwnershipPolicy(project_id="personal")
    resource = ResourceIdentity(
        kind=ResourceKind.CONTAINER,
        name="personal-api",
        labels={"io.morpheus.project": "personal"},
    )

    assert policy.allows(action=ResourceAction.INSPECT, resource=resource) is True
    assert policy.allows(action=ResourceAction.STOP, resource=resource) is False
    with pytest.raises(PermissionError, match="not authorized"):
        policy.authorize(action=ResourceAction.REMOVE, resource=resource)


def test_SEC_002_protected_identity_is_denied_before_the_action_allowlist() -> None:
    policy = OwnershipPolicy(project_id="personal")
    protected_network = ResourceIdentity(
        kind=ResourceKind.NETWORK,
        name="ai_default",
        labels={"io.morpheus.project": "personal"},
    )

    assert policy.allows(action=ResourceAction.INSPECT, resource=protected_network) is False
    with pytest.raises(PermissionError, match="not authorized"):
        policy.authorize(action=ResourceAction.INSPECT, resource=protected_network)
