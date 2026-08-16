"""Local model diagnosis provider (AID-002/003/004).

Uses an explicitly selected local model through a typed inference port.
The provider is fixture-testable and never touches the observed external
stack; wiring to a Morpheus-owned local model happens in physical
qualification phases.
"""

from __future__ import annotations

import asyncio

from morpheus.adapters.diagnosis.common import (
    assert_no_canaries,
    build_diagnosis_prompt,
    parse_provider_text,
)
from morpheus.core.diagnosis import (
    DiagnosisConfig,
    GroundedDiagnosis,
    ProviderTimeoutError,
)
from morpheus.core.diagnostic_evidence import DiagnosticEvidence
from morpheus.ports.protocols import DiagnosisInference


class LocalDiagnosisProvider:
    def __init__(self, inference: DiagnosisInference) -> None:
        self._inference = inference

    async def diagnose(
        self, evidence: DiagnosticEvidence, config: DiagnosisConfig
    ) -> GroundedDiagnosis:
        prompt = build_diagnosis_prompt(evidence)
        assert_no_canaries(prompt, config.canaries)
        timeout_s = config.timeout_ms / 1000
        try:
            text = await asyncio.wait_for(self._inference.complete(prompt), timeout=timeout_s)
        except TimeoutError as error:
            raise ProviderTimeoutError(
                f"local diagnosis provider timed out after {config.timeout_ms}ms"
            ) from error
        result = parse_provider_text(text)
        assert isinstance(result, GroundedDiagnosis)
        return result
