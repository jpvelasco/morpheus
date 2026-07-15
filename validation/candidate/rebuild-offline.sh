#!/usr/bin/env bash
set -euo pipefail

umask 077
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
root=$(cd -- "${script_dir}/../.." && pwd)
offline_table=morpheus_validation_offline

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 CACHE_MANIFEST CANDIDATE_OUTPUT_DIRECTORY" >&2
  exit 64
fi

cache_manifest=$1
output=$2
if [[ ! -f "${cache_manifest}" ]]; then
  echo "Cache manifest does not exist: ${cache_manifest}" >&2
  exit 2
fi
if [[ -e "${output}" ]]; then
  echo "Candidate output destination already exists: ${output}" >&2
  exit 2
fi

for command in docker git jq sha256sum uv; do
  command -v "${command}" >/dev/null || {
    echo "Missing required command: ${command}" >&2
    exit 1
  }
done
sudo -n nft list table inet "${offline_table}" >/dev/null

cd "${root}"
if [[ -n "$(git status --porcelain=v1)" ]]; then
  echo "Offline rebuild requires a clean Git checkout." >&2
  exit 2
fi

source_commit=$(git rev-parse HEAD)
source_date_epoch=$(git show -s --format=%ct HEAD)
source_created=$(date --utc --date="@${source_date_epoch}" +%Y-%m-%dT%H:%M:%SZ)
version=$(uv run --offline --no-sync python -c \
  'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')
short_commit=${source_commit:0:12}

test "$(jq -er '.format' "${cache_manifest}")" = 1
test "$(jq -er '.source_commit' "${cache_manifest}")" = "${source_commit}"
test "$(jq -er '.source_date_epoch' "${cache_manifest}")" = "${source_date_epoch}"
test "$(jq -er '.version' "${cache_manifest}")" = "${version}"
for image in backend dashboard; do
  tag=$(jq -er ".images.${image}.tag" "${cache_manifest}")
  expected=$(jq -er ".images.${image}.id" "${cache_manifest}")
  actual=$(docker image inspect --format '{{.Id}}' "${tag}")
  test "${actual}" = "${expected}"
done

mkdir -p "${output}/payload/python" "${output}/payload/images"
export SOURCE_DATE_EPOCH="${source_date_epoch}"
uv build --offline --out-dir "${output}/payload/python"

backend_output="${output}/payload/images/morpheus-backend-${version}-${short_commit}.oci.tar"
dashboard_output="${output}/payload/images/morpheus-dashboard-${version}-${short_commit}.oci.tar"
common_args=(
  --build-arg "MORPHEUS_VERSION=${version}"
  --build-arg "SOURCE_COMMIT=${source_commit}"
  --build-arg "SOURCE_CREATED=${source_created}"
  --build-arg "SOURCE_DATE_EPOCH=${source_date_epoch}"
  --provenance=false
  --pull=false
)
docker buildx build "${common_args[@]}" \
  --file deploy/Dockerfile \
  --output "type=oci,dest=${backend_output},rewrite-timestamp=true" \
  .
docker buildx build "${common_args[@]}" \
  --file web/Dockerfile \
  --output "type=oci,dest=${dashboard_output},rewrite-timestamp=true" \
  .

find "${output}/payload" -type f -print0 \
  | sort -z \
  | xargs -0 sha256sum >"${output}/SHA256SUMS"
jq -n \
  --arg source_commit "${source_commit}" \
  --argjson source_date_epoch "${source_date_epoch}" \
  --arg version "${version}" \
  --arg cache_manifest_sha256 "$(sha256sum "${cache_manifest}" | cut -d' ' -f1)" \
  '{
    format: 1,
    source_commit: $source_commit,
    source_date_epoch: $source_date_epoch,
    version: $version,
    network: "blocked-by-nftables",
    cache_manifest_sha256: $cache_manifest_sha256
  }' >"${output}/offline-rebuild.json.tmp"
mv "${output}/offline-rebuild.json.tmp" "${output}/offline-rebuild.json"

echo "offline_rebuild=${output}"
