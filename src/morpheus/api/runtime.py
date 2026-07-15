from __future__ import annotations

import asyncio
from typing import Any

from morpheus.agent.protocol import AgentOperation, AgentResponse
from morpheus.ports.protocols import Clock, RuntimeAgentPort

_OPERATIONS = (
    AgentOperation.HOST_SUMMARY,
    AgentOperation.GPU_SUMMARY,
    AgentOperation.MORPHEUS_SERVICES,
)


async def runtime_snapshot(
    runtime_agent: RuntimeAgentPort | None,
    *,
    clock: Clock,
) -> dict[str, Any]:
    if runtime_agent is None:
        return {
            "status": "unavailable",
            "reason": "runtime_agent_not_configured",
            "observed_at": clock.utc_now().isoformat(),
            "checks": {},
        }

    outcomes = await asyncio.gather(
        *(runtime_agent.inspect(operation) for operation in _OPERATIONS),
        return_exceptions=True,
    )
    results: dict[AgentOperation, dict[str, Any]] = {}
    checks: dict[str, dict[str, Any]] = {}
    for operation, outcome in zip(_OPERATIONS, outcomes, strict=True):
        if isinstance(outcome, AgentResponse):
            results[operation] = outcome.result
            checks[operation.value] = {
                "status": "pass",
                "reason_code": "runtime_agent_probe_ready",
                "summary": _summary(operation, ready=True),
                "next_action": None,
            }
        else:
            checks[operation.value] = {
                "status": "fail",
                "reason_code": "runtime_agent_probe_failed",
                "summary": _summary(operation, ready=False),
                "next_action": "Verify the runtime agent service and its dedicated credential",
            }

    host = results.get(AgentOperation.HOST_SUMMARY, {})
    gpu = results.get(AgentOperation.GPU_SUMMARY, {})
    services = results.get(AgentOperation.MORPHEUS_SERVICES, {})
    successful = len(results)
    payload: dict[str, Any] = {
        "status": "available" if successful == len(_OPERATIONS) else "degraded",
        "observed_at": clock.utc_now().isoformat(),
        "checks": checks,
    }
    if not successful:
        payload["status"] = "unavailable"
        payload["reason"] = "runtime_agent_unreachable"
    for field in ("memory", "disk", "process", "clock"):
        if field in host:
            payload[field] = host[field]
    if isinstance(gpu.get("gpus"), list):
        payload["gpus"] = gpu["gpus"]
        if gpu["gpus"]:
            payload["gpu"] = gpu["gpus"][0]
    if isinstance(services.get("containers"), list):
        payload["services"] = services["containers"]
    return payload


def _summary(operation: AgentOperation, *, ready: bool) -> str:
    subject = {
        AgentOperation.HOST_SUMMARY: "Host memory, storage, process, and clock evidence",
        AgentOperation.GPU_SUMMARY: "GPU evidence",
        AgentOperation.MORPHEUS_SERVICES: "Morpheus service evidence",
    }[operation]
    return f"{subject} is {'available' if ready else 'unavailable'}"
