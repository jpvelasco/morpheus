from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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
    request_id: str
    operation: AgentOperation
    result: dict[str, Any]
