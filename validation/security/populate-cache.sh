#!/usr/bin/env bash
set -euo pipefail

umask 077
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
: "${TRIVY_CACHE_OUTPUT:?set TRIVY_CACHE_OUTPUT below the repository artifacts directory}"
tool_lock=${SECURITY_TOOL_LOCK:-${root}/validation/tools/images.lock.json}
output=$(realpath -m -- "${TRIVY_CACHE_OUTPUT}")

case "${output}" in
  "${root}/artifacts/"*) ;;
  *) echo "TRIVY_CACHE_OUTPUT must be below ${root}/artifacts/" >&2; exit 2 ;;
esac
if [[ -e "${output}" ]]; then
  echo "Trivy cache output already exists: ${output}" >&2
  exit 2
fi
for command in date docker find git jq realpath sha256sum; do
  command -v "${command}" >/dev/null || { echo "Missing required command: ${command}" >&2; exit 1; }
done
[[ -f "${tool_lock}" && ! -L "${tool_lock}" ]] || {
  echo "Security tool lock is missing or unsafe" >&2
  exit 2
}

reference=$(jq -er '.tools[] | select(.id == "vulnerability-scan") | .reference' "${tool_lock}")
version=$(jq -er '.tools[] | select(.id == "vulnerability-scan") | .version' "${tool_lock}")
expected=${reference##*@}
actual=$(docker image inspect --format '{{.Id}}' "${reference}")
[[ "${actual}" == "${expected}" ]] || {
  echo "Cached Trivy image does not match the locked platform digest" >&2
  exit 2
}

mkdir -p -- "$(dirname -- "${output}")"
temporary=$(mktemp -d --tmpdir="$(dirname -- "${output}")" .trivy-cache.XXXXXX)
cleanup() {
  rm -rf -- "${temporary}"
}
trap cleanup EXIT

docker run --rm --read-only --cap-drop=ALL --security-opt=no-new-privileges:true \
  --user "$(id -u):$(id -g)" --tmpfs /tmp:size=256m,mode=1777 -e HOME=/tmp \
  -v "${temporary}:/cache:rw" "${reference}" image --cache-dir=/cache \
  --download-db-only --disable-telemetry --skip-version-check --no-progress

metadata=${temporary}/db/metadata.json
[[ -f "${metadata}" && ! -L "${metadata}" ]] || {
  echo "Trivy did not produce regular vulnerability database metadata" >&2
  exit 2
}
(
  cd "${temporary}"
  find . -type f ! -name SHA256SUMS ! -name cache-manifest.json -print0 \
    | LC_ALL=C sort -z \
    | xargs -0 sha256sum >SHA256SUMS
)
jq -n \
  --arg captured_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg source_commit "$(git -C "${root}" rev-parse HEAD)" \
  --arg tool_reference "${reference}" \
  --arg tool_version "${version}" \
  --arg tool_lock_sha256 "$(sha256sum "${tool_lock}" | cut -d' ' -f1)" \
  --arg inventory_sha256 "$(sha256sum "${temporary}/SHA256SUMS" | cut -d' ' -f1)" \
  --arg metadata_sha256 "$(sha256sum "${metadata}" | cut -d' ' -f1)" \
  '{
    format: 1,
    captured_at: $captured_at,
    source_commit: $source_commit,
    tool: {reference: $tool_reference, version: $tool_version},
    tool_lock_sha256: $tool_lock_sha256,
    inventory_sha256: $inventory_sha256,
    metadata_sha256: $metadata_sha256
  }' >"${temporary}/cache-manifest.json"
mv -- "${temporary}" "${output}"
trap - EXIT
echo "trivy_cache=${output}"
