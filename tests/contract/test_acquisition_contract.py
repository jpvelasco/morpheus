"""Contract tests: verified installation plan (RUNM-003).

Guarantees:
- Acquisition never touches a path outside the owned cache root, and no
  symlink is ever followed into or out of it.
- A plan that violates trust (source/license) or declared disk impact
  (free space, quota) is rejected before any byte is staged.
- Staging is resumable: interruption at any boundary restarts from the
  journaled byte offset and never duplicates or loses verified bytes.
- An artifact is usable only after size and sha256 verification; corruption
  or truncation moves the durable record to failed and removes the partial.
- The cache enforces its quota by evicting least-recently-verified artifacts
  and never deletes provenance records.
- Every lifecycle edge is a durable acquisition-machine transition.
"""

import hashlib

import pytest

from morpheus.core.acquisition import (
    AcquisitionCache,
    AcquisitionError,
    AcquisitionPlan,
    AcquisitionPolicy,
    CacheQuota,
    cache_record_digest,
)
from morpheus.core.paths import OwnedPathError

pytestmark = pytest.mark.contract

POLICY = AcquisitionPolicy(
    permitted_sources=("hf://huggingface.co/",),
    required_licenses=("apache-2.0", "mit", "llama-3.1"),
)
QUOTA = CacheQuota(max_bytes=10 * 1024**3)


def body(size: int) -> bytes:
    seed = hashlib.sha256(b"morpheus-contract").digest()
    return (seed * (size // len(seed) + 1))[:size]


def plan_for(size: int = 2048, **overrides) -> AcquisitionPlan:
    content = body(size)
    fields = {
        "entry_id": "llama-3.1-8b-instruct",
        "kind": "model",
        "revision": "main",
        "source_url": "hf://huggingface.co/meta-llama/Llama-3.1-8B-Instruct-GGUF",
        "expected_sha256": hashlib.sha256(content).hexdigest(),
        "declared_size_bytes": size,
        "license": "llama-3.1",
    }
    fields.update(overrides)
    return AcquisitionPlan(**fields)


def feed(cache: AcquisitionCache, plan: AcquisitionPlan, stop_after: int | None = None) -> int:
    content = body(plan.declared_size_bytes)
    offset = cache.begin(plan, policy=POLICY, free_bytes=2**30, quota=QUOTA)
    while offset < plan.declared_size_bytes:
        if stop_after is not None and offset >= stop_after:
            break
        chunk = content[offset : offset + 256]
        offset = cache.append_chunk(plan, chunk)
    return offset


def test_owned_paths_bound_every_artifact_and_record(tmp_path) -> None:
    cache = AcquisitionCache(tmp_path)
    plan = plan_for()
    feed(cache, plan)
    record = cache.verify(plan)
    artifact = cache.artifact_path(plan.expected_sha256, "model")
    assert tmp_path in artifact.parents
    assert artifact.is_file()
    escaped = tmp_path.parent / "outside.bin"
    escaped.write_bytes(b"x")
    (tmp_path / "cache" / "model" / plan.expected_sha256).unlink()
    (tmp_path / "cache" / "model" / plan.expected_sha256).symlink_to(escaped)
    with pytest.raises(OwnedPathError):
        cache.artifact_path(plan.expected_sha256, "model")
    record_file = tmp_path / "records" / f"{record.record_id}.json"
    record_file.unlink()
    record_file.symlink_to(escaped)
    with pytest.raises(OwnedPathError):
        cache.records()


def test_interruption_at_every_boundary_resumes_or_restarts(tmp_path) -> None:
    for index, stop in enumerate((0, 1, 256, 511, 1024, 1792)):
        cache = AcquisitionCache(tmp_path / f"case-{index}")
        plan = plan_for()
        fed = feed(cache, plan, stop_after=stop)
        before = cache.records()[0].state
        assert before == "acquiring"
        resumed = cache.begin(plan, policy=POLICY, free_bytes=2**30, quota=QUOTA)
        assert resumed == fed
        feed(cache, plan)
        record = cache.verify(plan)
        assert record.state == "verified"
        assert record.actual_size_bytes == plan.declared_size_bytes


def test_interruption_before_any_state_durable_edge_replays(tmp_path) -> None:
    cache = AcquisitionCache(tmp_path)
    plan = plan_for()
    first = cache.begin(plan, policy=POLICY, free_bytes=2**30, quota=QUOTA)
    assert first == 0
    second = cache.begin(plan, policy=POLICY, free_bytes=2**30, quota=QUOTA)
    assert second == 0
    feed(cache, plan)
    record = cache.verify(plan)
    assert record.machine.checkpoint == 2


def test_corruption_at_any_prefix_fails_and_cleans_partial(tmp_path) -> None:
    for index, flip in enumerate((0, 64, 1023)):
        cache = AcquisitionCache(tmp_path / f"case-{index}")
        plan = plan_for()
        feed(cache, plan)
        artifact = cache.root / "partial" / f"{cache_record_digest(plan)}.part"
        raw = bytearray(artifact.read_bytes())
        raw[flip] ^= 0xFF
        artifact.write_bytes(raw)
        with pytest.raises(AcquisitionError, match="sha256"):
            cache.verify(plan)
        record = cache.records()[0]
        assert record.state == "failed"
        assert not artifact.exists()
        assert cache.disk_usage() == 0


def test_low_disk_and_quota_reject_before_staging(tmp_path) -> None:
    cache = AcquisitionCache(tmp_path)
    plan = plan_for(size=4096)
    with pytest.raises(AcquisitionError, match="free space"):
        cache.begin(plan, policy=POLICY, free_bytes=2048, quota=QUOTA)
    with pytest.raises(AcquisitionError, match="quota"):
        cache.begin(plan, policy=POLICY, free_bytes=2**30, quota=CacheQuota(max_bytes=2048))
    assert cache.records() == ()


def test_license_and_source_policy_reject_before_staging(tmp_path) -> None:
    cache = AcquisitionCache(tmp_path)
    with pytest.raises(AcquisitionError, match="license"):
        cache.begin(
            plan_for(license="proprietary"),
            policy=POLICY,
            free_bytes=2**30,
            quota=QUOTA,
        )
    with pytest.raises(AcquisitionError, match="source"):
        cache.begin(
            plan_for(source_url="http://insecure.example/model"),
            policy=POLICY,
            free_bytes=2**30,
            quota=QUOTA,
        )
    assert cache.records() == ()


def test_quota_eviction_preserves_records_and_bounds_disk(tmp_path) -> None:
    cache = AcquisitionCache(tmp_path)
    small = plan_for(size=512)
    large = plan_for(size=1024)
    feed(cache, small)
    cache.verify(small)
    feed(cache, large)
    cache.verify(large)
    evicted = cache.enforce_quota(CacheQuota(max_bytes=1024))
    assert evicted == (small.expected_sha256,)
    assert cache.disk_usage() <= 1024
    assert len(cache.records()) == 2
    assert cache.lookup(small.expected_sha256) is None


def test_every_edge_is_a_durable_machine_transition(tmp_path) -> None:
    cache = AcquisitionCache(tmp_path)
    plan = plan_for()
    feed(cache, plan)
    staged_record = cache.verify(plan)
    assert staged_record.machine.machine.value == "acquisition"
    assert staged_record.machine.state == "verified"
    assert staged_record.machine.checkpoint == 2
    clone = type(staged_record).from_dict(staged_record.to_dict())
    assert clone.machine == staged_record.machine


def test_replay_is_byte_identical(tmp_path) -> None:
    plan = plan_for()
    first = AcquisitionCache(tmp_path / "first")
    feed(first, plan)
    first.verify(plan)
    second = AcquisitionCache(tmp_path / "second")
    feed(second, plan)
    second.verify(plan)
    assert first.records()[0].to_dict()["plan"] == second.records()[0].to_dict()["plan"]
    assert cache_record_digest(plan) == cache_record_digest(plan_for(size=2048))
