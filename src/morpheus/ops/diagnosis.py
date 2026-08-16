"""Diagnosis service (AID-002/003/004).

Selects the provider from the configured mode, runs the analysis under
policy, and always returns a typed outcome: provider failure or a
disabled configuration never raises into the caller, so ordinary
diagnostics and runtime operation are never blocked.
"""

from __future__ import annotations

import logging

from morpheus.adapters.diagnosis import ExternalDiagnosisProvider, LocalDiagnosisProvider
from morpheus.adapters.diagnosis.protocol import DiagnosisProvider
from morpheus.core.diagnosis import (
    DiagnosisConfig,
    DiagnosisError,
    DiagnosisMode,
    DiagnosisOutcome,
    GroundedDiagnosis,
    ProviderUnavailableError,
    evaluate_grounding,
)
from morpheus.core.diagnostic_evidence import DiagnosticEvidence
from morpheus.ports.protocols import DiagnosisInference

logger = logging.getLogger(__name__)

_REFUSAL_CODES = {
    "ProviderTimeoutError": "provider_timeout",
    "MalformedOutputError": "provider_malformed_output",
    "ProviderRefusalError": "provider_refusal",
    "ConsentRequiredError": "consent_required",
    "CostExceededError": "cost_exceeded",
    "InjectionDetectedError": "provider_output_rejected",
    "ProviderUnavailableError": "provider_unavailable",
}


class DiagnosisService:
    def __init__(self, *, inference: DiagnosisInference | None = None) -> None:
        self._inference = inference

    async def run(
        self,
        evidence: DiagnosticEvidence,
        config: DiagnosisConfig,
        *,
        api_key: str = "",
    ) -> DiagnosisOutcome:
        if config.mode == DiagnosisMode.DISABLED:
            return DiagnosisOutcome(status="disabled", reason="diagnosis_disabled")
        provider = self._select_provider(config, api_key=api_key)
        try:
            diagnosis = await provider.diagnose(evidence, config)
        except DiagnosisError as error:
            code = _REFUSAL_CODES.get(type(error).__name__, "provider_failed")
            logger.warning("diagnosis provider failed: %s: %s", code, error)
            return DiagnosisOutcome(status="unavailable", reason=code)
        except Exception as error:  # provider failure never blocks diagnostics
            logger.warning("diagnosis provider failed unexpectedly: %s", error)
            return DiagnosisOutcome(status="unavailable", reason="provider_failed")
        grounding = _grounding_report(diagnosis, evidence)
        return DiagnosisOutcome(status="available", diagnosis=diagnosis, grounding=grounding)

    def _select_provider(self, config: DiagnosisConfig, *, api_key: str) -> DiagnosisProvider:
        if config.mode == DiagnosisMode.LOCAL:
            if self._inference is None:
                return _UnavailableProvider("local_inference_not_configured")
            return LocalDiagnosisProvider(self._inference)
        return ExternalDiagnosisProvider(api_key=api_key)


class _UnavailableProvider:
    """Typed placeholder used when a mode is selected but not wired."""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    async def diagnose(
        self, evidence: DiagnosticEvidence, config: DiagnosisConfig
    ) -> GroundedDiagnosis:
        raise ProviderUnavailableError(self._reason)


def _grounding_report(diagnosis: GroundedDiagnosis, evidence: DiagnosticEvidence) -> dict[str, str]:
    return {
        finding.text: verdict
        for finding, verdict in evaluate_grounding(diagnosis, evidence).items()
    }
