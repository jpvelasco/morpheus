"""Catalog persistence behind owned paths and durable replacement (SEL-001)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from morpheus.core.catalog import CatalogCollection, CatalogError
from morpheus.core.paths import OwnedPathError, OwnedPathResolver
from morpheus.ports.platform import DurableReplacementPort


class CatalogRepository:
    """Load and store catalog collections atomically inside an owned root."""

    def __init__(
        self,
        root: Path,
        resolver: OwnedPathResolver | None = None,
        replacement: DurableReplacementPort | None = None,
    ) -> None:
        self._resolver = resolver or OwnedPathResolver(root)
        self._replacement = replacement
        root.mkdir(parents=True, exist_ok=True)

    def _destination(self) -> Path:
        return self._resolver.resolve("catalog.json")

    def load(self) -> CatalogCollection | None:
        destination = self._destination()
        if not destination.is_file():
            return None
        try:
            payload = json.loads(destination.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CatalogError(f"cannot read catalog store: {error}") from error
        return CatalogCollection.from_dict(payload)

    def save(self, collection: CatalogCollection) -> str:
        """Atomically persist a collection and return its content digest."""
        destination = self._destination()
        staged = destination.with_suffix(".json.staged")
        try:
            staged.write_text(
                json.dumps(collection.to_dict(), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            if self._replacement is not None:
                self._replacement.replace(self._resolver, destination, staged)
            else:
                self._atomic_replace(destination, staged)
        except (OSError, OwnedPathError) as error:
            staged.unlink(missing_ok=True)
            raise OwnedPathError(f"cannot replace catalog store: {error}") from error
        return _digest_of(collection)

    def _atomic_replace(self, destination: Path, staged: Path) -> None:
        try:
            os.replace(staged, destination)
        except OSError as error:
            staged.unlink(missing_ok=True)
            raise OwnedPathError(f"cannot replace catalog store: {error}") from error


def _digest_of(collection: CatalogCollection) -> str:
    from morpheus.core.catalog import catalog_digest

    return catalog_digest(collection)


def load_or_seed(repository: CatalogRepository, seed: CatalogCollection) -> CatalogCollection:
    """Return the persisted collection, or persist and return the seed."""
    existing = repository.load()
    if existing is not None:
        return existing
    repository.save(seed)
    return seed
