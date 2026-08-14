"""Unit tests for the SEL-001 versioned catalogs and trust evaluation."""

from __future__ import annotations

from datetime import date

import pytest

from morpheus.core.catalog import (
    DEFAULT_TRUST_POLICY,
    SEED_CATALOG,
    SEED_TRUST_POLICY,
    CatalogCollection,
    CatalogError,
    EngineCatalogEntry,
    ModelCatalogEntry,
    TrustPolicy,
    catalog_digest,
    evaluate_trust,
    validate_references,
)

TODAY = date(2026, 8, 13)


def _model(**overrides: object) -> ModelCatalogEntry:
    base: dict[str, object] = {
        "id": "model-a",
        "name": "Model A",
        "license": "apache-2.0",
        "architecture": "qwen2",
        "modalities": ("text",),
        "formats": ("safetensors",),
        "quantizations": ("awq",),
        "validation_freshness": date(2026, 7, 1),
        "source_url": "hf://huggingface.co/acme/model-a",
        "source_digest": "a" * 64,
    }
    base.update(overrides)
    return ModelCatalogEntry(**base)  # type: ignore[arg-type]


def _engine(**overrides: object) -> EngineCatalogEntry:
    base: dict[str, object] = {
        "id": "engine-a",
        "name": "Engine A",
        "license": "apache-2.0",
        "version": "1.0",
        "platforms": ("linux",),
        "released": date(2026, 7, 1),
        "source_url": "https://github.com/acme/engine-a",
        "source_digest": "b" * 64,
    }
    base.update(overrides)
    return EngineCatalogEntry(**base)  # type: ignore[arg-type]


def _collection(*models: ModelCatalogEntry, **engines: EngineCatalogEntry) -> CatalogCollection:
    return CatalogCollection(version="t", models=models, engines=tuple(engines.values()))


class TestSchemaValidation:
    def test_round_trip_is_identical(self) -> None:
        collection = _collection(_model(), engine=_engine())
        assert CatalogCollection.from_dict(collection.to_dict()) == collection

    def test_old_versions_reproduce_old_inputs(self) -> None:
        document = _collection(_model()).to_dict()
        parsed = CatalogCollection.from_dict(document)
        assert parsed.to_dict() == document

    @pytest.mark.parametrize(
        "field,value",
        [
            ("id", "Upper-Case"),
            ("source_url", "http://insecure.example/model"),
            ("source_url", "ftp://insecure.example/model"),
            ("source_url", "hf://user:pass@huggingface.co/model"),
            ("source_digest", "xyz"),
            ("source_digest", "abc"),
            ("validation_freshness", "not-a-date"),
            ("artifact_size_bytes", -1),
        ],
    )
    def test_model_rejects_invalid_fields(self, field: str, value: object) -> None:
        payload = _model().to_dict()
        payload[field] = value
        with pytest.raises(CatalogError):
            ModelCatalogEntry.from_dict(payload)

    def test_unknown_model_field_rejected(self) -> None:
        payload = _model().to_dict()
        payload["surprise"] = True
        with pytest.raises(CatalogError):
            ModelCatalogEntry.from_dict(payload)

    def test_unknown_catalog_field_rejected(self) -> None:
        payload = _collection(_model()).to_dict()
        payload["surprise"] = True
        with pytest.raises(CatalogError):
            CatalogCollection.from_dict(payload)

    def test_unknown_engine_field_rejected(self) -> None:
        payload = _engine().to_dict()
        payload["surprise"] = True
        with pytest.raises(CatalogError):
            EngineCatalogEntry.from_dict(payload)

    def test_malformed_quantization_list_rejected(self) -> None:
        payload = _model().to_dict()
        payload["quantizations"] = "q4_k_m"
        with pytest.raises(CatalogError):
            ModelCatalogEntry.from_dict(payload)


class TestReferenceValidation:
    def test_dangling_engine_reference_reported(self) -> None:
        collection = _collection(_model(engine_support=("missing-engine",)))
        assert validate_references(collection) == (
            "model model-a requires unknown engine missing-engine",
        )

    def test_satisfied_references_are_quiet(self) -> None:
        collection = _collection(_model(engine_support=("engine-a",)), engine=_engine())
        assert validate_references(collection) == ()


class TestTrustEvaluation:
    def test_all_seed_entries_pass_seed_policy(self) -> None:
        models, engines, violations = evaluate_trust(SEED_CATALOG, SEED_TRUST_POLICY, TODAY)
        assert violations == ()
        assert len(models) == 3 and len(engines) == 2

    def test_default_policy_flags_unsigned_seeds(self) -> None:
        _, _, violations = evaluate_trust(SEED_CATALOG, DEFAULT_TRUST_POLICY, TODAY)
        reasons = {violation.reason for violation in violations}
        assert "missing sha256 digest" in reasons
        assert len(violations) == 5

    def test_source_not_permitted(self) -> None:
        entry = _model(source_url="https://evil.example/model")
        _, _, violations = evaluate_trust(_collection(entry), SEED_TRUST_POLICY, TODAY)
        assert violations[0].reason == "source is not permitted by trust policy"

    def test_license_not_permitted(self) -> None:
        entry = _model(license="proprietary")
        _, _, violations = evaluate_trust(_collection(entry), SEED_TRUST_POLICY, TODAY)
        assert violations[0].reason == "license is not permitted by trust policy"

    def test_stale_freshness_reported(self) -> None:
        entry = _model(validation_freshness=date(2025, 1, 1))
        _, _, violations = evaluate_trust(_collection(entry), SEED_TRUST_POLICY, TODAY)
        assert violations[0].reason == "validation evidence is stale"

    def test_never_validated_reported(self) -> None:
        entry = _model(validation_freshness=None)
        _, _, violations = evaluate_trust(_collection(entry), SEED_TRUST_POLICY, TODAY)
        assert violations[0].reason == "never validated"

    def test_policy_without_restrictions_trusts_everything(self) -> None:
        entry = _model(license="whatever")
        collection = _collection(entry)
        models, engines, violations = evaluate_trust(
            collection,
            TrustPolicy(require_digest=False, max_freshness_days=None),
            TODAY,
        )
        assert models == collection.models and violations == ()

    def test_engine_freshness_uses_release_date(self) -> None:
        engine = _engine(released=date(2024, 1, 1))
        _, _, violations = evaluate_trust(_collection(engine=engine), SEED_TRUST_POLICY, TODAY)
        assert violations[0].reason == "validation evidence is stale"

    def test_unsigned_engine_rejected_by_digest_policy(self) -> None:
        engine = _engine(source_digest=None)
        _, _, violations = evaluate_trust(_collection(engine=engine), DEFAULT_TRUST_POLICY, TODAY)
        assert any(v.reason == "missing sha256 digest" for v in violations)


class TestDigestStability:
    def test_digest_is_canonical_and_stable(self) -> None:
        collection = _collection(_model())
        assert catalog_digest(collection) == catalog_digest(
            CatalogCollection.from_dict(collection.to_dict())
        )
        assert catalog_digest(collection) != catalog_digest(_collection(_model(name="Other")))

    def test_digest_changes_with_entry_content(self) -> None:
        before = catalog_digest(SEED_CATALOG)
        changed = CatalogCollection(
            version=SEED_CATALOG.version,
            models=(_model(),),
            engines=SEED_CATALOG.engines,
        )
        assert catalog_digest(changed) != before
