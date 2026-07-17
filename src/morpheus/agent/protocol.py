from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

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


class AgentLifecycleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    action: LifecycleAction
    result: dict[str, Any]
