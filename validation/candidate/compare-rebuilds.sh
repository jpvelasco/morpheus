#!/usr/bin/env bash
set -euo pipefail

umask 077

if [[ $# -ne 3 ]]; then
  echo "Usage: $0 FIRST_REBUILD SECOND_REBUILD RESULT_JSON" >&2
  exit 64
fi

first=$(cd -- "$1" && pwd)
second=$(cd -- "$2" && pwd)
result=$3
if [[ -e "${result}" ]]; then
  echo "Comparison result already exists: ${result}" >&2
  exit 2
fi

for command in cmp cut jq sha256sum; do
  command -v "${command}" >/dev/null || {
    echo "Missing required command: ${command}" >&2
    exit 1
  }
done

for rebuild in "${first}" "${second}"; do
  test "$(jq -er '.format' "${rebuild}/offline-rebuild.json")" = 1
  (
    cd "${rebuild}"
    sha256sum --check SHA256SUMS
  )
done

for field in source_commit source_date_epoch version; do
  test "$(jq -er ".${field}" "${first}/offline-rebuild.json")" = \
    "$(jq -er ".${field}" "${second}/offline-rebuild.json")"
done
cmp "${first}/SHA256SUMS" "${second}/SHA256SUMS"

artifact_count=0
while IFS= read -r checksum; do
  digest=${checksum%% *}
  path=${checksum#*  }
  test "${path}" != "${checksum}"
  test -f "${first}/${path}"
  test -f "${second}/${path}"
  cmp "${first}/${path}" "${second}/${path}"
  test "$(sha256sum "${first}/${path}" | cut -d' ' -f1)" = "${digest}"
  artifact_count=$((artifact_count + 1))
done <"${first}/SHA256SUMS"
test "${artifact_count}" -eq 5

mkdir -p "$(dirname -- "${result}")"
jq -n \
  --arg source_commit "$(jq -er '.source_commit' "${first}/offline-rebuild.json")" \
  --arg version "$(jq -er '.version' "${first}/offline-rebuild.json")" \
  --argjson source_date_epoch \
    "$(jq -er '.source_date_epoch' "${first}/offline-rebuild.json")" \
  --argjson artifact_count "${artifact_count}" \
  --slurpfile artifacts <(
    jq -Rn \
      '[inputs | capture("^(?<sha256>[0-9a-f]{64})  (?<path>.+)$")]' \
      <"${first}/SHA256SUMS"
  ) \
  '{
    format: 1,
    status: "pass",
    comparison: "byte-for-byte",
    source_commit: $source_commit,
    source_date_epoch: $source_date_epoch,
    version: $version,
    artifact_count: $artifact_count,
    artifacts: $artifacts[0]
  }' >"${result}.tmp"
mv "${result}.tmp" "${result}"

echo "comparison=${result}"
