from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from morpheus.adapters.runtime.resources import DockerResourceObserver
from morpheus.core.performance import assess_resource_budget, assess_resource_growth

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = (ROOT / "artifacts").resolve()


def _output_path(path: Path) -> Path:
    resolved = path.resolve(strict=False)
    if resolved == ARTIFACTS or ARTIFACTS not in resolved.parents:
        raise ValueError("resource evidence output must be below repository artifacts")
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Sample labeled Morpheus container resources")
    parser.add_argument("--project", required=True)
    parser.add_argument("--source-commit")
    parser.add_argument("--release-version")
    parser.add_argument("--component", action="append", dest="components")
    parser.add_argument("--phase", choices=("idle", "active"), required=True)
    parser.add_argument("--samples", type=int, default=6)
    parser.add_argument("--interval-seconds", type=float, default=5.0)
    parser.add_argument("--max-memory-growth-bytes", type=int, default=64 * 1024**2)
    parser.add_argument("--max-pid-growth", type=int, default=8)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.samples <= 10_000 or not 0 <= args.interval_seconds <= 300:
        raise ValueError("resource sampling bounds are invalid")
    components = tuple(args.components or ("api", "dashboard"))
    observer = DockerResourceObserver(
        project_id=args.project,
        expected_source_commit=args.source_commit,
        expected_release_version=args.release_version,
    )
    snapshots: list[dict[str, object]] = []
    assessments = []
    passed = True
    for index in range(args.samples):
        samples = observer.observe(required_components=components)
        assessment = assess_resource_budget(
            samples,
            required_components=components,
            max_idle_cpu_percent=2.0 if args.phase == "idle" else None,
        )
        passed = passed and assessment.passed
        assessments.append(assessment)
        snapshots.append(
            {
                "observed_at": datetime.now(UTC).isoformat(),
                "samples": [asdict(sample) for sample in samples],
                "assessment": asdict(assessment),
            }
        )
        if index + 1 < args.samples:
            time.sleep(args.interval_seconds)
    growth = (
        assess_resource_growth(
            tuple(assessments),
            max_memory_growth_bytes=args.max_memory_growth_bytes,
            max_pid_growth=args.max_pid_growth,
        )
        if len(assessments) > 1
        else None
    )
    passed = passed and (growth is None or growth.passed)
    _write(
        _output_path(args.output),
        {
            "schema_version": 1,
            "phase": args.phase,
            "project": args.project,
            "status": "pass" if passed else "fail",
            "growth_assessment": asdict(growth) if growth is not None else None,
            "snapshots": snapshots,
        },
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
