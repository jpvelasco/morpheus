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
export SOURCE_DATE_EPOCH="${source_date_epoch}"

# This is the one declared network-enabled dependency-fetch phase. It creates
# portable, hash-inventoried Python and npm inputs and pulls only the two exact
# candidate base images. The later image build runs no-cache under an egress
# block and does not depend on application-layer cache hits.
uv sync --python 3.12 --extra dev --frozen
version=$(uv run --offline --no-sync python -c \
  'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')
python_reference=$(jq -er \
  '.images[] | select(.name == "python-runtime") | "\(.image)@\(.digest)"' \
  deploy/images.lock.json)
node_reference=$(jq -er \
  '.tools[] | select(.id == "node") | .reference' \
  validation/tools/images.lock.json)

mkdir -p "${output}/python" "${output}/wheelhouse" "${output}/npm-cache"
uv build --offline --out-dir "${output}/python"
rm -f "${output}/python/.gitignore"
uv export \
  --frozen \
  --no-dev \
  --no-emit-project \
  --format requirements-txt \
  --output-file "${output}/runtime-requirements.txt"
docker pull "${python_reference}"
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --read-only \
  --tmpfs /tmp:size=64m,mode=1777 \
  --env HOME=/tmp/home \
  --volume "${output}/runtime-requirements.txt:/requirements.txt:ro" \
  --volume "${output}/wheelhouse:/wheelhouse" \
  "${python_reference}" \
  python -m pip download \
    --no-cache-dir \
    --require-hashes \
    --only-binary=:all: \
    --dest /wheelhouse \
    --requirement /requirements.txt
install -m 0644 \
  "${output}/python/morpheus_control_plane-${version}-py3-none-any.whl" \
  "${output}/wheelhouse/"
(
  cd "${output}/wheelhouse"
  find . -maxdepth 1 -type f ! -name SHA256SUMS -printf '%P\0' \
    | sort -z \
    | xargs -0 sha256sum >SHA256SUMS
)

work=$(mktemp -d)
cleanup() {
  rm -rf "${work}"
}
trap cleanup EXIT
git archive HEAD web | tar -x -C "${work}"
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --env HOME=/tmp/home \
  --volume "${work}/web:/work" \
  --volume "${output}/npm-cache:/npm-cache" \
  --workdir /work \
  "${node_reference}" \
  npm ci --ignore-scripts --cache /npm-cache
rm -rf "${output}/npm-cache/_logs"
rm -f "${output}/npm-cache/_update-notifier-last-checked"
(
  cd "${output}/npm-cache"
  find . -type f -printf '%P\0' \
    | sort -z \
    | xargs -0 sha256sum >"${output}/npm-cache.SHA256SUMS"
)

docker pull "${node_reference}"
python_image_id=$(docker image inspect --format '{{.Id}}' "${python_reference}")
node_image_id=$(docker image inspect --format '{{.Id}}' "${node_reference}")
jq -n \
  --arg source_commit "${source_commit}" \
  --argjson source_date_epoch "${source_date_epoch}" \
  --arg version "${version}" \
  --arg python_reference "${python_reference}" \
  --arg python_image_id "${python_image_id}" \
  --arg node_reference "${node_reference}" \
  --arg node_image_id "${node_image_id}" \
  --arg wheelhouse_sha256 "$(sha256sum "${output}/wheelhouse/SHA256SUMS" | cut -d' ' -f1)" \
  --arg runtime_requirements_sha256 "$(sha256sum "${output}/runtime-requirements.txt" | cut -d' ' -f1)" \
  --arg npm_cache_sha256 "$(sha256sum "${output}/npm-cache.SHA256SUMS" | cut -d' ' -f1)" \
  '{
    format: 1,
    source_commit: $source_commit,
    source_date_epoch: $source_date_epoch,
    version: $version,
    cache_scope: "portable-locked-dependencies-and-local-base-images",
    dependency_inputs: {
      wheelhouse_sha256: $wheelhouse_sha256,
      runtime_requirements_sha256: $runtime_requirements_sha256,
      npm_cache_sha256: $npm_cache_sha256
    },
    base_images: {
      python: {reference: $python_reference, id: $python_image_id},
      node: {reference: $node_reference, id: $node_image_id}
    }
  }' >"${output}/cache-manifest.json.tmp"
mv "${output}/cache-manifest.json.tmp" "${output}/cache-manifest.json"
(
  cd "${output}/python"
  sha256sum ./* >SHA256SUMS
)

echo "cache_manifest=${output}/cache-manifest.json"
