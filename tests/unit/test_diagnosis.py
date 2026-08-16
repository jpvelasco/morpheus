"""Unit tests: grounded diagnosis core (AID-002/003/004).

The core is pure and dependency-free: strict structured parsing of
provider output, deterministic grounding evaluation, and typed advisory
proposals that can never become arbitrary operations.
"""

from __future__ import annotations

import pytest

from morpheus.core.diagnosis import (
    ConfidenceOutOfRangeError,
    ConsentRequiredError,
    DiagnosisConfig,
    DiagnosisMode,
    GroundedDiagnosis,
    InjectionDetectedError,
    MalformedOutputError,
    ProposedCheck,
    evaluate_grounding,
    parse_grounded_diagnosis,
    reject_unsafe_proposals,
)
from morpheus.core.diagnostic_evidence import (
    DiagnosticEvidence,
    DiagnosticProvenance,
    build_diagnostic_evidence,
)


def config(**overrides: object) -> DiagnosisConfig:
    defaults: dict[str, object] = {
        "mode": DiagnosisMode.EXTERNAL,
        "provider_name": "fixture",
        "endpoint": "https://provider.example/v1/analyze",
        "timeout_ms": 5000,
        "max_cost": 100,
        "retention": "none",
        "data_destination": "external:fixture",
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
        events=[{"recorded_at": "2026-08-15T12:00:00+00:00", "message": "ok"}],
        log_excerpts=[],
        regressions=[],
        runbooks=["batwing-operator"],
        provenance=DiagnosticProvenance("0.1.0", "a" * 64, "2026-08-15T12:00:00+00:00"),
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
        },
        {
            "kind": "inference",
            "text": "Possibly needs more memory",
            "confidence": 0.4,
            "citations": [],
            "missing_evidence": ["memory usage over time"],
        },
    ],
    "likely_causes": [],
    "proposed_checks": [
        {"type": "runbook", "id": "batwing-operator"},
        {"type": "policy_plan", "kind": "repair"},
    ],
}


def test_parse_grounded_diagnosis_accepts_well_formed_output() -> None:
    diagnosis = parse_grounded_diagnosis(GOOD_PAYLOAD)
    assert isinstance(diagnosis, GroundedDiagnosis)
    assert diagnosis.summary == "GPU check passed"
    assert len(diagnosis.findings) == 2
    assert diagnosis.findings[0].confidence == 0.9
    assert diagnosis.proposed_checks == (
        ProposedCheck(type="runbook", id="batwing-operator"),
        ProposedCheck(type="policy_plan", kind="repair"),
    )


def test_parse_grounded_diagnosis_accepts_json_text_input() -> None:
    import json

    diagnosis = parse_grounded_diagnosis(json.dumps(GOOD_PAYLOAD))
    assert diagnosis.summary == "GPU check passed"


def test_parse_grounded_diagnosis_rejects_malformed_output() -> None:
    with pytest.raises(MalformedOutputError):
        parse_grounded_diagnosis({})
    with pytest.raises(MalformedOutputError):
        parse_grounded_diagnosis({"findings": "nope"})
    with pytest.raises(MalformedOutputError):
        parse_grounded_diagnosis(
            {"summary": "x", "findings": [], "likely_causes": [], "proposed_checks": "shell"}
        )
    with pytest.raises(MalformedOutputError):
        parse_grounded_diagnosis("not json at all")


def test_parse_grounded_diagnosis_rejects_out_of_range_confidence() -> None:
    payload = {
        **GOOD_PAYLOAD,
        "findings": [
            {
                "kind": "inference",
                "text": "certain",
                "confidence": 1.5,
                "citations": [],
                "missing_evidence": [],
            }
        ],
    }
    with pytest.raises(ConfidenceOutOfRangeError):
        parse_grounded_diagnosis(payload)


def test_parse_grounded_diagnosis_rejects_unknown_runbook_citation() -> None:
    payload = {
        **GOOD_PAYLOAD,
        "findings": [
            {
                "kind": "observation",
                "text": "unproven",
                "confidence": 0.9,
                "citations": [{"type": "runbook", "id": "totally-fake-runbook"}],
                "missing_evidence": [],
            }
        ],
    }
    with pytest.raises(InjectionDetectedError):
        parse_grounded_diagnosis(payload)


def test_parse_grounded_diagnosis_rejects_unknown_evidence_section() -> None:
    payload = {
        **GOOD_PAYLOAD,
        "findings": [
            {
                "kind": "observation",
                "text": "unproven",
                "confidence": 0.9,
                "citations": [{"type": "evidence", "section": "prompts", "index": 0}],
                "missing_evidence": [],
            }
        ],
    }
    with pytest.raises(InjectionDetectedError):
        parse_grounded_diagnosis(payload)


def test_evaluate_grounding_rejects_out_of_bounds_evidence_index() -> None:
    payload = {
        **GOOD_PAYLOAD,
        "findings": [
            {
                "kind": "observation",
                "text": "unproven",
                "confidence": 0.9,
                "citations": [{"type": "evidence", "section": "events", "index": 99}],
                "missing_evidence": [],
            }
        ],
    }
    diagnosis = parse_grounded_diagnosis(payload)
    with pytest.raises(InjectionDetectedError):
        evaluate_grounding(diagnosis, evidence())


def test_reject_unsafe_proposals_filters_shell_and_arbitrary_actions() -> None:
    payload = {
        **GOOD_PAYLOAD,
        "proposed_checks": [
            {"type": "shell", "command": "rm -rf /"},
            {"type": "docker", "command": "docker rm"},
            {"type": "runbook", "id": "batwing-operator"},
        ],
    }
    with pytest.raises(InjectionDetectedError):
        parse_grounded_diagnosis(payload)


def test_evaluate_grounding_marks_confident_uncited_claims_unsupported() -> None:
    diagnosis = parse_grounded_diagnosis(GOOD_PAYLOAD)
    report = evaluate_grounding(diagnosis, evidence())
    verdicts = {finding.text: verdict for finding, verdict in report.items()}
    assert verdicts["GPU is healthy"] == "grounded"
    assert verdicts["Possibly needs more memory"] == "unsupported"


def test_evaluate_grounding_accepts_runbook_citations() -> None:
    payload = {
        **GOOD_PAYLOAD,
        "findings": [
            {
                "kind": "observation",
                "text": "covered by runbook",
                "confidence": 0.9,
                "citations": [{"type": "runbook", "id": "batwing-operator"}],
                "missing_evidence": [],
            }
        ],
    }
    report = evaluate_grounding(parse_grounded_diagnosis(payload), evidence())
    assert list(report.values()) == ["grounded"]


def test_reject_unsafe_proposals_only_typed_plans_remain() -> None:
    diagnosis = parse_grounded_diagnosis(GOOD_PAYLOAD)
    assert reject_unsafe_proposals(diagnosis) == diagnosis.proposed_checks


def test_consent_required_error_is_a_diagnosis_error() -> None:
    with pytest.raises(ConsentRequiredError):
        raise ConsentRequiredError("consent required before evidence leaves the host")
