#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
COMMAND=${1:-}
: "${CANDIDATE_OUTPUT_ROOT:?set CANDIDATE_OUTPUT_ROOT to the candidate directory}"
: "${CANDIDATE_VERSION:?set CANDIDATE_VERSION to the semantic version}"
: "${SOURCE_DATE_EPOCH:?set SOURCE_DATE_EPOCH to the source commit timestamp}"
: "${SOURCE_COMMIT:?set SOURCE_COMMIT to the full source commit}"

if [[ ! ${CANDIDATE_VERSION} =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "CANDIDATE_VERSION must be semantic version text" >&2
  exit 2
fi
if [[ ! ${SOURCE_DATE_EPOCH} =~ ^[1-9][0-9]*$ ]]; then
  echo "SOURCE_DATE_EPOCH must be a positive integer" >&2
  exit 2
fi
if [[ ! ${SOURCE_COMMIT} =~ ^[0-9a-f]{40,64}$ ]]; then
  echo "SOURCE_COMMIT must be a full lowercase Git object ID" >&2
  exit 2
fi

OUTPUT_ROOT=$(realpath -m -- "${CANDIDATE_OUTPUT_ROOT}")
mkdir -p -- "${OUTPUT_ROOT}"
TEMP_DIR=$(mktemp -d --tmpdir="${OUTPUT_ROOT}" .candidate-build.XXXXXX)
trap 'rm -rf -- "${TEMP_DIR}"' EXIT

tracked_archive() {
  local destination=$1
  shift
  local temporary="${TEMP_DIR}/$(basename -- "${destination}")"
  mkdir -p -- "$(dirname -- "${destination}")"
  git -C "${ROOT}" ls-files -z -- "$@" \
    | LC_ALL=C sort -z \
    | tar --create --directory="${ROOT}" --sort=name --mtime="@${SOURCE_DATE_EPOCH}" \
        --owner=0 --group=0 --numeric-owner --pax-option=delete=atime,delete=ctime \
        --format=posix --null --files-from=- \
    | gzip -n > "${temporary}"
  mv -- "${temporary}" "${destination}"
}

payload_archive() {
  local destination=$1
  shift
  local temporary="${TEMP_DIR}/$(basename -- "${destination}")"
  mkdir -p -- "$(dirname -- "${destination}")"
  tar --create --directory="${OUTPUT_ROOT}" --sort=name \
      --mtime="@${SOURCE_DATE_EPOCH}" --owner=0 --group=0 --numeric-owner \
      --pax-option=delete=atime,delete=ctime --format=posix "$@" \
    | gzip -n > "${temporary}"
  mv -- "${temporary}" "${destination}"
}

case "${COMMAND}" in
  compose-config-bundle)
    tracked_archive \
      "${OUTPUT_ROOT}/payload/config/morpheus-compose-config-${CANDIDATE_VERSION}.tar.gz" \
      .env.example deploy/compose.yaml 'deploy/compose.*.yaml' deploy/config deploy/images.lock.json
    ;;
  migration-bundle)
    tracked_archive \
      "${OUTPUT_ROOT}/payload/migrations/morpheus-migrations-${CANDIDATE_VERSION}.tar.gz" \
      src/morpheus/adapters/persistence/sqlite.py
    ;;
  requirements-evidence)
    tracked_archive \
      "${OUTPUT_ROOT}/payload/requirements/morpheus-requirements-${CANDIDATE_VERSION}.tar.gz" \
      requirements.json requirements.schema.json docs/PRODUCT_SPECIFICATION.md \
      docs/IMPLEMENTATION_GAP_REVIEW.md
    ;;
  checksums)
    checksum_path="${OUTPUT_ROOT}/payload/SHA256SUMS"
    mkdir -p -- "$(dirname -- "${checksum_path}")"
    temporary="${TEMP_DIR}/SHA256SUMS"
    while IFS= read -r -d '' path; do
      relative=${path#"${OUTPUT_ROOT}/"}
      digest=$(sha256sum -- "${path}")
      printf '%s  %s\n' "${digest%% *}" "${relative}"
    done < <(
      find "${OUTPUT_ROOT}/payload" -type f ! -name SHA256SUMS ! -name 'candidate-manifest.json' \
        -print0 | LC_ALL=C sort -z
    ) > "${temporary}"
    mv -- "${temporary}" "${checksum_path}"
    ;;
  rollback-bundle)
    payload_archive \
      "${OUTPUT_ROOT}/payload/rollback/morpheus-rollback-${CANDIDATE_VERSION}-${SOURCE_COMMIT:0:12}.tar.gz" \
      payload/python payload/images payload/config payload/migrations payload/requirements
    ;;
  *)
    echo "usage: $0 {compose-config-bundle|migration-bundle|requirements-evidence|checksums|rollback-bundle}" >&2
    exit 2
    ;;
esac
