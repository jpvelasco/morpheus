from __future__ import annotations

from morpheus.core.capabilities import Capability, CapabilityState, evaluate_capabilities
from morpheus.core.models import ModelIdentity


def test_RUN_001_model_identity_deduplicates_aliases_without_losing_order() -> None:
    model = ModelIdentity(
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
