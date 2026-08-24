"""Owned-path durable store for managed operation documents.

Every save is an atomic replace of the whole versioned envelope, so a
crash between two durable edges leaves either the previous or the next
complete snapshot on disk — never a torn document. Documents are keyed by
their content-derived ``operation_id``.
"""

from __future__ import annotations

from pathlib import Path

from morpheus.core.durable import atomic_replace
from morpheus.core.operations import (
    ManagedOperation,
    decode_operation,
    encode_operation,
)

_MAX_DOCUMENTS = 512


class OperationStoreError(RuntimeError):
    """The managed operation store could not be read or written."""


class OperationStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def _document_path(self, operation_id: str) -> Path:
        if not operation_id or "/" in operation_id or "\\" in operation_id:
            raise OperationStoreError("operation id is not a storable document name")
        return self._root / f"{operation_id}.json"

    def save(self, operation: ManagedOperation) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        atomic_replace(self._document_path(operation.operation_id), encode_operation(operation))

    def get(self, operation_id: str) -> ManagedOperation | None:
        path = self._document_path(operation_id)
        if not path.exists():
            return None
        try:
            return decode_operation(path.read_bytes())
        except (OSError, ValueError) as error:
            raise OperationStoreError(
                f"managed operation {operation_id!r} is unreadable: {error}"
            ) from error

    def list_all(self) -> tuple[ManagedOperation, ...]:
        """All stored operations, most recently updated first."""
        if not self._root.exists():
            return ()
        operations: list[ManagedOperation] = []
        for path in self._root.glob("*.json"):
            try:
                operations.append(decode_operation(path.read_bytes()))
            except (OSError, ValueError) as error:
                raise OperationStoreError(
                    f"managed operation document {path.name!r} is unreadable: {error}"
                ) from error
        operations.sort(
            key=lambda operation: (operation.updated_at, operation.operation_id), reverse=True
        )
        overflow = len(operations) - _MAX_DOCUMENTS
        if overflow > 0:
            for stale in operations[-overflow:]:
                self._document_path(stale.operation_id).unlink(missing_ok=True)
            operations = operations[:_MAX_DOCUMENTS]
        return tuple(operations)
