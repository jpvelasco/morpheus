from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

PROJECT_LABEL = "io.morpheus.project"
PROTECTED_NAMES = frozenset({"ai", "ai_default", "open-webui", "history-coder"})


class ResourceKind(StrEnum):
    CONTAINER = "container"
    NETWORK = "network"
    VOLUME = "volume"
    IMAGE = "image"


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
