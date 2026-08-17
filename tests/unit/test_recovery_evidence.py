"""Unit tests: transition recovery evidence records (IMG-004)."""

from __future__ import annotations

from morpheus.core.recovery_evidence import (
    InferencePreState,
    build_recovery_evidence,
    verify_recovery,
)


def make_pre_state() -> InferencePreState:
    return InferencePreState(
        image_ref="ghcr.io/example/coder:qwen36-27b@sha256:" + "a" * 64,
        model_revision="qwen36-27b-nvfp4",
        arguments=("--max-model-len", "131072"),
        endpoint_healthy=True,
    )


def test_recovery_evidence_verifies_identical_pre_and_post_state() -> None:
    pre = make_pre_state()
    evidence = build_recovery_evidence(pre, pre)
    assert evidence.verified is True
    assert evidence.reasons == ()
    assert evidence.pre_state == pre
    assert evidence.post_state == pre


def test_recovery_evidence_catches_image_change() -> None:
    pre = make_pre_state()
    post = InferencePreState(
        image_ref="ghcr.io/example/coder:other@sha256:" + "b" * 64,
        model_revision=pre.model_revision,
        arguments=pre.arguments,
        endpoint_healthy=True,
    )
    evidence = build_recovery_evidence(pre, post)
    assert evidence.verified is False
    assert any("image" in reason for reason in evidence.reasons)


def test_recovery_evidence_catches_model_revision_change() -> None:
    pre = make_pre_state()
    post = InferencePreState(
        image_ref=pre.image_ref,
        model_revision="different-revision",
        arguments=pre.arguments,
        endpoint_healthy=True,
    )
    evidence = build_recovery_evidence(pre, post)
    assert evidence.verified is False
    assert any("revision" in reason for reason in evidence.reasons)


def test_recovery_evidence_catches_argument_change() -> None:
    pre = make_pre_state()
    post = InferencePreState(
        image_ref=pre.image_ref,
        model_revision=pre.model_revision,
        arguments=("--max-model-len", "65536"),
        endpoint_healthy=True,
    )
    evidence = build_recovery_evidence(pre, post)
    assert evidence.verified is False
    assert any("arguments" in reason for reason in evidence.reasons)


def test_recovery_evidence_catches_unhealthy_endpoint() -> None:
    pre = make_pre_state()
    post = InferencePreState(
        image_ref=pre.image_ref,
        model_revision=pre.model_revision,
        arguments=pre.arguments,
        endpoint_healthy=False,
    )
    evidence = build_recovery_evidence(pre, post)
    assert evidence.verified is False
    assert any("endpoint" in reason for reason in evidence.reasons)


def test_recovery_evidence_records_versioned_fields() -> None:
    pre = make_pre_state()
    evidence = build_recovery_evidence(pre, pre)
    assert evidence.schema_version == 1
    assert isinstance(evidence.verified_fields, tuple)
    assert "image_ref" in evidence.verified_fields
    assert "model_revision" in evidence.verified_fields
    assert "arguments" in evidence.verified_fields
    assert "endpoint_healthy" in evidence.verified_fields


def test_verify_recovery_matches_build_recovery_evidence() -> None:
    pre = make_pre_state()
    evidence = build_recovery_evidence(pre, pre)
    assert verify_recovery(pre, pre) == evidence
    assert verify_recovery(pre, pre).verified is True


def test_recovery_evidence_rejects_embedded_secrets_in_arguments() -> None:
    pre = make_pre_state()
    post = InferencePreState(
        image_ref=pre.image_ref,
        model_revision=pre.model_revision,
        arguments=("--api-key", "sk-secret"),
        endpoint_healthy=True,
    )
    evidence = build_recovery_evidence(pre, post)
    assert evidence.verified is False
    assert any("secret-shaped" in reason for reason in evidence.reasons)
    assert "sk-secret" not in " ".join(evidence.reasons)
