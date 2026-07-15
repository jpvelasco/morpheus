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

for command in cmp cp docker git jq sha256sum tar uv; do
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
cache_root=$(cd -- "$(dirname -- "${cache_manifest}")" && pwd)
test "$(sha256sum "${cache_root}/wheelhouse/SHA256SUMS" | cut -d' ' -f1)" = \
  "$(jq -er '.dependency_inputs.wheelhouse_sha256' "${cache_manifest}")"
test "$(sha256sum "${cache_root}/npm-cache.SHA256SUMS" | cut -d' ' -f1)" = \
  "$(jq -er '.dependency_inputs.npm_cache_sha256' "${cache_manifest}")"
(
  cd "${cache_root}/wheelhouse"
  sha256sum --check SHA256SUMS
)
(
  cd "${cache_root}/npm-cache"
  sha256sum --check "${cache_root}/npm-cache.SHA256SUMS"
)
for image in python node; do
  reference=$(jq -er ".base_images.${image}.reference" "${cache_manifest}")
  expected=$(jq -er ".base_images.${image}.id" "${cache_manifest}")
  actual=$(docker image inspect --format '{{.Id}}' "${reference}")
  test "${actual}" = "${expected}"
done

mkdir -p "${output}/payload/python" "${output}/payload/images"
export SOURCE_DATE_EPOCH="${source_date_epoch}"
uv build --offline --out-dir "${output}/payload/python"
rm -f "${output}/payload/python/.gitignore"
cmp \
  "${cache_root}/python/morpheus_control_plane-${version}-py3-none-any.whl" \
  "${output}/payload/python/morpheus_control_plane-${version}-py3-none-any.whl"
cmp \
  "${cache_root}/python/morpheus_control_plane-${version}.tar.gz" \
  "${output}/payload/python/morpheus_control_plane-${version}.tar.gz"

work=$(mktemp -d)
cleanup() {
  rm -rf "${work}"
}
trap cleanup EXIT
git archive HEAD web | tar -x -C "${work}"
cp -a "${cache_root}/wheelhouse" "${work}/wheelhouse"
cp -a "${cache_root}/npm-cache" "${work}/npm-cache"

backend_output="${output}/payload/images/morpheus-backend-${version}-${short_commit}.oci.tar"
dashboard_output="${output}/payload/images/morpheus-dashboard-${version}-${short_commit}.oci.tar"
backend_tag="morpheus/backend:${version}-${short_commit}"
dashboard_tag="morpheus/dashboard:${version}-${short_commit}"
common_args=(
  --build-arg "MORPHEUS_VERSION=${version}"
  --build-arg "SOURCE_COMMIT=${source_commit}"
  --build-arg "SOURCE_CREATED=${source_created}"
  --build-arg "SOURCE_DATE_EPOCH=${source_date_epoch}"
  --network=none
  --no-cache
  --platform linux/amd64
  --provenance=false
  --pull=false
)
docker buildx build "${common_args[@]}" \
  --tag "${backend_tag}" \
  --file "${root}/validation/candidate/Dockerfile.backend" \
  --output "type=oci,dest=${backend_output},rewrite-timestamp=true" \
  "${work}"
docker buildx build "${common_args[@]}" \
  --tag "${dashboard_tag}" \
  --file "${root}/validation/candidate/Dockerfile.dashboard" \
  --output "type=oci,dest=${dashboard_output},rewrite-timestamp=true" \
  "${work}"

(
  cd "${output}"
  find payload -type f -print0 \
    | sort -z \
    | xargs -0 sha256sum >SHA256SUMS
)
jq -n \
  --arg source_commit "${source_commit}" \
  --argjson source_date_epoch "${source_date_epoch}" \
  --arg version "${version}" \
  --arg backend_tag "${backend_tag}" \
  --arg dashboard_tag "${dashboard_tag}" \
  --arg cache_manifest_sha256 "$(sha256sum "${cache_manifest}" | cut -d' ' -f1)" \
  '{
    format: 1,
    source_commit: $source_commit,
    source_date_epoch: $source_date_epoch,
    version: $version,
    network: "blocked-by-nftables",
    images: {
      backend: {tag: $backend_tag},
      dashboard: {tag: $dashboard_tag}
    },
    cache_manifest_sha256: $cache_manifest_sha256
  }' >"${output}/offline-rebuild.json.tmp"
mv "${output}/offline-rebuild.json.tmp" "${output}/offline-rebuild.json"

echo "offline_rebuild=${output}"
