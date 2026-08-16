#!/usr/bin/env bash
# Build a checksummed developer/source-qualified desktop package (DESK-002).
#
# Bundles the compiled desktop shell and its fallback page into the same
# versioned .mrpkg format used by backend artifacts (manifest.json with
# per-file SHA-256 digests plus an SPDX SBOM), then emits SHA256SUMS over
# the package. Unsigned by design under ADR-0009: every install or update
# of this package requires explicit local confirmation and unattended
# update is impossible.
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
: "${DESKTOP_VERSION:?set DESKTOP_VERSION to the semantic version}"
if [[ ! ${DESKTOP_VERSION} =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "DESKTOP_VERSION must be semantic version text" >&2
  exit 2
fi

PLATFORM=$(uname -s | tr '[:upper:]' '[:lower:]')
case "${PLATFORM}" in
  linux) PLATFORM=linux ;;
  darwin) PLATFORM=darwin ;;
  msys* | mingw* | cygwin*) PLATFORM=win32 ;;
  *) echo "unsupported platform: ${PLATFORM}" >&2 && exit 2 ;;
esac
ARCH=$(uname -m)
case "${ARCH}" in
  x86_64 | amd64) ARCH=x86_64 ;;
  arm64 | aarch64) ARCH=arm64 ;;
  *) echo "unsupported architecture: ${ARCH}" >&2 && exit 2 ;;
esac

BIN_DIR="${ROOT}/desktop/src-tauri/target/release"
BIN="${BIN_DIR}/morpheus-desktop"
if [[ ${PLATFORM} == win32 ]]; then
  BIN="${BIN}.exe"
fi
if [[ ! -x ${BIN} ]]; then
  echo "release binary not found: ${BIN}" >&2
  exit 3
fi

OUTPUT_ROOT=${DESKTOP_PACKAGE_OUTPUT_ROOT:-${ROOT}/artifacts/desktop}
mkdir -p -- "${OUTPUT_ROOT}"
TEMP_DIR=$(mktemp -d --tmpdir="${OUTPUT_ROOT}" .desktop-package.XXXXXX)
trap 'rm -rf -- "${TEMP_DIR}"' EXIT

STAGING="${TEMP_DIR}/staging"
mkdir -p -- "${STAGING}/fallback"
cp -- "${BIN}" "${STAGING}/morpheus-desktop"
cp -- "${ROOT}/desktop/src-tauri/fallback/index.html" "${STAGING}/fallback/index.html"

ARCHIVE="${TEMP_DIR}/morpheus-desktop-${DESKTOP_VERSION}-${PLATFORM}-${ARCH}.mrpkg"
uv run --python 3.12 python -c "
import sys
from pathlib import Path
from morpheus.core.packages import PackageVersion, build_package
source = Path(sys.argv[1])
build_package(
    source / 'staging',
    Path(sys.argv[2]),
    name='morpheus-desktop',
    version=PackageVersion.parse(sys.argv[3]),
    platform=f'{sys.argv[4]}-{sys.argv[5]}',
)
" "${TEMP_DIR}" "${ARCHIVE}" "${DESKTOP_VERSION}" "${PLATFORM}" "${ARCH}"

DESTINATION="${OUTPUT_ROOT}/morpheus-desktop-${DESKTOP_VERSION}-${PLATFORM}-${ARCH}.mrpkg"
mv -- "${ARCHIVE}" "${DESTINATION}"
(cd -- "${OUTPUT_ROOT}" && sha256sum -- "morpheus-desktop-${DESKTOP_VERSION}-${PLATFORM}-${ARCH}.mrpkg" > "SHA256SUMS")
echo "desktop package: ${DESTINATION}"
echo "checksums: ${OUTPUT_ROOT}/SHA256SUMS"