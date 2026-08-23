from __future__ import annotations

import pytest

from morpheus.core.gateway import AliasMap

MORPHEUS_OWNED_REQUIREMENTS = frozenset({"GATE-002"})


def test_GATE_002_alias_mapping_is_deterministic() -> None:
    aliases = AliasMap({"coding": "qwen36-27b-nvfp4", "default": "qwen36-27b-nvfp4"})
    assert aliases.resolve("coding") == "qwen36-27b-nvfp4"
    assert aliases.resolve("coding") == aliases.resolve("coding")


def test_GATE_002_unknown_alias_fails_closed() -> None:
    aliases = AliasMap({"coding": "qwen36-27b-nvfp4"})
    with pytest.raises(KeyError, match="unknown model alias"):
        aliases.resolve("surprise")


def test_GATE_002_alias_map_rejects_empty_or_duplicate_normalized_names() -> None:
    with pytest.raises(ValueError):
        AliasMap({"": "model"})
    with pytest.raises(ValueError):
        AliasMap({"Coding": "one", "coding": "two"})
