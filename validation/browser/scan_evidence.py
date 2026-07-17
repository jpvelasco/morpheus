from __future__ import annotations

import sys
import zipfile
from pathlib import Path
from typing import BinaryIO

CANARY = b"browser-test-key"
CHUNK_SIZE = 1024 * 1024
MAX_ARCHIVE_MEMBER_BYTES = 512 * 1024 * 1024


def _contains_canary(stream: BinaryIO) -> bool:
    overlap = b""
    while chunk := stream.read(CHUNK_SIZE):
        combined = overlap + chunk
        if CANARY in combined:
            return True
        overlap = combined[-(len(CANARY) - 1) :]
    return False


def _scan_file(path: Path) -> bool:
    with path.open("rb") as stream:
        return _contains_canary(stream)


def _scan_zip(path: Path) -> list[str]:
    matches: list[str] = []
    with zipfile.ZipFile(path) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            if member.file_size > MAX_ARCHIVE_MEMBER_BYTES:
                raise ValueError(f"archive member exceeds scan bound: {path.name}:{member.filename}")
            with archive.open(member) as stream:
                if _contains_canary(stream):
                    matches.append(member.filename)
    return matches


def scan_evidence(root: Path) -> list[str]:
    matches: list[str] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if _scan_file(path):
            matches.append(relative)
        if path.suffix == ".zip":
            matches.extend(f"{relative}:{member}" for member in _scan_zip(path))
    return matches


def main(arguments: list[str] | None = None) -> int:
    values = sys.argv[1:] if arguments is None else arguments
    if len(values) != 1:
        print("usage: scan_evidence.py ARTIFACT_ROOT", file=sys.stderr)
        return 2
    try:
        matches = scan_evidence(Path(values[0]).resolve(strict=True))
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"Browser evidence scan failed closed: {error}", file=sys.stderr)
        return 2
    if matches:
        print("Synthetic browser credential found in retained evidence:", file=sys.stderr)
        for match in matches:
            print(f"- {match}", file=sys.stderr)
        return 1
    print("Browser evidence credential-canary scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
