from __future__ import annotations

import pytest

from morpheus.core.ownership import OwnershipPolicy, ResourceIdentity, ResourceKind


def test_INV_002_name_alone_never_grants_ownership() -> None:
    policy = OwnershipPolicy(project_id="personal")
    forged = ResourceIdentity(
        kind=ResourceKind.CONTAINER,
        name="morpheus-api",
        labels={},
    )
    assert policy.is_owned(forged) is False


@pytest.mark.parametrize("name", ["qwopus-coder", "open-webui", "ai_default"])
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
