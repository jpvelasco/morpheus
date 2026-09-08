from __future__ import annotations

from morpheus.core.capabilities import (
    Capability,
    CapabilityState,
    CapabilityStatus,
    evaluate_capabilities,
    withhold_deferred_capability,
)
from morpheus.core.models import ServedModel


def test_RUN_001_model_identity_deduplicates_aliases_without_losing_order() -> None:
    model = ServedModel(
        root="nvidia/Qwen3.6-27B-NVFP4",
        aliases=("qwen36-27b-nvfp4", "coder36-q4km", "qwen36-27b-nvfp4"),
        context_window=131072,
    )
    assert model.aliases == ("qwen36-27b-nvfp4", "coder36-q4km")


def test_RUN_005_failed_optional_dependency_does_not_hide_core_capability() -> None:
    report = evaluate_capabilities(
        configured={Capability.CORE: True, Capability.SEARCH: True, Capability.VOICE: False},
        dependency_health={Capability.CORE: True, Capability.SEARCH: False},
        blockers={Capability.SEARCH: ("search_unreachable",)},
    )

    assert report[Capability.CORE].state is CapabilityState.AVAILABLE
    assert report[Capability.SEARCH].state is CapabilityState.UNHEALTHY
    assert report[Capability.VOICE].state is CapabilityState.DISABLED


def test_RUN_005_configured_capability_without_dependency_is_blocked() -> None:
    report = evaluate_capabilities(
        configured={Capability.RESEARCH: True},
        dependency_health={},
        blockers={Capability.RESEARCH: ("search_not_configured", "model_not_ready")},
    )
    assert report[Capability.RESEARCH].state is CapabilityState.BLOCKED
    assert report[Capability.RESEARCH].blockers == ("search_not_configured", "model_not_ready")


def test_R8_withhold_deferred_capability_blocks_available_optional_scope() -> None:
    available = CapabilityStatus(Capability.SEARCH, CapabilityState.AVAILABLE, ())
    withheld = withhold_deferred_capability(available)
    assert withheld.state is CapabilityState.BLOCKED
    assert withheld.blockers == ("deferred_optional_scope",)
    already_blocked = withhold_deferred_capability(
        CapabilityStatus(
            Capability.RAG, CapabilityState.BLOCKED, ("dependency_mapping_not_configured",)
        )
    )
    assert already_blocked.state is CapabilityState.BLOCKED
    assert already_blocked.blockers[0] == "deferred_optional_scope"
    assert (
        withhold_deferred_capability(
            CapabilityStatus(Capability.TELEMETRY, CapabilityState.AVAILABLE)
        ).state
        is CapabilityState.AVAILABLE
    )
