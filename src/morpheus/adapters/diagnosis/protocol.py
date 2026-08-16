"""Diagnosis provider protocol (AID-002).

Typed adapter boundary between the diagnosis service and any provider.
"""

from __future__ import annotations

from typing import Protocol

from morpheus.core.diagnosis import DiagnosisConfig, GroundedDiagnosis
from morpheus.core.diagnostic_evidence import DiagnosticEvidence


class DiagnosisProvider(Protocol):
    async def diagnose(
        self, evidence: DiagnosticEvidence, config: DiagnosisConfig
    ) -> GroundedDiagnosis: ...
