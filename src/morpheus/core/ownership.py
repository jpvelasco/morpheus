from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

PROJECT_LABEL = "io.morpheus.project"
PROTECTED_NAMES = frozenset({"ai", "ai_default", "open-webui", "coder-model"})

_IDENTITY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SCOPE_ITEM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_PLAN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class OwnershipMode(StrEnum):
    EXTERNAL_OBSERVED = "external_observed"
    MORPHEUS_MANAGED = "morpheus_managed"


@dataclass(frozen=True, slots=True)
class InferenceIdentity:
    identity_id: str
    mode: OwnershipMode
    discovery_source: str | None = None

    def __post_init__(self) -> None:
        if not _IDENTITY_ID.fullmatch(self.identity_id):
            raise ValueError("identity_id must be a bounded identifier")
        if self.discovery_source is not None and not _SCOPE_ITEM.fullmatch(self.discovery_source):
            raise ValueError("discovery_source must be a bounded value")

    def public_dict(self) -> dict[str, object]:
        return {
            "identity_id": self.identity_id,
            "mode": self.mode.value,
            "discovery_source": self.discovery_source,
        }


@dataclass(frozen=True, slots=True)
class ManagedTarget:
    identity_id: str
    deployment_plan_id: str
    owned_root: str

    def __post_init__(self) -> None:
        if not _IDENTITY_ID.fullmatch(self.identity_id):
            raise ValueError("identity_id must be a bounded identifier")
        if not _PLAN_ID.fullmatch(self.deployment_plan_id):
            raise ValueError("deployment_plan_id must be a bounded identifier")
        if not re.fullmatch(r"^/[^;$\n]{1,511}$", self.owned_root):
            raise ValueError("owned_root must be an absolute path without shell metacharacters")

    def public_dict(self) -> dict[str, object]:
        return {
            "identity_id": self.identity_id,
            "deployment_plan_id": self.deployment_plan_id,
            "owned_root": self.owned_root,
        }


@dataclass(frozen=True, slots=True)
class AdoptionCandidate:
    candidate_id: str
    external_identity: InferenceIdentity
    pre_state_digest: str
    pre_state_scope: tuple[str, ...]
    proposed_target: ManagedTarget
    confirmation: str
    recovery_plan_id: str | None = None

    def __post_init__(self) -> None:
        if not _IDENTITY_ID.fullmatch(self.candidate_id):
            raise ValueError("candidate_id must be a bounded identifier")
        if self.external_identity.mode is not OwnershipMode.EXTERNAL_OBSERVED:
            raise ValueError("an adoption candidate binds an external_observed identity")
        if not _DIGEST.fullmatch(self.pre_state_digest):
            raise ValueError("pre_state_digest must be a sha256 digest")
        if not self.pre_state_scope:
            raise ValueError("pre_state_scope must capture at least one exact item")
        if any(not _SCOPE_ITEM.fullmatch(item) for item in self.pre_state_scope):
            raise ValueError("pre_state_scope contains an unbounded item")
        if self.proposed_target.identity_id == self.external_identity.identity_id:
            raise ValueError("the proposed managed identity must be a new identity")
        if not self.confirmation:
            raise ValueError("an adoption candidate requires explicit operator confirmation")
        if self.recovery_plan_id is not None and not _PLAN_ID.fullmatch(self.recovery_plan_id):
            raise ValueError("recovery_plan_id must be a bounded identifier")

    def public_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "external_identity": self.external_identity.public_dict(),
            "pre_state_digest": self.pre_state_digest,
            "pre_state_scope": self.pre_state_scope,
            "proposed_target": self.proposed_target.public_dict(),
            "confirmation": self.confirmation,
            "recovery_plan_id": self.recovery_plan_id,
        }


def lifecycle_identity_guard(target: object) -> InferenceIdentity:
    """Public lifecycle boundary: only exact inference identities pass.

    Adoption candidates, resource identities, and raw strings are not
    lifecycle targets and are rejected before any adapter can act on them.
    """
    if not isinstance(target, InferenceIdentity):
        raise TypeError("lifecycle operations require an exact InferenceIdentity")
    return target


class ResourceKind(StrEnum):
    CONTAINER = "container"
    NETWORK = "network"
    VOLUME = "volume"
    IMAGE = "image"


class ResourceAction(StrEnum):
    INSPECT = "inspect"
    START = "start"
    STOP = "stop"
    RESTART = "restart"
    REMOVE = "remove"
    BACKUP = "backup"
    RESTORE = "restore"


_ALLOWED_ACTIONS: Mapping[ResourceKind, frozenset[ResourceAction]] = MappingProxyType(
    {
        ResourceKind.CONTAINER: frozenset({ResourceAction.INSPECT}),
        ResourceKind.NETWORK: frozenset({ResourceAction.INSPECT}),
        ResourceKind.VOLUME: frozenset({ResourceAction.INSPECT}),
        ResourceKind.IMAGE: frozenset({ResourceAction.INSPECT}),
    }
)


@dataclass(frozen=True, slots=True)
class ResourceIdentity:
    kind: ResourceKind
    name: str
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "labels", MappingProxyType(dict(self.labels)))


@dataclass(frozen=True, slots=True)
class OwnershipPolicy:
    project_id: str
    protected_names: frozenset[str] = PROTECTED_NAMES

    def is_owned(self, resource: ResourceIdentity) -> bool:
        return (
            resource.name not in self.protected_names
            and resource.labels.get(PROJECT_LABEL) == self.project_id
        )

    def allows(self, *, action: ResourceAction, resource: ResourceIdentity) -> bool:
        """Authorize only explicit, read-only operations on owned resources.

        Matching an ownership label is necessary but never sufficient.  The
        resource must also be outside the protected inventory and the action
        must appear in the code-owned allowlist for its resource type.
        """
        return self.is_owned(resource) and action in _ALLOWED_ACTIONS[resource.kind]

    def authorize(self, *, action: ResourceAction, resource: ResourceIdentity) -> None:
        if not self.allows(action=action, resource=resource):
            raise PermissionError("resource action is not authorized")
