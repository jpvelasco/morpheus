from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from morpheus.core.performance import assess_load_overhead
from morpheus.ops.performance import parse_k6_summary

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = (ROOT / "artifacts").resolve()


def _artifact_path(path: Path, *, must_exist: bool) -> Path:
    resolved = path.resolve(strict=must_exist)
    if resolved == ARTIFACTS or ARTIFACTS not in resolved.parents:
        raise ValueError("load evidence paths must be below repository artifacts")
    if must_exist and (resolved.is_symlink() or not resolved.is_file()):
        raise ValueError("load input must be a regular non-symlink file")
    return resolved


def _read(path: Path) -> tuple[dict[str, object], str]:
    payload = path.read_bytes()
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("load summary must be a JSON object")
    return value, hashlib.sha256(payload).hexdigest()


def _write(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare fixed direct and telemetry load evidence")
    parser.add_argument("--direct", type=Path, required=True)
    parser.add_argument("--proxied", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    direct_path = _artifact_path(args.direct, must_exist=True)
    proxied_path = _artifact_path(args.proxied, must_exist=True)
    output_path = _artifact_path(args.output, must_exist=False)
    direct_document, direct_digest = _read(direct_path)
    proxied_document, proxied_digest = _read(proxied_path)
    direct = parse_k6_summary(direct_document)
    proxied = parse_k6_summary(proxied_document)
    assessment = assess_load_overhead(direct=direct, proxied=proxied)
    _write(
        output_path,
        {
            "schema_version": 1,
            "generated_at": datetime.now(UTC).isoformat(),
            "status": "pass" if assessment.passed else "fail",
            "inputs": {
                "direct_sha256": direct_digest,
                "proxied_sha256": proxied_digest,
            },
            "direct": asdict(direct),
            "proxied": asdict(proxied),
            "assessment": asdict(assessment),
        },
    )
    return 0 if assessment.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
