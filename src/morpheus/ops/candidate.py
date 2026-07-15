from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

_COMMIT = re.compile(r"^[0-9a-f]{40,64}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_UTC = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
_ARTIFACT_FIELDS = {"id", "path", "media_type", "sha256", "size", "source_commit"}


class CandidateValidationError(ValueError):
    """A release candidate is incomplete, incoherent, or corrupt."""


def verify_candidate(manifest_path: Path, *, definition_path: Path) -> dict[str, Any]:
    manifest = _read_object(manifest_path, label="candidate manifest")
    definition = _read_object(definition_path, label="artifact definition")
    _validate_header(manifest)

    definitions = _definitions(definition)
    artifacts_value = manifest.get("artifacts")
    if not isinstance(artifacts_value, list) or not all(
        isinstance(item, dict) for item in artifacts_value
    ):
        raise CandidateValidationError("candidate artifacts must be a list of objects")
    artifacts: list[dict[str, Any]] = artifacts_value
    identifiers = [item.get("id") for item in artifacts]
    if len(identifiers) != len(set(identifiers)) or set(identifiers) != set(definitions):
        raise CandidateValidationError(
            "candidate artifact set is missing, duplicated, or unexpected"
        )

    root = manifest_path.resolve().parent
    commit = manifest["source_commit"]
    version = manifest["candidate_version"]
    verified: dict[str, tuple[str, str]] = {}
    for artifact in artifacts:
        identifier = artifact.get("id")
        if not isinstance(identifier, str):
            raise CandidateValidationError("candidate artifact ID must be a string")
        definition_item = definitions[identifier]
        _validate_artifact_fields(artifact, commit=commit)
        relative = _safe_relative(artifact["path"])
        expected_pattern = definition_item["path_pattern"].replace("{version}", version)
        expected_pattern = expected_pattern.replace("{commit}", commit[:12])
        if not fnmatch.fnmatchcase(relative.as_posix(), expected_pattern):
            raise CandidateValidationError(f"unexpected path for artifact {identifier}")
        if artifact["media_type"] != definition_item["media_type"]:
            raise CandidateValidationError(f"unexpected media type for artifact {identifier}")
        path = root / relative
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
            raise CandidateValidationError(f"artifact is missing or unsafe: {identifier}")
        size, digest = _file_identity(path)
        if size != artifact["size"] or digest != artifact["sha256"]:
            raise CandidateValidationError(f"artifact identity mismatch: {identifier}")
        verified[identifier] = (relative.as_posix(), digest)

    checksum_scope = definition.get("checksum_scope")
    if not isinstance(checksum_scope, list) or set(checksum_scope) != set(definitions) - {
        "checksums"
    }:
        raise CandidateValidationError("artifact definition checksum scope is invalid")
    checksum_path = root / verified["checksums"][0]
    checksum_entries = sorted((verified[name][0], verified[name][1]) for name in checksum_scope)
    expected_checksums = "".join(f"{digest}  {path}\n" for path, digest in checksum_entries)
    if checksum_path.read_text() != expected_checksums:
        raise CandidateValidationError("SHA256SUMS does not cover the declared candidate payload")
    return manifest


def _read_object(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise CandidateValidationError(f"{label} must be a regular file")
    try:
        value = json.loads(path.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CandidateValidationError(f"{label} is not valid JSON") from error
    if not isinstance(value, dict):
        raise CandidateValidationError(f"{label} must be a JSON object")
    return value


def _validate_header(manifest: dict[str, Any]) -> None:
    if manifest.get("format") != 1:
        raise CandidateValidationError("unsupported candidate manifest format")
    if not isinstance(manifest.get("candidate_version"), str) or not _VERSION.fullmatch(
        manifest["candidate_version"]
    ):
        raise CandidateValidationError("candidate version must be semantic version text")
    if not isinstance(manifest.get("source_commit"), str) or not _COMMIT.fullmatch(
        manifest["source_commit"]
    ):
        raise CandidateValidationError("candidate source commit must be a full Git object ID")
    if manifest.get("source_tree_clean") is not True:
        raise CandidateValidationError("candidate source tree must be clean")
    if not isinstance(manifest.get("source_date_epoch"), int) or manifest["source_date_epoch"] < 1:
        raise CandidateValidationError("candidate source date epoch is invalid")
    if not isinstance(manifest.get("created_at"), str) or not _UTC.fullmatch(
        manifest["created_at"]
    ):
        raise CandidateValidationError("candidate creation time must be UTC")
    if not isinstance(manifest.get("tool_lock_sha256"), str) or not _DIGEST.fullmatch(
        manifest["tool_lock_sha256"]
    ):
        raise CandidateValidationError("candidate tool-lock digest is invalid")


def _definitions(definition: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if definition.get("format") != 1 or not isinstance(definition.get("artifacts"), list):
        raise CandidateValidationError("artifact definition format is invalid")
    result: dict[str, dict[str, Any]] = {}
    for item in definition["artifacts"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise CandidateValidationError("artifact definition entry is invalid")
        if item["id"] in result:
            raise CandidateValidationError("artifact definition IDs must be unique")
        if item.get("required") is not True:
            raise CandidateValidationError("every candidate artifact must be required")
        if not isinstance(item.get("path_pattern"), str) or not isinstance(
            item.get("media_type"), str
        ):
            raise CandidateValidationError("artifact definition path or media type is invalid")
        result[item["id"]] = item
    return result


def _validate_artifact_fields(artifact: dict[str, Any], *, commit: str) -> None:
    if set(artifact) != _ARTIFACT_FIELDS:
        raise CandidateValidationError("candidate artifact fields are invalid")
    if artifact["source_commit"] != commit:
        raise CandidateValidationError("candidate artifacts do not share one source commit")
    if not isinstance(artifact["sha256"], str) or not _DIGEST.fullmatch(artifact["sha256"]):
        raise CandidateValidationError("candidate artifact digest is invalid")
    if not isinstance(artifact["size"], int) or artifact["size"] < 0:
        raise CandidateValidationError("candidate artifact size is invalid")
    if not isinstance(artifact["path"], str) or not isinstance(artifact["media_type"], str):
        raise CandidateValidationError("candidate artifact path or media type is invalid")


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if "\\" in value or path.is_absolute() or not path.parts or ".." in path.parts:
        raise CandidateValidationError("candidate artifact path is unsafe")
    return path


def _file_identity(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()
