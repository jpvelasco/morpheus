from __future__ import annotations

import hashlib
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "validation/candidate/build.sh"


def test_ART_001_candidate_bundle_builder_is_reproducible(tmp_path: Path) -> None:
    outputs = [tmp_path / "first", tmp_path / "second"]
    environment = {
        **os.environ,
        "CANDIDATE_VERSION": "0.1.0",
        "SOURCE_DATE_EPOCH": "1752600000",
        "SOURCE_COMMIT": "a" * 40,
    }
    archives = []
    for output in outputs:
        subprocess.run(  # noqa: S603 - checked-in fixed builder and subcommand
            [BUILDER, "migration-bundle"],
            check=True,
            cwd=ROOT,
            env={**environment, "CANDIDATE_OUTPUT_ROOT": str(output)},
        )
        archive = output / "payload/migrations/morpheus-migrations-0.1.0.tar.gz"
        archives.append(archive)
        with tarfile.open(archive) as bundle:
            assert bundle.getnames() == ["src/morpheus/adapters/persistence/sqlite.py"]

    assert (
        hashlib.sha256(archives[0].read_bytes()).digest()
        == hashlib.sha256(archives[1].read_bytes()).digest()
    )
