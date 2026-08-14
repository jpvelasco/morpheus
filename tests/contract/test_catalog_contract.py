"""SEL-001 contracts: persistence, immutability, and trust behavior."""

from __future__ import annotations

from datetime import date

import pytest

from morpheus.adapters.catalog import CatalogRepository, load_or_seed
from morpheus.adapters.platform import platform_ports
from morpheus.core.catalog import (
    SEED_CATALOG,
    SEED_TRUST_POLICY,
    CatalogCollection,
    CatalogError,
    evaluate_trust,
    validate_references,
)
from morpheus.core.paths import OwnedPathError

TODAY = date(2026, 8, 13)


class TestPersistenceContract:
    def test_save_then_load_reproduces_exact_document(self, tmp_path: pytest.TestPath) -> None:
        repository = CatalogRepository(tmp_path)
        repository.save(SEED_CATALOG)
        loaded = repository.load()
        assert loaded == SEED_CATALOG
        assert loaded.to_dict() == SEED_CATALOG.to_dict()

    def test_installed_plan_never_mutates_on_reload(self, tmp_path: pytest.TestPath) -> None:
        repository = CatalogRepository(tmp_path)
        repository.save(SEED_CATALOG)
        for _ in range(3):
            loaded = repository.load()
            assert loaded == SEED_CATALOG
        assert repository.load().to_dict() == SEED_CATALOG.to_dict()

    def test_failed_replace_keeps_prior_document(self, tmp_path: pytest.TestPath) -> None:
        repository = CatalogRepository(tmp_path)
        repository.save(SEED_CATALOG)
        original = repository.load().to_dict()

        class BrokenReplacement:
            def replace(self, resolver, destination, staged) -> None:
                raise OwnedPathError("disposable failure")

        broken = CatalogRepository(tmp_path, replacement=BrokenReplacement())
        with pytest.raises(OwnedPathError):
            broken.save(SEED_CATALOG)
        assert repository.load().to_dict() == original
        assert not list(tmp_path.rglob("*.staged"))

    def test_empty_store_returns_none(self, tmp_path: pytest.TestPath) -> None:
        assert CatalogRepository(tmp_path).load() is None

    def test_load_or_seed_seeds_once(self, tmp_path: pytest.TestPath) -> None:
        repository = CatalogRepository(tmp_path)
        first = load_or_seed(repository, SEED_CATALOG)
        assert first == SEED_CATALOG
        seeded = load_or_seed(repository, SEED_CATALOG)
        assert seeded == SEED_CATALOG

    def test_repository_never_escapes_owned_root(self, tmp_path: pytest.TestPath) -> None:
        repository = CatalogRepository(tmp_path)
        with pytest.raises((OwnedPathError, CatalogError)):
            repository._resolver.resolve_relative("../escape")  # type: ignore[attr-defined]

    def test_staged_artifact_removed_after_failed_save(self, tmp_path: pytest.TestPath) -> None:
        class FailingReplacement:
            def replace(self, resolver, destination, staged) -> None:
                raise OSError("disk full")

        with pytest.raises(OwnedPathError):
            CatalogRepository(tmp_path, replacement=FailingReplacement()).save(SEED_CATALOG)
        assert not list(tmp_path.rglob("*.staged"))


class TestSeedContract:
    def test_seed_catalog_is_self_consistent(self) -> None:
        assert validate_references(SEED_CATALOG) == ()

    def test_seed_catalog_passes_seed_trust(self) -> None:
        models, engines, violations = evaluate_trust(SEED_CATALOG, SEED_TRUST_POLICY, TODAY)
        assert violations == ()
        assert {m.id for m in models} == {
            "llama-3.1-8b-instruct",
            "qwen2.5-7b-instruct",
            "mistral-7b-instruct",
        }
        assert {e.id for e in engines} == {"llama.cpp", "vllm"}

    def test_seed_catalog_parses_from_its_own_document(self) -> None:
        document = SEED_CATALOG.to_dict()
        assert CatalogCollection.from_dict(document) == SEED_CATALOG

    def test_every_model_has_an_engine(self) -> None:
        for model in SEED_CATALOG.models:
            assert model.engine_support, f"{model.id} must list an engine"
            assert all(
                engine in {e.id for e in SEED_CATALOG.engines} for engine in model.engine_support
            )

    def test_platform_ports_are_used_for_persistence(self, tmp_path: pytest.TestPath) -> None:
        ports = platform_ports("linux")
        repository = CatalogRepository(tmp_path, replacement=ports.durable_replacement)
        repository.save(SEED_CATALOG)
        assert repository.load() == SEED_CATALOG
