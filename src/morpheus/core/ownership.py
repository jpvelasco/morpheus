from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

PROJECT_LABEL = "io.morpheus.project"
PROTECTED_NAMES = frozenset({"ai", "ai_default", "open-webui", "qwopus-coder"})


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
