from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from morpheus.ops.candidate import CandidateValidationError, verify_candidate

ROOT = Path(__file__).resolve().parents[2]
DEFINITION = ROOT / "validation/candidate/artifact-set.json"
REQUIRED_ARTIFACTS = {
    "python-sdist",
    "python-wheel",
    "backend-oci",
    "dashboard-oci",
    "compose-config-bundle",
    "migration-bundle",
    "requirements-evidence",
    "checksums",
    "rollback-bundle",
}


def test_ART_001_definition_covers_the_complete_single_commit_candidate() -> None:
    definition = json.loads(DEFINITION.read_text())
    assert definition["format"] == 1
    assert definition["source_policy"] == {
        "commit": "one-full-git-object-id",
        "source_date_epoch": "commit-timestamp",
        "tree": "clean",
    }
    artifacts = {item["id"]: item for item in definition["artifacts"]}
    assert set(artifacts) == REQUIRED_ARTIFACTS
    for artifact in artifacts.values():
        assert artifact["required"] is True
        assert artifact["path_pattern"].startswith("payload/")
        assert artifact["media_type"]
        assert artifact["sources"]
        assert artifact["producer"]["command"]
        assert "latest" not in " ".join(artifact["producer"]["command"])

    assert all(artifact["producer"]["network"] is False for artifact in artifacts.values())

    assert set(definition["checksum_scope"]) == REQUIRED_ARTIFACTS - {"checksums"}
    assert set(definition["rollback_contents"]) >= {
        "python-wheel",
        "backend-oci",
        "dashboard-oci",
        "compose-config-bundle",
        "migration-bundle",
    }


def _write_candidate(tmp_path: Path) -> Path:
    definition = json.loads(DEFINITION.read_text())
    commit = "a" * 40
    artifacts = []
    checksums: dict[str, str] = {}
    for item in definition["artifacts"]:
        if item["id"] == "checksums":
            continue
        relative = item["path_pattern"].replace("{version}", "0.1.0")
        relative = relative.replace("{commit}", commit[:12])
        relative = relative.replace("*", "morpheus_control_plane-0.1.0-py3-none-any")
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"artifact={item['id']}\n".encode())
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        checksums[relative] = digest
        artifacts.append(
            {
                "id": item["id"],
                "path": relative,
                "media_type": item["media_type"],
                "sha256": digest,
                "size": path.stat().st_size,
                "source_commit": commit,
            }
        )

    checksum_definition = next(
        item for item in definition["artifacts"] if item["id"] == "checksums"
    )
    checksum_relative = checksum_definition["path_pattern"]
    checksum_path = tmp_path / checksum_relative
    checksum_path.parent.mkdir(parents=True, exist_ok=True)
    checksum_path.write_text(
        "".join(f"{digest}  {path}\n" for path, digest in sorted(checksums.items()))
    )
    artifacts.append(
        {
            "id": "checksums",
            "path": checksum_relative,
            "media_type": checksum_definition["media_type"],
            "sha256": hashlib.sha256(checksum_path.read_bytes()).hexdigest(),
            "size": checksum_path.stat().st_size,
            "source_commit": commit,
        }
    )
    manifest = {
        "format": 1,
        "candidate_version": "0.1.0",
        "source_commit": commit,
        "source_tree_clean": True,
        "source_date_epoch": 1_752_600_000,
        "created_at": "2026-07-15T21:00:00Z",
        "tool_lock_sha256": hashlib.sha256(
            (ROOT / "validation/tools/images.lock.json").read_bytes()
        ).hexdigest(),
        "artifacts": artifacts,
    }
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    return manifest_path


def test_candidate_verifier_accepts_complete_checksums_from_one_commit(tmp_path: Path) -> None:
    manifest = verify_candidate(_write_candidate(tmp_path), definition_path=DEFINITION)
    assert manifest["candidate_version"] == "0.1.0"
    assert {item["id"] for item in manifest["artifacts"]} == REQUIRED_ARTIFACTS


@pytest.mark.parametrize("mutation", ["mixed-commit", "bad-digest", "missing-artifact"])
def test_candidate_verifier_rejects_incoherent_candidate(tmp_path: Path, mutation: str) -> None:
    manifest_path = _write_candidate(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    if mutation == "mixed-commit":
        manifest["artifacts"][0]["source_commit"] = "b" * 40
    elif mutation == "bad-digest":
        manifest["artifacts"][0]["sha256"] = "0" * 64
    else:
        manifest["artifacts"].pop(0)
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(CandidateValidationError):
        verify_candidate(manifest_path, definition_path=DEFINITION)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("format", 2),
        ("candidate_version", "not-a-version"),
        ("source_commit", "short"),
        ("source_tree_clean", False),
        ("source_date_epoch", 0),
        ("created_at", "2026-07-15 21:00:00"),
        ("tool_lock_sha256", "not-a-digest"),
        ("artifacts", "not-a-list"),
    ],
)
def test_candidate_verifier_rejects_invalid_manifest_header(
    tmp_path: Path, field: str, value: object
) -> None:
    manifest_path = _write_candidate(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    manifest[field] = value
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(CandidateValidationError):
        verify_candidate(manifest_path, definition_path=DEFINITION)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("path", "../outside.tar.gz"),
        ("media_type", "application/x-wrong"),
        ("size", -1),
        ("sha256", "invalid"),
    ],
)
def test_candidate_verifier_rejects_invalid_artifact_metadata(
    tmp_path: Path, field: str, value: object
) -> None:
    manifest_path = _write_candidate(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"][0][field] = value
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(CandidateValidationError):
        verify_candidate(manifest_path, definition_path=DEFINITION)


def test_candidate_verifier_rejects_incomplete_checksum_file(tmp_path: Path) -> None:
    manifest_path = _write_candidate(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    checksum = next(item for item in manifest["artifacts"] if item["id"] == "checksums")
    checksum_path = tmp_path / checksum["path"]
    checksum_path.write_text("0" * 64 + "  payload/missing\n")
    checksum["size"] = checksum_path.stat().st_size
    checksum["sha256"] = hashlib.sha256(checksum_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(CandidateValidationError, match="SHA256SUMS"):
        verify_candidate(manifest_path, definition_path=DEFINITION)


def test_candidate_verifier_rejects_invalid_json_and_definition(tmp_path: Path) -> None:
    invalid_manifest = tmp_path / "candidate-manifest.json"
    invalid_manifest.write_text("{")
    with pytest.raises(CandidateValidationError, match="valid JSON"):
        verify_candidate(invalid_manifest, definition_path=DEFINITION)

    manifest_path = _write_candidate(tmp_path)
    invalid_definition = tmp_path / "definition.json"
    invalid_definition.write_text('{"format":2,"artifacts":[]}')
    with pytest.raises(CandidateValidationError, match="definition format"):
        verify_candidate(manifest_path, definition_path=invalid_definition)
