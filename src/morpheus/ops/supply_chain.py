from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from morpheus.ops.candidate import verify_candidate

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
_REQUIRED_TOOLS = {"secret-scan", "vulnerability-scan", "sbom", "license-scan"}
_REPORT_FIELDS = {"path", "sha256", "size"}
_MANIFEST_FIELDS = {
    "format",
    "source_commit",
    "candidate_manifest_sha256",
    "tool_lock_sha256",
    "policy_sha256",
    "vulnerability_database",
    "tools",
    "scans",
    "sboms",
    "license_review",
    "result",
}


class SupplyChainValidationError(ValueError):
    """Supply-chain evidence is incomplete, stale, corrupt, or unsafe."""


def verify_supply_chain(
    manifest_path: Path,
    *,
    candidate_manifest_path: Path,
    candidate_definition_path: Path,
    tool_lock_path: Path,
    policy_path: Path,
) -> dict[str, Any]:
    try:
        candidate = verify_candidate(
            candidate_manifest_path, definition_path=candidate_definition_path
        )
    except ValueError as error:
        raise SupplyChainValidationError("candidate verification failed") from error
    manifest = _read_object(manifest_path, label="supply-chain manifest")
    tool_lock = _read_object(tool_lock_path, label="tool lock")
    policy = _read_object(policy_path, label="supply-chain policy")
    _validate_policy(policy)
    _validate_header(
        manifest,
        candidate=candidate,
        candidate_manifest_path=candidate_manifest_path,
        tool_lock_path=tool_lock_path,
        policy_path=policy_path,
    )
    _validate_tools(manifest.get("tools"), tool_lock=tool_lock)
    _validate_database(manifest.get("vulnerability_database"))

    root = manifest_path.resolve().parent
    used_paths: set[str] = set()
    scans = _validate_scans(manifest.get("scans"), policy=policy, root=root, used_paths=used_paths)
    artifact_ids = {str(item["id"]) for item in candidate["artifacts"]}
    _validate_sboms(
        manifest.get("sboms"),
        artifact_ids=artifact_ids,
        formats=set(policy["sbom_formats"]),
        root=root,
        used_paths=used_paths,
    )
    _validate_license_review(
        manifest.get("license_review"),
        source_commit=candidate["source_commit"],
        scans=scans,
        root=root,
        used_paths=used_paths,
    )
    if manifest.get("result") != "pass":
        raise SupplyChainValidationError("supply-chain result must be pass")
    return manifest


def _read_object(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise SupplyChainValidationError(f"{label} must be a regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SupplyChainValidationError(f"{label} must be valid JSON") from error
    if not isinstance(value, dict):
        raise SupplyChainValidationError(f"{label} must be a JSON object")
    return value


def _file_identity(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _validate_policy(policy: dict[str, Any]) -> None:
    expected = {
        "format",
        "blocked_severities",
        "required_scans",
        "sbom_formats",
        "forbidden_licenses",
    }
    if set(policy) != expected or policy.get("format") != 1:
        raise SupplyChainValidationError("supply-chain policy fields are invalid")
    if policy.get("blocked_severities") != ["HIGH", "CRITICAL"]:
        raise SupplyChainValidationError("high and critical severities must block release")
    for field in ("required_scans", "sbom_formats", "forbidden_licenses"):
        values = policy.get(field)
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(value, str) and value for value in values)
        ):
            raise SupplyChainValidationError(f"policy {field} must be a non-empty string list")
        if len(values) != len(set(values)):
            raise SupplyChainValidationError(f"policy {field} must not contain duplicates")
    if set(policy["sbom_formats"]) != {"cyclonedx-json", "spdx-json"}:
        raise SupplyChainValidationError("both required SBOM formats must be configured")


def _validate_header(
    manifest: dict[str, Any],
    *,
    candidate: dict[str, Any],
    candidate_manifest_path: Path,
    tool_lock_path: Path,
    policy_path: Path,
) -> None:
    if set(manifest) != _MANIFEST_FIELDS or manifest.get("format") != 1:
        raise SupplyChainValidationError("supply-chain manifest fields are invalid")
    if manifest.get("source_commit") != candidate.get("source_commit"):
        raise SupplyChainValidationError("supply-chain source commit does not match candidate")
    expected = {
        "candidate_manifest_sha256": _file_identity(candidate_manifest_path)[1],
        "tool_lock_sha256": _file_identity(tool_lock_path)[1],
        "policy_sha256": _file_identity(policy_path)[1],
    }
    for field, digest in expected.items():
        if manifest.get(field) != digest:
            raise SupplyChainValidationError(f"{field} does not match its input")
    if candidate.get("tool_lock_sha256") != expected["tool_lock_sha256"]:
        raise SupplyChainValidationError("candidate was not built with the supplied tool lock")


def _validate_tools(value: object, *, tool_lock: dict[str, Any]) -> None:
    if not isinstance(value, dict) or set(value) != _REQUIRED_TOOLS:
        raise SupplyChainValidationError("supply-chain tool inventory is incomplete")
    lock_items = tool_lock.get("tools")
    if not isinstance(lock_items, list):
        raise SupplyChainValidationError("tool lock inventory is invalid")
    locked = {
        item.get("id"): item
        for item in lock_items
        if isinstance(item, dict) and item.get("id") in _REQUIRED_TOOLS
    }
    if set(locked) != _REQUIRED_TOOLS:
        raise SupplyChainValidationError("tool lock does not contain all required scanners")
    for identifier in _REQUIRED_TOOLS:
        supplied = value[identifier]
        expected = locked[identifier]
        if not isinstance(supplied, dict) or set(supplied) != {"reference", "version"}:
            raise SupplyChainValidationError("tool evidence fields are invalid")
        if supplied != {"reference": expected.get("reference"), "version": expected.get("version")}:
            raise SupplyChainValidationError(f"tool evidence does not match lock: {identifier}")


def _validate_database(value: object) -> None:
    fields = {"updated_at", "next_update", "downloaded_at"}
    if not isinstance(value, dict) or set(value) != fields:
        raise SupplyChainValidationError("vulnerability database metadata is incomplete")
    parsed: dict[str, datetime] = {}
    for field in fields:
        timestamp = value[field]
        if not isinstance(timestamp, str) or not _UTC.fullmatch(timestamp):
            raise SupplyChainValidationError("vulnerability database timestamps must be UTC")
        parsed[field] = datetime.fromisoformat(timestamp.removesuffix("Z") + "+00:00")
    if parsed["next_update"] <= parsed["updated_at"]:
        raise SupplyChainValidationError("vulnerability database update window is invalid")
    if parsed["downloaded_at"] < parsed["updated_at"]:
        raise SupplyChainValidationError("vulnerability database download predates its update")


def _safe_report(
    reference: object, *, root: Path, used_paths: set[str]
) -> tuple[dict[str, Any], dict[str, Any] | list[Any]]:
    if not isinstance(reference, dict) or set(reference) != _REPORT_FIELDS:
        raise SupplyChainValidationError("report reference fields are invalid")
    relative_value = reference.get("path")
    if not isinstance(relative_value, str):
        raise SupplyChainValidationError("report path must be text")
    relative = PurePosixPath(relative_value)
    if (
        "\\" in relative_value
        or relative.is_absolute()
        or not relative.parts
        or ".." in relative.parts
        or relative_value in used_paths
    ):
        raise SupplyChainValidationError("report path is unsafe or duplicated")
    path = root / relative
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
        raise SupplyChainValidationError("report is missing or unsafe")
    size, digest = _file_identity(path)
    if (
        not isinstance(reference.get("size"), int)
        or reference["size"] != size
        or not isinstance(reference.get("sha256"), str)
        or not _DIGEST.fullmatch(reference["sha256"])
        or reference["sha256"] != digest
    ):
        raise SupplyChainValidationError("report identity mismatch")
    used_paths.add(relative_value)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SupplyChainValidationError("report must be valid JSON") from error
    if not isinstance(payload, dict | list):
        raise SupplyChainValidationError("report JSON type is invalid")
    return reference, payload


def _validate_scans(
    value: object,
    *,
    policy: dict[str, Any],
    root: Path,
    used_paths: set[str],
) -> dict[str, dict[str, Any]]:
    required = set(policy["required_scans"])
    if not isinstance(value, dict) or set(value) != required:
        raise SupplyChainValidationError("required scan set is incomplete")
    validated: dict[str, dict[str, Any]] = {}
    for identifier in sorted(required):
        reference, payload = _safe_report(value[identifier], root=root, used_paths=used_paths)
        if identifier.startswith("gitleaks-"):
            if not isinstance(payload, list) or payload:
                raise SupplyChainValidationError("secret scan contains findings")
        else:
            if not isinstance(payload, dict):
                raise SupplyChainValidationError("Trivy report must be a JSON object")
            _validate_trivy(payload, identifier=identifier, policy=policy)
        validated[identifier] = reference
    return validated


def _validate_trivy(payload: dict[str, Any], *, identifier: str, policy: dict[str, Any]) -> None:
    if not isinstance(payload.get("SchemaVersion"), int) or not isinstance(
        payload.get("Results"), list
    ):
        raise SupplyChainValidationError("Trivy report contract is invalid")
    blocked = set(policy["blocked_severities"])
    forbidden = {license_name.casefold() for license_name in policy["forbidden_licenses"]}
    for result in payload["Results"]:
        if not isinstance(result, dict):
            raise SupplyChainValidationError("Trivy result must be an object")
        if identifier.endswith("-security"):
            for field in ("Vulnerabilities", "Misconfigurations"):
                findings = result.get(field, [])
                if not isinstance(findings, list):
                    raise SupplyChainValidationError("Trivy findings must be a list")
                for finding in findings:
                    if isinstance(finding, dict) and finding.get("Severity") in blocked:
                        raise SupplyChainValidationError("high or critical finding blocks release")
            secrets = result.get("Secrets", [])
            if not isinstance(secrets, list) or secrets:
                raise SupplyChainValidationError("Trivy secret findings block release")
        if identifier.endswith("-license"):
            licenses = result.get("Licenses", [])
            if not isinstance(licenses, list):
                raise SupplyChainValidationError("Trivy licenses must be a list")
            for finding in licenses:
                if (
                    isinstance(finding, dict)
                    and isinstance(finding.get("Name"), str)
                    and finding["Name"].casefold() in forbidden
                ):
                    raise SupplyChainValidationError("forbidden license blocks release")


def _validate_sboms(
    value: object,
    *,
    artifact_ids: set[str],
    formats: set[str],
    root: Path,
    used_paths: set[str],
) -> None:
    if not isinstance(value, list):
        raise SupplyChainValidationError("SBOM inventory must be a list")
    observed: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != _REPORT_FIELDS | {
            "artifact_id",
            "format",
        }:
            raise SupplyChainValidationError("SBOM evidence fields are invalid")
        artifact_id = item.get("artifact_id")
        sbom_format = item.get("format")
        key = (str(artifact_id), str(sbom_format))
        if artifact_id not in artifact_ids or sbom_format not in formats or key in observed:
            raise SupplyChainValidationError("SBOM target or format is invalid")
        _, payload = _safe_report(
            {field: item[field] for field in _REPORT_FIELDS}, root=root, used_paths=used_paths
        )
        if not isinstance(payload, dict):
            raise SupplyChainValidationError("SBOM must be a JSON object")
        if sbom_format == "cyclonedx-json":
            components = payload.get("components")
            if (
                payload.get("bomFormat") != "CycloneDX"
                or not isinstance(payload.get("specVersion"), str)
                or "components" not in payload
                or (components is not None and not isinstance(components, list))
            ):
                raise SupplyChainValidationError("CycloneDX SBOM contract is invalid")
        elif (
            not isinstance(payload.get("spdxVersion"), str)
            or not payload["spdxVersion"].startswith("SPDX-")
            or payload.get("SPDXID") != "SPDXRef-DOCUMENT"
            or not isinstance(payload.get("packages"), list)
        ):
            raise SupplyChainValidationError("SPDX SBOM contract is invalid")
        observed.add(key)
    expected = {
        (artifact_id, sbom_format) for artifact_id in artifact_ids for sbom_format in formats
    }
    if observed != expected:
        raise SupplyChainValidationError("every candidate artifact requires both SBOM formats")


def _validate_license_review(
    value: object,
    *,
    source_commit: str,
    scans: dict[str, dict[str, Any]],
    root: Path,
    used_paths: set[str],
) -> None:
    _, payload = _safe_report(value, root=root, used_paths=used_paths)
    fields = {
        "format",
        "source_commit",
        "decision",
        "reviewer",
        "reviewed_at",
        "report_sha256s",
        "exceptions",
    }
    if not isinstance(payload, dict) or set(payload) != fields or payload.get("format") != 1:
        raise SupplyChainValidationError("license review fields are invalid")
    if payload.get("source_commit") != source_commit or payload.get("decision") != "approved":
        raise SupplyChainValidationError("license review is not approved for this candidate")
    if not isinstance(payload.get("reviewer"), str) or not payload["reviewer"].strip():
        raise SupplyChainValidationError("license review must name a reviewer")
    reviewed_at = payload.get("reviewed_at")
    if not isinstance(reviewed_at, str) or not _UTC.fullmatch(reviewed_at):
        raise SupplyChainValidationError("license review time must be UTC")
    license_scans = {
        identifier: reference["sha256"]
        for identifier, reference in scans.items()
        if identifier.endswith("-license")
    }
    if payload.get("report_sha256s") != license_scans:
        raise SupplyChainValidationError("license review does not cover every license report")
    exceptions = payload.get("exceptions")
    if not isinstance(exceptions, list):
        raise SupplyChainValidationError("license exceptions must be a list")
    reviewed = datetime.fromisoformat(reviewed_at.removesuffix("Z") + "+00:00")
    for exception in exceptions:
        expected = {"license", "owner", "rationale", "expires_at"}
        if not isinstance(exception, dict) or set(exception) != expected:
            raise SupplyChainValidationError("license exception fields are invalid")
        if not all(
            isinstance(exception[field], str) and exception[field].strip()
            for field in ("license", "owner", "rationale", "expires_at")
        ) or not _UTC.fullmatch(exception["expires_at"]):
            raise SupplyChainValidationError("license exception values are invalid")
        expiry = datetime.fromisoformat(exception["expires_at"].removesuffix("Z") + "+00:00")
        if expiry <= reviewed:
            raise SupplyChainValidationError("license exception is already expired")
