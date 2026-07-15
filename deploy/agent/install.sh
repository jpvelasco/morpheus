#!/usr/bin/env bash
set -euo pipefail

umask 077
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 ABSOLUTE_INSTALL_DIRECTORY" >&2
  exit 64
fi

destination=$1
if [[ ${destination} != /* ]]; then
  echo "Install directory must be absolute." >&2
  exit 2
fi
if [[ -e ${destination} ]]; then
  echo "Install directory already exists: ${destination}" >&2
  exit 2
fi
agent_python=${MORPHEUS_AGENT_PYTHON:-python3}
for command in find mktemp mv sha256sum "${agent_python}"; do
  command -v "${command}" >/dev/null || {
    echo "Missing required command: ${command}" >&2
    exit 1
  }
done
python_version=$("${agent_python}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if [[ ${python_version} != 3.12 ]]; then
  echo "Runtime agent requires CPython 3.12; ${agent_python} is ${python_version}." >&2
  echo "Set MORPHEUS_AGENT_PYTHON to the absolute CPython 3.12 executable." >&2
  exit 2
fi

parent=$(dirname -- "${destination}")
if [[ ! -d ${parent} ]]; then
  echo "Install parent directory does not exist: ${parent}" >&2
  exit 2
fi
temporary=$(mktemp -d --tmpdir="${parent}" .morpheus-agent.XXXXXX)
cleanup() {
  if [[ -n ${temporary} && -d ${temporary} ]]; then
    rm -rf -- "${temporary}"
  fi
}
trap cleanup EXIT

(
  cd "${root}/wheelhouse"
  sha256sum --check SHA256SUMS
)
"${agent_python}" -m venv "${temporary}"
"${temporary}/bin/python" -m pip install \
  --no-cache-dir \
  --no-index \
  --require-hashes \
  --find-links "${root}/wheelhouse" \
  --requirement "${root}/runtime-requirements.txt"
mapfile -d '' agent_wheels < <(
  find "${root}/wheelhouse" -maxdepth 1 -type f \
    -name 'morpheus_control_plane-*.whl' -print0
)
if [[ ${#agent_wheels[@]} -ne 1 ]]; then
  echo "Expected exactly one Morpheus agent wheel." >&2
  exit 2
fi
"${temporary}/bin/python" -m pip install \
  --no-cache-dir --no-deps --no-index "${agent_wheels[0]}"
"${temporary}/bin/python" -m pip check

# venv console scripts embed the absolute environment path in their shebangs.
# Point them at the final path before the atomic rename so the installed
# entrypoints do not retain the deleted staging-directory name.
MORPHEUS_STAGING_DIRECTORY="${temporary}" \
MORPHEUS_INSTALL_DIRECTORY="${destination}" \
  "${temporary}/bin/python" - <<'PY'
import os
from pathlib import Path

staging = os.environ["MORPHEUS_STAGING_DIRECTORY"].encode()
destination = os.environ["MORPHEUS_INSTALL_DIRECTORY"].encode()
for path in (Path(os.environ["MORPHEUS_STAGING_DIRECTORY"]) / "bin").iterdir():
    if path.is_symlink() or not path.is_file():
        continue
    content = path.read_bytes()
    rewritten = content.replace(staging, destination)
    if rewritten != content:
        path.write_bytes(rewritten)
    if staging in rewritten:
        raise RuntimeError(f"staging path remains in {path.name}")
PY
mv --no-clobber --no-target-directory -- "${temporary}" "${destination}"
temporary=

echo "agent_install=${destination}"
