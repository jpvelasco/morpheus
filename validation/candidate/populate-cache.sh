#!/usr/bin/env bash
set -euo pipefail

umask 077
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
root=$(cd -- "${script_dir}/../.." && pwd)

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 CACHE_EVIDENCE_DIRECTORY" >&2
  exit 64
fi

output=$1
if [[ -e "${output}" ]]; then
  echo "Cache evidence destination already exists: ${output}" >&2
  exit 2
fi

for command in docker git jq uv; do
  command -v "${command}" >/dev/null || {
    echo "Missing required command: ${command}" >&2
    exit 1
  }
done

cd "${root}"
if [[ -n "$(git status --porcelain=v1)" ]]; then
  echo "Cache population requires a clean Git checkout." >&2
  exit 2
fi

source_commit=$(git rev-parse HEAD)
source_date_epoch=$(git show -s --format=%ct HEAD)
source_created=$(date --utc --date="@${source_date_epoch}" +%Y-%m-%dT%H:%M:%SZ)
version=$(uv run --no-sync python -c \
  'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')
short_commit=${source_commit:0:12}
backend_tag="morpheus/backend:cache-${short_commit}"
dashboard_tag="morpheus/dashboard:cache-${short_commit}"

mkdir -p "${output}/python"
export SOURCE_DATE_EPOCH="${source_date_epoch}"

# This is the one declared network-enabled dependency-fetch phase. The later
# rebuild must run through validation/vm/offline-egress.sh.
uv sync --python 3.12 --extra dev --frozen
uv build --offline --out-dir "${output}/python"
rm -f "${output}/python/.gitignore"
docker buildx build \
  --build-arg "MORPHEUS_VERSION=${version}" \
  --build-arg "SOURCE_COMMIT=${source_commit}" \
  --build-arg "SOURCE_CREATED=${source_created}" \
  --build-arg "SOURCE_DATE_EPOCH=${source_date_epoch}" \
  --file deploy/Dockerfile \
  --load \
  --provenance=false \
  --tag "${backend_tag}" \
  .
docker buildx build \
  --build-arg "MORPHEUS_VERSION=${version}" \
  --build-arg "SOURCE_COMMIT=${source_commit}" \
  --build-arg "SOURCE_CREATED=${source_created}" \
  --build-arg "SOURCE_DATE_EPOCH=${source_date_epoch}" \
  --file web/Dockerfile \
  --load \
  --provenance=false \
  --tag "${dashboard_tag}" \
  .

backend_id=$(docker image inspect --format '{{.Id}}' "${backend_tag}")
dashboard_id=$(docker image inspect --format '{{.Id}}' "${dashboard_tag}")
jq -n \
  --arg source_commit "${source_commit}" \
  --argjson source_date_epoch "${source_date_epoch}" \
  --arg version "${version}" \
  --arg backend_tag "${backend_tag}" \
  --arg backend_id "${backend_id}" \
  --arg dashboard_tag "${dashboard_tag}" \
  --arg dashboard_id "${dashboard_id}" \
  '{
    format: 1,
    source_commit: $source_commit,
    source_date_epoch: $source_date_epoch,
    version: $version,
    cache_scope: "local-docker-driver-and-uv-cache",
    images: {
      backend: {tag: $backend_tag, id: $backend_id},
      dashboard: {tag: $dashboard_tag, id: $dashboard_id}
    }
  }' >"${output}/cache-manifest.json.tmp"
mv "${output}/cache-manifest.json.tmp" "${output}/cache-manifest.json"
sha256sum "${output}"/python/* >"${output}/python/SHA256SUMS"

echo "cache_manifest=${output}/cache-manifest.json"
