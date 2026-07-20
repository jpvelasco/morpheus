from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from morpheus.ops.supply_chain import (
    SupplyChainValidationError,
    _read_object,
    _safe_report,
    _validate_database,
    _validate_license_review,
    _validate_policy,
    _validate_sboms,
    _validate_tools,
    _validate_trivy,
    verify_supply_chain,
)

ROOT = Path(__file__).resolve().parents[2]
TOOL_LOCK = ROOT / "validation" / "tools" / "images.lock.json"
POLICY = ROOT / "validation" / "security" / "policy.json"
FINALIZER = ROOT / "validation" / "security" / "finalize.py"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _report(root: Path, relative: str, payload: object) -> dict[str, object]:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return {"path": relative, "sha256": _digest(path), "size": path.stat().st_size}


def _candidate(tmp_path: Path) -> tuple[Path, Path]:
    commit = "a" * 40
    definition = {
        "format": 1,
        "artifacts": [
            {
                "id": "backend-oci",
                "required": True,
                "path_pattern": "payload/backend.oci.tar",
                "media_type": "application/vnd.oci.image.layout.v1.tar",
            },
            {
                "id": "dashboard-oci",
                "required": True,
                "path_pattern": "payload/dashboard.oci.tar",
                "media_type": "application/vnd.oci.image.layout.v1.tar",
            },
            {
                "id": "checksums",
                "required": True,
                "path_pattern": "payload/SHA256SUMS",
                "media_type": "text/plain",
            },
        ],
        "checksum_scope": ["backend-oci", "dashboard-oci"],
    }
    definition_path = tmp_path / "artifact-set.json"
    definition_path.write_text(json.dumps(definition), encoding="utf-8")

    artifacts = []
    checksums: list[tuple[str, str]] = []
    for identifier, relative, media_type in (
        (
            "backend-oci",
            "payload/backend.oci.tar",
            "application/vnd.oci.image.layout.v1.tar",
        ),
        (
            "dashboard-oci",
            "payload/dashboard.oci.tar",
            "application/vnd.oci.image.layout.v1.tar",
        ),
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(identifier, encoding="utf-8")
        digest = _digest(path)
        checksums.append((relative, digest))
        artifacts.append(
            {
                "id": identifier,
                "path": relative,
                "media_type": media_type,
                "sha256": digest,
                "size": path.stat().st_size,
                "source_commit": commit,
            }
        )

    checksum_path = tmp_path / "payload/SHA256SUMS"
    checksum_path.write_text(
        "".join(f"{digest}  {relative}\n" for relative, digest in sorted(checksums)),
        encoding="utf-8",
    )
    artifacts.append(
        {
            "id": "checksums",
            "path": "payload/SHA256SUMS",
            "media_type": "text/plain",
            "sha256": _digest(checksum_path),
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
        "tool_lock_sha256": _digest(TOOL_LOCK),
        "artifacts": artifacts,
    }
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path, definition_path


def _supply_manifest(tmp_path: Path) -> tuple[Path, Path, Path]:
    candidate_manifest, definition = _candidate(tmp_path)
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    scans: dict[str, dict[str, object]] = {}
    for scan_id in policy["required_scans"]:
        payload: object = (
            []
            if scan_id.startswith("gitleaks-")
            else {
                "SchemaVersion": 2,
                "Results": [],
            }
        )
        scans[scan_id] = _report(tmp_path, f"reports/scans/{scan_id}.json", payload)

    sboms = []
    for artifact_id in ("backend-oci", "dashboard-oci", "checksums"):
        sboms.extend(
            [
                {
                    "artifact_id": artifact_id,
                    "format": "cyclonedx-json",
                    **_report(
                        tmp_path,
                        f"reports/sbom/{artifact_id}.cdx.json",
                        {
                            "bomFormat": "CycloneDX",
                            "specVersion": "1.6",
                            "components": None if artifact_id == "checksums" else [],
                        },
                    ),
                },
                {
                    "artifact_id": artifact_id,
                    "format": "spdx-json",
                    **_report(
                        tmp_path,
                        f"reports/sbom/{artifact_id}.spdx.json",
                        {
                            "spdxVersion": "SPDX-2.3",
                            "SPDXID": "SPDXRef-DOCUMENT",
                            "packages": [],
                        },
                    ),
                },
            ]
        )

    license_scans = {
        scan_id: reference["sha256"]
        for scan_id, reference in scans.items()
        if scan_id.endswith("-license")
    }
    license_review = _report(
        tmp_path,
        "reports/license-review.json",
        {
            "format": 1,
            "source_commit": "a" * 40,
            "decision": "approved",
            "reviewer": "release-license-reviewer",
            "reviewed_at": "2026-07-16T20:00:00Z",
            "report_sha256s": license_scans,
            "exceptions": [],
        },
    )
    tools = {
        item["id"]: {"reference": item["reference"], "version": item["version"]}
        for item in json.loads(TOOL_LOCK.read_text(encoding="utf-8"))["tools"]
        if item["id"] in {"secret-scan", "vulnerability-scan", "sbom", "license-scan"}
    }
    supply = {
        "format": 1,
        "source_commit": "a" * 40,
        "candidate_manifest_sha256": _digest(candidate_manifest),
        "tool_lock_sha256": _digest(TOOL_LOCK),
        "policy_sha256": _digest(POLICY),
        "vulnerability_database": {
            "updated_at": "2026-07-16T18:00:00Z",
            "next_update": "2026-07-17T00:00:00Z",
            "downloaded_at": "2026-07-16T18:05:00Z",
        },
        "tools": tools,
        "scans": scans,
        "sboms": sboms,
        "license_review": license_review,
        "result": "pass",
    }
    supply_path = tmp_path / "supply-chain-manifest.json"
    supply_path.write_text(json.dumps(supply), encoding="utf-8")
    return supply_path, candidate_manifest, definition


def test_SEC_005_accepts_complete_clean_scans_and_two_sboms_per_artifact(
    tmp_path: Path,
) -> None:
    supply, candidate, definition = _supply_manifest(tmp_path)

    verified = verify_supply_chain(
        supply,
        candidate_manifest_path=candidate,
        candidate_definition_path=definition,
        tool_lock_path=TOOL_LOCK,
        policy_path=POLICY,
    )

    assert verified["result"] == "pass"
    assert len(verified["sboms"]) == 6


def test_SEC_005_finalizer_atomically_builds_a_verified_manifest(tmp_path: Path) -> None:
    supplied_manifest, candidate, definition = _supply_manifest(tmp_path)
    supplied_manifest.unlink()
    database = tmp_path / "reports/trivy-db-metadata.json"
    database.write_text(
        json.dumps(
            {
                "UpdatedAt": "2026-07-16T18:00:00Z",
                "NextUpdate": "2026-07-17T00:00:00Z",
                "DownloadedAt": "2026-07-16T18:05:00Z",
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(  # noqa: S603 - fixed checked-in finalizer
        [
            sys.executable,
            FINALIZER,
            "finalize",
            "--output-root",
            tmp_path,
            "--candidate-manifest",
            candidate,
            "--candidate-definition",
            definition,
            "--tool-lock",
            TOOL_LOCK,
            "--policy",
            POLICY,
            "--database-metadata",
            database,
            "--license-review",
            tmp_path / "reports/license-review.json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == "security_manifest=passed\n"
    assert (tmp_path / "supply-chain-manifest.json").is_file()
    assert not (tmp_path / "supply-chain-manifest.json.tmp").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "high-vulnerability",
        "secret-finding",
        "missing-sbom",
        "wrong-tool",
        "unreviewed-license-scan",
        "bad-report-digest",
    ],
)
def test_SEC_005_rejects_incomplete_or_unsafe_supply_chain_evidence(
    tmp_path: Path, mutation: str
) -> None:
    supply_path, candidate, definition = _supply_manifest(tmp_path)
    supply = json.loads(supply_path.read_text(encoding="utf-8"))
    if mutation == "high-vulnerability":
        report = tmp_path / supply["scans"]["repository-filesystem-security"]["path"]
        report.write_text(
            json.dumps(
                {
                    "SchemaVersion": 2,
                    "Results": [
                        {"Vulnerabilities": [{"VulnerabilityID": "CVE-TEST", "Severity": "HIGH"}]}
                    ],
                }
            ),
            encoding="utf-8",
        )
        supply["scans"]["repository-filesystem-security"].update(
            {"sha256": _digest(report), "size": report.stat().st_size}
        )
    elif mutation == "secret-finding":
        report = tmp_path / supply["scans"]["gitleaks-history"]["path"]
        report.write_text(json.dumps([{"RuleID": "generic-api-key"}]), encoding="utf-8")
        supply["scans"]["gitleaks-history"].update(
            {"sha256": _digest(report), "size": report.stat().st_size}
        )
    elif mutation == "missing-sbom":
        supply["sboms"].pop()
    elif mutation == "wrong-tool":
        supply["tools"]["sbom"]["reference"] = "anchore/syft:latest"
    elif mutation == "unreviewed-license-scan":
        review = tmp_path / supply["license_review"]["path"]
        payload = json.loads(review.read_text(encoding="utf-8"))
        payload["report_sha256s"].pop("backend-oci-license")
        review.write_text(json.dumps(payload), encoding="utf-8")
        supply["license_review"].update({"sha256": _digest(review), "size": review.stat().st_size})
    else:
        supply["scans"]["candidate-artifacts-security"]["sha256"] = "0" * 64
    supply_path.write_text(json.dumps(supply), encoding="utf-8")

    with pytest.raises(SupplyChainValidationError):
        verify_supply_chain(
            supply_path,
            candidate_manifest_path=candidate,
            candidate_definition_path=definition,
            tool_lock_path=TOOL_LOCK,
            policy_path=POLICY,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("format", 2),
        ("blocked_severities", ["CRITICAL"]),
        ("required_scans", []),
        ("required_scans", ["duplicate", "duplicate"]),
        ("sbom_formats", ["cyclonedx-json"]),
        ("forbidden_licenses", [""]),
    ],
)
def test_supply_chain_policy_rejects_weakened_or_malformed_values(
    field: str, value: object
) -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    policy[field] = value

    with pytest.raises(SupplyChainValidationError):
        _validate_policy(policy)


@pytest.mark.parametrize(
    "value",
    [
        {},
        {
            "updated_at": "not-utc",
            "next_update": "2026-07-17T00:00:00Z",
            "downloaded_at": "2026-07-16T18:05:00Z",
        },
        {
            "updated_at": "2026-07-17T00:00:00Z",
            "next_update": "2026-07-17T00:00:00Z",
            "downloaded_at": "2026-07-17T00:05:00Z",
        },
        {
            "updated_at": "2026-07-17T00:00:00Z",
            "next_update": "2026-07-18T00:00:00Z",
            "downloaded_at": "2026-07-16T23:59:59Z",
        },
    ],
)
def test_vulnerability_database_metadata_rejects_incomplete_or_stale_values(
    value: object,
) -> None:
    with pytest.raises(SupplyChainValidationError):
        _validate_database(value)


def test_tool_inventory_rejects_missing_lock_and_malformed_evidence() -> None:
    lock = json.loads(TOOL_LOCK.read_text(encoding="utf-8"))
    valid = {
        item["id"]: {"reference": item["reference"], "version": item["version"]}
        for item in lock["tools"]
        if item["id"] in {"secret-scan", "vulnerability-scan", "sbom", "license-scan"}
    }
    invalid_cases = [
        ({}, lock),
        (valid, {"tools": "invalid"}),
        (valid, {"tools": []}),
        ({**valid, "sbom": "invalid"}, lock),
    ]
    for evidence, tool_lock in invalid_cases:
        with pytest.raises(SupplyChainValidationError):
            _validate_tools(evidence, tool_lock=tool_lock)


@pytest.mark.parametrize(
    ("identifier", "payload"),
    [
        ("repository-filesystem-security", {"SchemaVersion": "2", "Results": []}),
        ("repository-filesystem-security", {"SchemaVersion": 2, "Results": ["bad"]}),
        (
            "repository-filesystem-security",
            {"SchemaVersion": 2, "Results": [{"Vulnerabilities": "bad"}]},
        ),
        (
            "repository-filesystem-security",
            {
                "SchemaVersion": 2,
                "Results": [{"Misconfigurations": [{"Severity": "CRITICAL"}]}],
            },
        ),
        (
            "repository-filesystem-security",
            {"SchemaVersion": 2, "Results": [{"Secrets": [{"RuleID": "secret"}]}]},
        ),
        (
            "repository-filesystem-license",
            {"SchemaVersion": 2, "Results": [{"Licenses": "bad"}]},
        ),
        (
            "repository-filesystem-license",
            {"SchemaVersion": 2, "Results": [{"Licenses": [{"Name": "SSPL-1.0"}]}]},
        ),
    ],
)
def test_trivy_contract_rejects_malformed_or_blocking_findings(
    identifier: str, payload: dict[str, object]
) -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    with pytest.raises(SupplyChainValidationError):
        _validate_trivy(payload, identifier=identifier, policy=policy)


def test_trivy_contract_accepts_nonblocking_findings_and_permissive_license() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    _validate_trivy(
        {
            "SchemaVersion": 2,
            "Results": [
                {
                    "Vulnerabilities": [{"Severity": "LOW"}],
                    "Misconfigurations": [],
                    "Secrets": [],
                }
            ],
        },
        identifier="repository-filesystem-security",
        policy=policy,
    )
    _validate_trivy(
        {"SchemaVersion": 2, "Results": [{"Licenses": [{"Name": "MIT"}]}]},
        identifier="repository-filesystem-license",
        policy=policy,
    )
    # Clean filesystem/image scans may omit Results entirely.
    _validate_trivy(
        {"SchemaVersion": 2},
        identifier="candidate-artifacts-security",
        policy=policy,
    )


def test_report_reference_rejects_unsafe_corrupt_and_non_json_inputs(tmp_path: Path) -> None:
    valid = _report(tmp_path, "reports/valid.json", {})
    cases: list[object] = [
        {},
        {**valid, "path": 3},
        {**valid, "path": "../escape.json"},
        {**valid, "path": "reports/missing.json"},
        {**valid, "size": -1},
    ]
    for reference in cases:
        with pytest.raises(SupplyChainValidationError):
            _safe_report(reference, root=tmp_path, used_paths=set())

    invalid_json = tmp_path / "reports/invalid.json"
    invalid_json.write_text("{", encoding="utf-8")
    with pytest.raises(SupplyChainValidationError):
        _safe_report(
            {"path": "reports/invalid.json", "sha256": _digest(invalid_json), "size": 1},
            root=tmp_path,
            used_paths=set(),
        )
    scalar = _report(tmp_path, "reports/scalar.json", "scalar")
    with pytest.raises(SupplyChainValidationError):
        _safe_report(scalar, root=tmp_path, used_paths=set())
    with pytest.raises(SupplyChainValidationError):
        _safe_report(valid, root=tmp_path, used_paths={"reports/valid.json"})


@pytest.mark.parametrize(
    ("sbom_format", "payload"),
    [
        ("cyclonedx-json", {"bomFormat": "wrong", "specVersion": "1.6", "components": []}),
        (
            "spdx-json",
            {"spdxVersion": "wrong", "SPDXID": "SPDXRef-DOCUMENT", "packages": []},
        ),
    ],
)
def test_sbom_contract_rejects_malformed_documents(
    tmp_path: Path, sbom_format: str, payload: dict[str, object]
) -> None:
    reference = _report(tmp_path, f"reports/{sbom_format}.json", payload)
    item = {"artifact_id": "artifact", "format": sbom_format, **reference}
    with pytest.raises(SupplyChainValidationError):
        _validate_sboms(
            [item],
            artifact_ids={"artifact"},
            formats={sbom_format},
            root=tmp_path,
            used_paths=set(),
        )


def test_sbom_contract_accepts_cyclonedx_without_components_key(tmp_path: Path) -> None:
    # Syft emits metadata-only CycloneDX for empty package inventories.
    reference = _report(
        tmp_path,
        "reports/empty-cdx.json",
        {"bomFormat": "CycloneDX", "specVersion": "1.6"},
    )
    _validate_sboms(
        [{"artifact_id": "artifact", "format": "cyclonedx-json", **reference}],
        artifact_ids={"artifact"},
        formats={"cyclonedx-json"},
        root=tmp_path,
        used_paths=set(),
    )


def test_sbom_inventory_rejects_bad_shape_target_and_incomplete_coverage(tmp_path: Path) -> None:
    reference = _report(
        tmp_path,
        "reports/valid-cdx.json",
        {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": []},
    )
    invalid_values: list[object] = [
        {},
        [{"artifact_id": "artifact"}],
        [{"artifact_id": "wrong", "format": "cyclonedx-json", **reference}],
        [],
    ]
    for value in invalid_values:
        with pytest.raises(SupplyChainValidationError):
            _validate_sboms(
                value,
                artifact_ids={"artifact"},
                formats={"cyclonedx-json"},
                root=tmp_path,
                used_paths=set(),
            )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("format", 2),
        ("decision", "pending"),
        ("reviewer", ""),
        ("reviewed_at", "not-utc"),
        ("report_sha256s", {}),
        ("exceptions", "invalid"),
        ("exceptions", [{}]),
        (
            "exceptions",
            [{"license": "MIT", "owner": "owner", "rationale": "reason", "expires_at": "bad"}],
        ),
        (
            "exceptions",
            [
                {
                    "license": "MIT",
                    "owner": "owner",
                    "rationale": "reason",
                    "expires_at": "2026-07-16T19:00:00Z",
                }
            ],
        ),
    ],
)
def test_license_review_rejects_unapproved_malformed_or_expired_values(
    tmp_path: Path, field: str, value: object
) -> None:
    scan_digest = "a" * 64
    payload = {
        "format": 1,
        "source_commit": "a" * 40,
        "decision": "approved",
        "reviewer": "reviewer",
        "reviewed_at": "2026-07-16T20:00:00Z",
        "report_sha256s": {"artifact-license": scan_digest},
        "exceptions": [],
    }
    payload[field] = value
    reference = _report(tmp_path, "reports/review.json", payload)
    with pytest.raises(SupplyChainValidationError):
        _validate_license_review(
            reference,
            source_commit="a" * 40,
            scans={"artifact-license": {"sha256": scan_digest}},
            root=tmp_path,
            used_paths=set(),
        )


def test_license_review_accepts_a_complete_future_exception(tmp_path: Path) -> None:
    scan_digest = "a" * 64
    reference = _report(
        tmp_path,
        "reports/review.json",
        {
            "format": 1,
            "source_commit": "a" * 40,
            "decision": "approved",
            "reviewer": "reviewer",
            "reviewed_at": "2026-07-16T20:00:00Z",
            "report_sha256s": {"artifact-license": scan_digest},
            "exceptions": [
                {
                    "license": "LicenseRef-Review",
                    "owner": "owner",
                    "rationale": "bounded review",
                    "expires_at": "2026-08-16T20:00:00Z",
                }
            ],
        },
    )
    _validate_license_review(
        reference,
        source_commit="a" * 40,
        scans={"artifact-license": {"sha256": scan_digest}},
        root=tmp_path,
        used_paths=set(),
    )


def test_json_object_reader_rejects_missing_invalid_and_non_object_files(tmp_path: Path) -> None:
    with pytest.raises(SupplyChainValidationError):
        _read_object(tmp_path / "missing.json", label="fixture")
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    with pytest.raises(SupplyChainValidationError):
        _read_object(invalid, label="fixture")
    array = tmp_path / "array.json"
    array.write_text("[]", encoding="utf-8")
    with pytest.raises(SupplyChainValidationError):
        _read_object(array, label="fixture")
