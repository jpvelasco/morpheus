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
for command in find mktemp mv python3 sha256sum; do
  command -v "${command}" >/dev/null || {
    echo "Missing required command: ${command}" >&2
    exit 1
  }
done

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
python3 -m venv "${temporary}"
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
mv --no-clobber --no-target-directory -- "${temporary}" "${destination}"
temporary=

echo "agent_install=${destination}"
