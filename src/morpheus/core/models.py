from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ServedModel:
    root: str | None
    aliases: tuple[str, ...]
    context_window: int | None = None

    def __post_init__(self) -> None:
        aliases = tuple(dict.fromkeys(alias.strip() for alias in self.aliases if alias.strip()))
        if not aliases:
            raise ValueError("at least one served model alias is required")
        if self.context_window is not None and self.context_window <= 0:
            raise ValueError("context_window must be positive")
        object.__setattr__(self, "aliases", aliases)
