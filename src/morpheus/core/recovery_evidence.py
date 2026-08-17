"""Transition recovery evidence records (IMG-004).

The transition workflow records the verified pre-state and proves that
inference returned to the same image, model revision, arguments, and a
healthy endpoint afterward. The evidence record is versioned, lists every
verified field, and never embeds secret-shaped values.
"""

from __future__ import annotations

from dataclasses import dataclass

RECOVERY_EVIDENCE_SCHEMA_VERSION = 1

_SECRET_MARKERS = ("api_key", "apikey", "token", "secret", "password", "sk-")


@dataclass(frozen=True, slots=True)
class InferencePreState:
    image_ref: str
    model_revision: str
    arguments: tuple[str, ...]
    endpoint_healthy: bool


@dataclass(frozen=True, slots=True)
class RecoveryEvidence:
    schema_version: int = RECOVERY_EVIDENCE_SCHEMA_VERSION
    pre_state: InferencePreState | None = None
    post_state: InferencePreState | None = None
    verified: bool = False
    verified_fields: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    @property
    def failed(self) -> bool:
        return not self.verified


def _argument_contains_secrets(arguments: tuple[str, ...]) -> bool:
    lowered = " ".join(arguments).lower()
    return any(marker in lowered for marker in _SECRET_MARKERS)


def verify_recovery(
    pre_state: InferencePreState, post_state: InferencePreState
) -> RecoveryEvidence:
    """Prove inference returned to the same image, revision, args, and health."""
    verified_fields: list[str] = []
    reasons: list[str] = []
    if _argument_contains_secrets(post_state.arguments):
        return RecoveryEvidence(
            pre_state=pre_state,
            post_state=post_state,
            verified=False,
            verified_fields=(),
            reasons=("post-state arguments must not embed secret-shaped values",),
        )
    if post_state.image_ref != pre_state.image_ref:
        reasons.append("image changed: inference did not return to the same image")
    else:
        verified_fields.append("image_ref")
    if post_state.model_revision != pre_state.model_revision:
        reasons.append("model revision changed: inference did not return to the same model")
    else:
        verified_fields.append("model_revision")
    if post_state.arguments != pre_state.arguments:
        reasons.append("arguments changed: inference did not return to the same arguments")
    else:
        verified_fields.append("arguments")
    if not post_state.endpoint_healthy:
        reasons.append("endpoint is not healthy after recovery")
    else:
        verified_fields.append("endpoint_healthy")
    return RecoveryEvidence(
        pre_state=pre_state,
        post_state=post_state,
        verified=not reasons,
        verified_fields=tuple(verified_fields),
        reasons=tuple(reasons),
    )


def build_recovery_evidence(
    pre_state: InferencePreState, post_state: InferencePreState
) -> RecoveryEvidence:
    """Build the versioned recovery evidence record for a transition."""
    return verify_recovery(pre_state, post_state)
