"""Shared diagnosis provider helpers (AID-002/003/004).

Prompt assembly, refusal detection, and the canary-absence gate shared by
the local and external adapters. The prompt is bounded because the
evidence package is bounded and already redacted; nothing here adds
prompts, responses, or secrets to the request.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from morpheus.core.diagnosis import InjectionDetectedError, ProviderRefusalError
from morpheus.core.diagnostic_evidence import DiagnosticEvidence

_PROMPT_INSTRUCTIONS = (
    "You are a diagnostic assistant for the Morpheus inference appliance. "
    "Analyze ONLY the evidence sections below. Cite an evidence item "
    "(section name and index) or a known runbook for every material "
    "conclusion. Answer ONLY with a JSON object matching this schema: "
    '{"summary": string, "findings": [{"kind": "observation"|"inference", '
    '"text": string, "confidence": number 0..1, "citations": [{"type": '
    '"evidence", "section": string, "index": int} | {"type": "runbook", '
    '"id": string}], "missing_evidence": [string]}], "likely_causes": '
    '[string], "proposed_checks": [{"type": "runbook", "id": string} | '
    '{"type": "policy_plan", "kind": "install"|"repair"|"update"|"rollback"}], '
    '"missing_evidence": [string]}. No other output.'
)


def build_diagnosis_prompt(evidence: DiagnosticEvidence) -> str:
    """Assemble the bounded analysis prompt from the evidence sections."""
    sections = {section: getattr(evidence, section) for section in evidence.sections}
    return "\n".join(
        (
            _PROMPT_INSTRUCTIONS,
            "EVIDENCE:",
            json.dumps(sections, sort_keys=True, default=str),
        )
    )


def assert_no_canaries(payload: str, canaries: Mapping[str, str]) -> None:
    """Refuse the request if a privacy canary would leave the host."""
    for canary in canaries.values():
        if canary and canary in payload:
            raise InjectionDetectedError(
                "privacy canary found in outgoing provider payload; refusing to send"
            )


def refusal_reason(raw: str) -> str | None:
    """Return the refusal text when the provider explicitly declines."""
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if isinstance(parsed, Mapping):
        reason = parsed.get("refusal")
        if isinstance(reason, str):
            return reason
    return None


def parse_provider_text(raw: str) -> object:
    """Parse provider text into a grounded diagnosis, mapping refusals."""
    reason = refusal_reason(raw)
    if reason is not None:
        raise ProviderRefusalError(reason)
    from morpheus.core.diagnosis import parse_grounded_diagnosis

    return parse_grounded_diagnosis(raw)
