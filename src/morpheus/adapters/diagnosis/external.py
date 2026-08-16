"""External API diagnosis provider (AID-002/003/004).

Posts the bounded, redacted evidence payload to a configured API with an
explicit timeout, a cost guard estimated before any request, a consent
gate, and a canary-absence check on the outgoing payload. The API key is
injected by the caller and never travels through the core config.
"""

from __future__ import annotations

import httpx

from morpheus.adapters.diagnosis.common import (
    assert_no_canaries,
    build_diagnosis_prompt,
    parse_provider_text,
)
from morpheus.core.diagnosis import (
    ConsentRequiredError,
    CostExceededError,
    DiagnosisConfig,
    GroundedDiagnosis,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from morpheus.core.diagnostic_evidence import DiagnosticEvidence


def _estimated_tokens(payload: str) -> int:
    return max(1, len(payload.encode("utf-8")) // 4)


class ExternalDiagnosisProvider:
    def __init__(self, *, api_key: str = "", client: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
        self._client = client

    async def diagnose(
        self, evidence: DiagnosticEvidence, config: DiagnosisConfig
    ) -> GroundedDiagnosis:
        if config.consent_required and not config.consent_granted:
            raise ConsentRequiredError("evidence must not leave the host without explicit consent")
        if not config.endpoint:
            raise ProviderUnavailableError("external diagnosis provider has no endpoint")
        payload = build_diagnosis_prompt(evidence)
        assert_no_canaries(payload, config.canaries)
        if config.max_cost > 0 and config.cost_per_1k_tokens > 0:
            estimated_cost = _estimated_tokens(payload) * config.cost_per_1k_tokens / 1000
            if estimated_cost > config.max_cost:
                raise CostExceededError(
                    f"estimated diagnosis cost {estimated_cost:.3f} exceeds "
                    f"the configured budget {config.max_cost}"
                )
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        timeout = httpx.Timeout(config.timeout_ms / 1000)
        try:
            if self._client is not None:
                response = await self._client.post(
                    config.endpoint, content=payload, headers=headers, timeout=timeout
                )
            else:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(config.endpoint, content=payload, headers=headers)
        except httpx.TimeoutException as error:
            raise ProviderTimeoutError(
                f"external diagnosis provider timed out after {config.timeout_ms}ms"
            ) from error
        except httpx.HTTPError as error:
            raise ProviderUnavailableError("external diagnosis provider unreachable") from error
        if response.status_code != 200:
            raise ProviderUnavailableError(
                f"external diagnosis provider returned HTTP {response.status_code}"
            )
        result = parse_provider_text(response.text)
        assert isinstance(result, GroundedDiagnosis)
        return result
