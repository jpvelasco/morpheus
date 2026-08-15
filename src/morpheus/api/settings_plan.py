"""Validated settings plan preview (OUI-005).

Plans validate proposed changes against the same pydantic rules the
process uses at startup and produce a before/after diff without applying
anything. Secret fields always fail with ``secret_not_editable``; they are
edited only in the secret env file. This module sits outside the pure core
because validation reuses the pydantic settings model.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from morpheus.config import MorpheusSettings
from morpheus.core.settings_catalog import SECRET_FIELDS, _kind_for


def _public_values(settings: MorpheusSettings) -> dict[str, Any]:
    values = settings.model_dump()
    for key in SECRET_FIELDS:
        values[key] = ""
    return values


def plan_settings(
    settings: MorpheusSettings,
    *,
    changes: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate proposed changes against startup rules and build a diff."""
    issues: list[dict[str, str]] = []
    for key in changes:
        if key not in MorpheusSettings.model_fields:
            issues.append({"key": key, "code": "unknown_setting", "message": "Unknown setting"})
        elif key in SECRET_FIELDS:
            issues.append(
                {
                    "key": key,
                    "code": "secret_not_editable",
                    "message": "Secret settings are edited in the secret env file",
                }
            )
    if issues:
        return _plan_result(settings, changes, issues, valid=False)

    candidates = _public_values(settings)
    candidates.update(changes)
    try:
        MorpheusSettings.model_validate(candidates)
    except ValidationError as error:
        for detail in error.errors():
            key = str(detail["loc"][0]) if detail["loc"] else next(iter(changes))
            issues.append(
                {"key": str(key), "code": "validation_failed", "message": str(detail["msg"])}
            )
        return _plan_result(settings, changes, issues, valid=False)

    diff: list[dict[str, Any]] = []
    for key, after in changes.items():
        before: Any = getattr(settings, key)
        if hasattr(before, "get_secret_value"):
            before = None
        diff.append(
            {
                "key": key,
                "before": before,
                "after": after,
                "restart_required": True,
                "kind": _kind_for(key, MorpheusSettings.model_fields[key]),
            }
        )
    return _plan_result(settings, changes, issues, valid=True, diff=diff)


def _plan_result(
    settings: MorpheusSettings,
    changes: Mapping[str, Any],
    issues: Sequence[dict[str, str]],
    *,
    valid: bool,
    diff: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "valid": valid,
        "changes": list(diff or ()),
        "issues": list(issues),
        "restart_required": valid and bool(changes),
        "description": "Review the diff and restart requirement before applying.",
    }
