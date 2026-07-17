from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from morpheus.ops.candidate import verify_candidate
from morpheus.ops.supply_chain import verify_supply_chain

ARTIFACT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
REQUIRED_TOOLS = {"secret-scan", "vulnerability-scan", "sbom", "license-scan"}


def _object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise AssertionError(f"required JSON input is missing or unsafe: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"JSON input must be an object: {path.name}")
    return value


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _reference(root: Path, relative: str) -> dict[str, object]:
    path = root / relative
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
        raise AssertionError(f"security report is missing or unsafe: {relative}")
    return {"path": relative, "sha256": _digest(path), "size": path.stat().st_size}


def _utc(value: object) -> str:
    if not isinstance(value, str):
        raise AssertionError("vulnerability database timestamp is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def _inputs(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    candidate = verify_candidate(
        args.candidate_manifest, definition_path=args.candidate_definition
    )
    tool_lock = _object(args.tool_lock)
    policy = _object(args.policy)
    if candidate["tool_lock_sha256"] != _digest(args.tool_lock):
        raise AssertionError("candidate tool lock does not match the supplied lock")
    return candidate, tool_lock, policy


def _scan_references(output: Path, policy: dict[str, Any]) -> dict[str, dict[str, object]]:
    return {
        scan_id: _reference(output, f"reports/scans/{scan_id}.json")
        for scan_id in policy["required_scans"]
    }


def _license_template(
    *, output: Path, candidate: dict[str, Any], scans: dict[str, dict[str, object]]
) -> Path:
    template = {
        "format": 1,
        "source_commit": candidate["source_commit"],
        "decision": "pending",
        "reviewer": "REPLACE_WITH_REVIEWER",
        "reviewed_at": "REPLACE_WITH_UTC_TIMESTAMP",
        "report_sha256s": {
            scan_id: reference["sha256"]
            for scan_id, reference in scans.items()
            if scan_id.endswith("-license")
        },
        "exceptions": [],
    }
    destination = output / "license-review.template.json"
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(template, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, destination)
    return destination


def _manifest(
    *,
    args: argparse.Namespace,
    candidate: dict[str, Any],
    tool_lock: dict[str, Any],
    policy: dict[str, Any],
    scans: dict[str, dict[str, object]],
) -> dict[str, Any]:
    output = args.output_root.resolve()
    tools = {
        item["id"]: {"reference": item["reference"], "version": item["version"]}
        for item in tool_lock["tools"]
        if item.get("id") in REQUIRED_TOOLS
    }
    if set(tools) != REQUIRED_TOOLS:
        raise AssertionError("tool lock does not contain every security tool")
    database = _object(args.database_metadata)
    vulnerability_database = {
        "updated_at": _utc(database.get("UpdatedAt", database.get("updated_at"))),
        "next_update": _utc(database.get("NextUpdate", database.get("next_update"))),
        "downloaded_at": _utc(
            database.get("DownloadedAt", database.get("downloaded_at"))
        ),
    }
    sboms = []
    for artifact in candidate["artifacts"]:
        identifier = artifact["id"]
        if not isinstance(identifier, str) or not ARTIFACT_ID.fullmatch(identifier):
            raise AssertionError("candidate artifact ID is unsafe for report paths")
        for sbom_format, suffix in (
            ("cyclonedx-json", "cdx.json"),
            ("spdx-json", "spdx.json"),
        ):
            sboms.append(
                {
                    "artifact_id": identifier,
                    "format": sbom_format,
                    **_reference(output, f"reports/sbom/{identifier}.{suffix}"),
                }
            )
    return {
        "format": 1,
        "source_commit": candidate["source_commit"],
        "candidate_manifest_sha256": _digest(args.candidate_manifest),
        "tool_lock_sha256": _digest(args.tool_lock),
        "policy_sha256": _digest(args.policy),
        "vulnerability_database": vulnerability_database,
        "tools": tools,
        "scans": scans,
        "sboms": sboms,
        "license_review": _reference(output, "reports/license-review.json"),
        "result": "pass",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Finalize Morpheus supply-chain evidence")
    parser.add_argument("action", choices=("preflight", "review-template", "finalize"))
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--candidate-definition", type=Path, required=True)
    parser.add_argument("--tool-lock", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--database-metadata", type=Path)
    parser.add_argument("--license-review", type=Path)
    args = parser.parse_args()

    candidate, tool_lock, policy = _inputs(args)
    if args.action == "preflight":
        return
    output = args.output_root.resolve()
    scans = _scan_references(output, policy)
    if args.action == "review-template":
        path = _license_template(output=output, candidate=candidate, scans=scans)
        sys.stdout.write(f"license_review_template={path}\n")
        return
    if args.database_metadata is None or args.license_review is None:
        raise AssertionError("finalize requires database metadata and a license review")
    if args.license_review.is_symlink() or not args.license_review.is_file():
        raise AssertionError("license review must be a regular non-symlink file")
    review_destination = output / "reports/license-review.json"
    if review_destination.is_symlink():
        raise AssertionError("license review destination must not be a symlink")
    if args.license_review.resolve() != review_destination.resolve():
        shutil.copyfile(args.license_review, review_destination)
        review_destination.chmod(0o600)
    manifest = _manifest(
        args=args,
        candidate=candidate,
        tool_lock=tool_lock,
        policy=policy,
        scans=scans,
    )
    destination = output / "supply-chain-manifest.json"
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    verify_supply_chain(
        temporary,
        candidate_manifest_path=args.candidate_manifest,
        candidate_definition_path=args.candidate_definition,
        tool_lock_path=args.tool_lock,
        policy_path=args.policy,
    )
    os.replace(temporary, destination)
    sys.stdout.write("security_manifest=passed\n")


if __name__ == "__main__":
    main()
