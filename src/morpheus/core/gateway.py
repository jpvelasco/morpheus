from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class AliasMap:
    aliases: Mapping[str, str]

    def __post_init__(self) -> None:
        normalized: dict[str, str] = {}
        for alias, model in self.aliases.items():
            name = alias.strip().casefold()
            target = model.strip()
            if not name or not target or name in normalized:
                raise ValueError("model aliases and targets must be non-empty and unique")
            normalized[name] = target
        object.__setattr__(self, "aliases", MappingProxyType(normalized))

    def resolve(self, alias: str) -> str:
        try:
            return self.aliases[alias.strip().casefold()]
        except KeyError as error:
            raise KeyError(f"unknown model alias: {alias}") from error
