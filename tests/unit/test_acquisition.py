"""Unit tests: verified resumable acquisition cache (RUNM-003)."""

import hashlib
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from morpheus.core.acquisition import (
    AcquisitionCache,
    AcquisitionError,
    AcquisitionPlan,
    AcquisitionPolicy,
    CacheQuota,
    acquisition_violations,
    cache_record_digest,
    disk_reservation_violations,
    verify_digest,
)
from morpheus.core.paths import OwnedPathError

PLAN = AcquisitionPlan(
    entry_id="llama-3.1-8b-instruct",
    kind="model",
    revision="main",
    source_url="hf://huggingface.co/meta-llama/Llama-3.1-8B-Instruct-GGUF",
    expected_sha256="b" * 64,
    declared_size_bytes=1024,
    license="llama-3.1",
)

POLICY = AcquisitionPolicy(
    permitted_sources=("hf://huggingface.co/",),
    required_licenses=("llama-3.1", "apache-2.0", "mit"),
)

QUOTA = CacheQuota(max_bytes=2048)


def artifact(digest: str | None = None, size: int = 1024) -> bytes:
    content = hashlib.sha256((digest or "b" * 64).encode()).digest()
    body = content * (size // len(content) + 1)
    return body[:size]


def matching_plan(size: int = 1024) -> AcquisitionPlan:
    body = artifact(size=size)
    return AcquisitionPlan(
        entry_id=PLAN.entry_id,
        kind=PLAN.kind,
        revision=PLAN.revision,
        source_url=PLAN.source_url,
        expected_sha256=hashlib.sha256(body).hexdigest(),
        declared_size_bytes=size,
        license=PLAN.license,
    )


def acquire(cache: AcquisitionCache, plan: AcquisitionPlan, chunks: tuple[int, ...] = (512, 512)):
    assert cache.begin(plan, policy=POLICY, free_bytes=2**30, quota=QUOTA) == 0
    offset = 0
    body = artifact(size=plan.declared_size_bytes)
    for chunk in chunks:
        cache.append_chunk(plan, body[offset : offset + chunk])
        offset += chunk
    return cache.verify(plan)


def test_plan_validation() -> None:
    with pytest.raises(AcquisitionError, match="kind"):
        replace(PLAN, kind="binary")
    with pytest.raises(AcquisitionError, match="sha256"):
        replace(PLAN, expected_sha256="short")
    with pytest.raises(AcquisitionError, match="positive"):
        replace(PLAN, declared_size_bytes=0)


def test_trust_and_disk_violations_are_explainable() -> None:
    assert acquisition_violations(PLAN, POLICY) == ()
    assert acquisition_violations(PLAN, AcquisitionPolicy()) == ()
    bad_source = replace(PLAN, source_url="http://insecure.example/model")
    assert "source" in acquisition_violations(bad_source, POLICY)[0]
    bad_license = replace(PLAN, license="proprietary")
    assert "license" in acquisition_violations(bad_license, POLICY)[0]

    assert disk_reservation_violations(PLAN, free_bytes=4096, quota=QUOTA) == ()
    reasons = disk_reservation_violations(PLAN, free_bytes=512, quota=QUOTA)
    assert any("free space" in reason for reason in reasons)
    reasons = disk_reservation_violations(PLAN, free_bytes=4096, quota=CacheQuota(max_bytes=512))
    assert any("quota" in reason for reason in reasons)


def test_begin_rejects_policy_or_disk_violations(tmp_path) -> None:
    cache = AcquisitionCache(tmp_path)
    with pytest.raises(AcquisitionError, match="source"):
        cache.begin(
            replace(PLAN, source_url="http://insecure.example/m"),
            policy=POLICY,
            free_bytes=2**30,
            quota=QUOTA,
        )
    with pytest.raises(AcquisitionError, match="free space"):
        cache.begin(PLAN, policy=POLICY, free_bytes=512, quota=QUOTA)


def test_happy_path_verifies_and_content_addresses(tmp_path) -> None:
    cache = AcquisitionCache(tmp_path)
    plan = matching_plan()
    record = acquire(cache, plan)
    assert record.state == "verified"
    assert record.actual_size_bytes == plan.declared_size_bytes
    assert record.verified_at is not None
    assert record.machine.checkpoint == 2
    path = cache.artifact_path(plan.expected_sha256, "model")
    assert path.exists()
    assert cache.verify_existing(plan.expected_sha256, "model")
    assert cache.disk_usage() == plan.declared_size_bytes


def test_record_id_is_content_digest_over_identity(tmp_path) -> None:
    cache = AcquisitionCache(tmp_path)
    assert cache_record_digest(PLAN) == cache_record_digest(PLAN)
    changed = replace(PLAN, revision="v2")
    assert cache_record_digest(changed) != cache_record_digest(PLAN)
    acquire(cache, matching_plan())
    stored = cache.records()[0]
    assert stored.record_id == cache_record_digest(stored.plan)


def test_resume_continues_from_partial_bytes(tmp_path) -> None:
    cache = AcquisitionCache(tmp_path)
    plan = matching_plan()
    body = artifact(size=plan.declared_size_bytes)
    assert cache.begin(plan, policy=POLICY, free_bytes=2**30, quota=QUOTA) == 0
    assert cache.append_chunk(plan, body[:400]) == 400
    resumed = cache.begin(plan, policy=POLICY, free_bytes=2**30, quota=QUOTA)
    assert resumed == 400
    assert cache.append_chunk(plan, body[400:]) == plan.declared_size_bytes
    record = cache.verify(plan)
    assert record.state == "verified"
    assert record.actual_size_bytes == plan.declared_size_bytes


def test_restart_after_interruption_before_first_byte(tmp_path) -> None:
    cache = AcquisitionCache(tmp_path)
    plan = matching_plan()
    assert cache.begin(plan, policy=POLICY, free_bytes=2**30, quota=QUOTA) == 0
    assert cache.begin(plan, policy=POLICY, free_bytes=2**30, quota=QUOTA) == 0
    assert cache.records()[0].state == "acquiring"


def test_corruption_is_detected_and_failed(tmp_path) -> None:
    cache = AcquisitionCache(tmp_path)
    plan = matching_plan()
    body = artifact(size=plan.declared_size_bytes)
    cache.begin(plan, policy=POLICY, free_bytes=2**30, quota=QUOTA)
    corrupted = bytearray(body)
    corrupted[0] ^= 0xFF
    cache.append_chunk(plan, bytes(corrupted))
    with pytest.raises(AcquisitionError, match="sha256"):
        cache.verify(plan)
    record = cache.records()[0]
    assert record.state == "failed"
    assert not (tmp_path / "partial").joinpath(f"{record.record_id}.part").exists()
    with pytest.raises(AcquisitionError, match="failed verification"):
        cache.begin(plan, policy=POLICY, free_bytes=2**30, quota=QUOTA)


def test_declared_size_mismatch_is_failed(tmp_path) -> None:
    cache = AcquisitionCache(tmp_path)
    plan = matching_plan(size=512)
    truncated = replace(plan, declared_size_bytes=1024)
    body = artifact(size=plan.declared_size_bytes)
    cache.begin(truncated, policy=POLICY, free_bytes=2**30, quota=QUOTA)
    cache.append_chunk(truncated, body)
    with pytest.raises(AcquisitionError, match="declared size"):
        cache.verify(truncated)
    assert cache.records()[0].state == "failed"


def test_append_cannot_exceed_declared_size(tmp_path) -> None:
    cache = AcquisitionCache(tmp_path)
    plan = matching_plan()
    cache.begin(plan, policy=POLICY, free_bytes=2**30, quota=QUOTA)
    with pytest.raises(AcquisitionError, match="exceed"):
        cache.append_chunk(plan, b"x" * (plan.declared_size_bytes + 1))


def test_duplicate_acquisition_is_rejected(tmp_path) -> None:
    cache = AcquisitionCache(tmp_path)
    plan = matching_plan()
    acquire(cache, plan)
    with pytest.raises(AcquisitionError, match="already verified"):
        cache.begin(plan, policy=POLICY, free_bytes=2**30, quota=QUOTA)


def test_collision_on_existing_artifact_is_verified_not_rewritten(tmp_path) -> None:
    cache = AcquisitionCache(tmp_path)
    plan = matching_plan()
    acquire(cache, plan)
    second = AcquisitionPlan(
        entry_id="mistral-7b-instruct",
        kind="model",
        revision="main",
        source_url=plan.source_url,
        expected_sha256=plan.expected_sha256,
        declared_size_bytes=plan.declared_size_bytes,
        license="apache-2.0",
    )
    cache.begin(second, policy=POLICY, free_bytes=2**30, quota=QUOTA)
    cache.append_chunk(second, artifact(size=plan.declared_size_bytes))
    record = cache.verify(second)
    assert record.state == "verified"
    assert len(cache.records()) == 2
    assert cache.disk_usage() == plan.declared_size_bytes


def test_quota_evicts_least_recently_verified(tmp_path) -> None:
    cache = AcquisitionCache(tmp_path)
    small = matching_plan(size=512)
    large = matching_plan(size=1024)
    acquire(cache, small)
    acquire(cache, large)
    evicted = cache.enforce_quota(CacheQuota(max_bytes=1024))
    assert evicted == (small.expected_sha256,)
    assert cache.disk_usage() == large.declared_size_bytes
    with pytest.raises(AcquisitionError, match="not cached"):
        cache.artifact_path(small.expected_sha256, "model")
    record = next(r for r in cache.records() if r.evicted_at is not None)
    assert record.evicted_at is not None


def test_evict_requires_verified_and_removes_artifact(tmp_path) -> None:
    cache = AcquisitionCache(tmp_path)
    plan = matching_plan()
    with pytest.raises(AcquisitionError, match="document missing"):
        cache.evict(plan)
    acquire(cache, plan)
    cache.evict(plan)
    assert not (tmp_path / "cache" / "model" / plan.expected_sha256).exists()
    with pytest.raises(AcquisitionError, match="not cached"):
        cache.artifact_path(plan.expected_sha256, "model")


def test_lookup_and_artifact_path_validate_digests(tmp_path) -> None:
    cache = AcquisitionCache(tmp_path)
    with pytest.raises(AcquisitionError, match="sha256"):
        cache.lookup("nope")
    with pytest.raises(AcquisitionError, match="sha256"):
        cache.artifact_path("nope", "model")
    assert cache.lookup("b" * 64) is None
    with pytest.raises(AcquisitionError, match="not cached"):
        cache.artifact_path("b" * 64, "model")


def test_owned_paths_reject_symlinks(tmp_path) -> None:
    cache = AcquisitionCache(tmp_path)
    plan = matching_plan()
    acquire(cache, plan)
    record = cache.records()[0]
    record_file = tmp_path / "records" / f"{record.record_id}.json"
    record_file.unlink()
    (tmp_path / "records" / f"{record.record_id}.json").symlink_to(tmp_path / "manifest.json")
    with pytest.raises(OwnedPathError, match="symbolic"):
        cache.records()
    (tmp_path / "records" / f"{record.record_id}.json").unlink()
    (tmp_path / "cache" / "model" / plan.expected_sha256).unlink()
    (tmp_path / "cache" / "model" / plan.expected_sha256).symlink_to(tmp_path / "manifest.json")
    with pytest.raises(OwnedPathError, match="symbolic"):
        cache.artifact_path(plan.expected_sha256, "model")


def test_round_trip_preserves_provenance(tmp_path) -> None:
    cache = AcquisitionCache(tmp_path)
    plan = matching_plan()
    acquire(cache, plan)
    clone = cache.records()[0]
    payload = clone.to_dict()
    rebuilt = type(clone).from_dict(payload)
    assert rebuilt == clone


def test_verify_without_acquiring_record_is_rejected(tmp_path) -> None:
    cache = AcquisitionCache(tmp_path)
    plan = matching_plan()
    with pytest.raises(AcquisitionError, match="document missing"):
        cache.verify(plan)
    with pytest.raises(AcquisitionError, match="document missing"):
        cache.append_chunk(plan, b"x" * 8)


def test_timestamps_are_timezone_aware() -> None:
    plan = matching_plan()
    record_id = cache_record_digest(plan)
    payload = {
        "record_id": record_id,
        "plan": {
            "entry_id": plan.entry_id,
            "kind": plan.kind,
            "revision": plan.revision,
            "source_url": plan.source_url,
            "expected_sha256": plan.expected_sha256,
            "declared_size_bytes": plan.declared_size_bytes,
            "license": plan.license,
        },
        "machine": {
            "machine": "acquisition",
            "record_id": record_id,
            "state": "verified",
            "schema_version": 1,
            "checkpoint": 2,
        },
        "actual_size_bytes": 1024,
        "acquired_at": "2026-08-01T12:00:00+00:00",
        "verified_at": "2026-08-01T12:00:00+00:00",
        "evicted_at": None,
    }
    from morpheus.core.acquisition import CacheRecord

    record = CacheRecord.from_dict(payload)
    assert record.verified_at == datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def test_verify_digest_streams_large_content(tmp_path) -> None:
    path = tmp_path / "blob.bin"
    body = b"x" * (3 * 1024 * 1024 + 17)
    path.write_bytes(body)
    assert verify_digest(path, hashlib.sha256(body).hexdigest())
    assert not verify_digest(path, hashlib.sha256(body + b"x").hexdigest())
