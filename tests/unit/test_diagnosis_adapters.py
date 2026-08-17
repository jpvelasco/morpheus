"""Unit tests: diagnosis provider adapters (AID-002/003/004).

Timeout, refusal, malformed output, cost, consent, and canary-absence
behavior must be deterministic and fixture-driven; provider failure must
never surface outside the typed adapter boundary.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from morpheus.adapters.diagnosis.external import ExternalDiagnosisProvider
from morpheus.adapters.diagnosis.local import LocalDiagnosisProvider
from morpheus.core.diagnosis import (
    ConsentRequiredError,
    CostExceededError,
    DiagnosisConfig,
    DiagnosisMode,
    GroundedDiagnosis,
    InjectionDetectedError,
    MalformedOutputError,
    ProviderRefusalError,
    ProviderTimeoutError,
)
from morpheus.core.diagnostic_evidence import (
    DiagnosticEvidence,
    DiagnosticProvenance,
    build_diagnostic_evidence,
)

GOOD_PAYLOAD = {
    "summary": "GPU check passed",
    "findings": [
        {
            "kind": "observation",
            "text": "GPU is healthy",
            "confidence": 0.9,
            "citations": [{"type": "evidence", "section": "health", "index": 0}],
            "missing_evidence": [],
        }
    ],
    "likely_causes": [],
    "proposed_checks": [{"type": "runbook", "id": "ubuntu-operator"}],
}


def config(**overrides: object) -> DiagnosisConfig:
    defaults: dict[str, object] = {
        "mode": DiagnosisMode.LOCAL,
        "provider_name": "fixture",
        "timeout_ms": 200,
        "max_cost": 100,
        "retention": "none",
        "data_destination": "local",
        "consent_required": True,
        "consent_granted": True,
        "canaries": {},
    }
    defaults.update(overrides)
    return DiagnosisConfig(**defaults)


def evidence() -> DiagnosticEvidence:
    return build_diagnostic_evidence(
        health={"status": "ready", "checks": {"gpu": {"status": "pass"}}},
        machine_profile={"memory": {"total_bytes": 1}},
        deployment={"version": "0.1.0"},
        metrics={},
        events=[],
        log_excerpts=[],
        regressions=[],
        runbooks=["ubuntu-operator"],
        provenance=DiagnosticProvenance("0.1.0", "a" * 64, "2026-08-15T12:00:00+00:00"),
    )


class FakeInference:
    def __init__(self, result: str, *, delay_s: float = 0.0) -> None:
        self.result = result
        self.delay_s = delay_s
        self.prompts: list[str] = []

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        return self.result


def test_local_provider_returns_grounded_diagnosis() -> None:
    provider = LocalDiagnosisProvider(FakeInference(json.dumps(GOOD_PAYLOAD)))
    diagnosis = asyncio.run(provider.diagnose(evidence(), config()))
    assert isinstance(diagnosis, GroundedDiagnosis)
    assert diagnosis.summary == "GPU check passed"


def test_local_provider_prompt_never_leaks_canary_values() -> None:
    provider = LocalDiagnosisProvider(FakeInference(json.dumps(GOOD_PAYLOAD)))
    cfg = config(canaries={"secret": "SENTINEL-77"})
    with pytest.raises(InjectionDetectedError):
        asyncio.run(provider.diagnose(evidence_with_canary(), cfg))


def evidence_with_canary() -> DiagnosticEvidence:
    return build_diagnostic_evidence(
        health={"status": "ready", "checks": {"gpu": {"status": "SENTINEL-77"}}},
        machine_profile={},
        deployment={"version": "0.1.0"},
        metrics={},
        events=[],
        log_excerpts=[],
        regressions=[],
        runbooks=[],
        provenance=DiagnosticProvenance("0.1.0", "a" * 64, "2026-08-15T12:00:00+00:00"),
    )


def test_local_provider_timeout_raises_provider_timeout() -> None:
    provider = LocalDiagnosisProvider(FakeInference(json.dumps(GOOD_PAYLOAD), delay_s=2.0))
    with pytest.raises(ProviderTimeoutError):
        asyncio.run(provider.diagnose(evidence(), config(timeout_ms=100)))


def test_local_provider_malformed_output_raises() -> None:
    provider = LocalDiagnosisProvider(FakeInference("definitely not json"))
    with pytest.raises(MalformedOutputError):
        asyncio.run(provider.diagnose(evidence(), config()))


def test_local_provider_refusal_output_raises_refusal() -> None:
    provider = LocalDiagnosisProvider(FakeInference(json.dumps({"refusal": "cannot help"})))
    with pytest.raises(ProviderRefusalError):
        asyncio.run(provider.diagnose(evidence(), config()))


def test_external_provider_requires_consent_before_request() -> None:
    provider = ExternalDiagnosisProvider()
    with pytest.raises(ConsentRequiredError):
        asyncio.run(provider.diagnose(evidence(), config(consent_granted=False)))


def test_external_provider_cost_guard_blocks_before_request() -> None:
    provider = ExternalDiagnosisProvider()
    with pytest.raises(CostExceededError):
        asyncio.run(
            provider.diagnose(
                evidence(),
                config(
                    mode=DiagnosisMode.EXTERNAL,
                    endpoint="https://provider.example/v1/analyze",
                    max_cost=1,
                    cost_per_1k_tokens=1000.0,
                ),
            )
        )


def test_external_provider_posts_bounded_payload_and_parses() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.content
        return httpx.Response(200, json=GOOD_PAYLOAD)

    transport = httpx.MockTransport(handler)
    provider = ExternalDiagnosisProvider(
        api_key="test-key", client=httpx.AsyncClient(transport=transport)
    )
    diagnosis = asyncio.run(
        provider.diagnose(
            evidence(),
            config(
                mode=DiagnosisMode.EXTERNAL,
                endpoint="https://provider.example/v1/analyze",
            ),
        )
    )
    assert isinstance(diagnosis, GroundedDiagnosis)


def test_external_provider_timeout_raises_provider_timeout() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated provider timeout", request=request)

    transport = httpx.MockTransport(handler)
    provider = ExternalDiagnosisProvider(
        api_key="test-key", client=httpx.AsyncClient(transport=transport)
    )
    with pytest.raises(ProviderTimeoutError):
        asyncio.run(
            provider.diagnose(
                evidence(),
                config(
                    mode=DiagnosisMode.EXTERNAL,
                    endpoint="https://provider.example/v1/analyze",
                    timeout_ms=100,
                ),
            )
        )


def test_external_provider_sets_authorization_header() -> None:
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization", ""))
        return httpx.Response(200, json=GOOD_PAYLOAD)

    transport = httpx.MockTransport(handler)
    provider = ExternalDiagnosisProvider(
        api_key="secret-key-1", client=httpx.AsyncClient(transport=transport)
    )
    asyncio.run(
        provider.diagnose(
            evidence(),
            config(
                mode=DiagnosisMode.EXTERNAL,
                endpoint="https://provider.example/v1/analyze",
            ),
        )
    )
    assert seen == ["Bearer secret-key-1"]
