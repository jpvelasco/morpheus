"""Diagnosis provider adapters (AID-002/003/004)."""

from morpheus.adapters.diagnosis.external import ExternalDiagnosisProvider
from morpheus.adapters.diagnosis.local import LocalDiagnosisProvider

__all__ = ["ExternalDiagnosisProvider", "LocalDiagnosisProvider"]
