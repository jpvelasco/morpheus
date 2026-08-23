from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from morpheus.core.lifecycle import LifecycleAction


class AgentOperation(StrEnum):
    GPU_SUMMARY = "gpu_summary"
    HOST_SUMMARY = "host_summary"
    MORPHEUS_SERVICES = "morpheus_services"


class AgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    operation: AgentOperation


class AgentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    operation: AgentOperation
    result: dict[str, Any]


class AgentLifecycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    action: LifecycleAction
    version: str | None = Field(default=None, max_length=64)
    backup_id: str | None = Field(default=None, max_length=64)
    confirmation: str | None = Field(default=None, max_length=128)
    # RUNM-001: optional canonical plan identity carried with state-changing
    # requests. Observed/external ownership markers are never valid values.
    plan_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )

    @field_validator("plan_id")
    @classmethod
    def _reject_observed_ownership_markers(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip().lower()
        if "observed" in normalized or normalized.startswith("external"):
            raise ValueError(
                "plan identity must reference a Morpheus-owned managed plan, "
                f"not an observed/external target: {value!r}"
            )
        return value


class AgentLifecycleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    action: LifecycleAction
    result: dict[str, Any]
