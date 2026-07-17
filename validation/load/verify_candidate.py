from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

from morpheus.ops.candidate import verify_candidate

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = (ROOT / "artifacts").resolve()
DEFINITION = ROOT / "validation/candidate/artifact-set.json"


def _output_path(path: Path) -> Path:
    resolved = path.resolve(strict=False)
    if resolved == ARTIFACTS or ARTIFACTS not in resolved.parents:
        raise ValueError("candidate verification output must be below repository artifacts")
    return resolved


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify and bind soak to one candidate")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest_path = args.manifest.resolve(strict=True)
    payload = manifest_path.read_bytes()
    candidate = verify_candidate(manifest_path, definition_path=DEFINITION)
    _write(
        _output_path(args.output),
        {
            "schema_version": 1,
            "status": "pass",
            "candidate_manifest_sha256": hashlib.sha256(payload).hexdigest(),
            "candidate_version": candidate["candidate_version"],
            "source_commit": candidate["source_commit"],
        },
    )


if __name__ == "__main__":
    main()
