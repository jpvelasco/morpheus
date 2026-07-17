#!/usr/bin/env bash
set -euo pipefail

umask 077
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
compose_file="${root}/validation/load/compose.yaml"
project=morpheus-load-dev
network="${project}_load_internal"
artifact_root="${LOAD_ARTIFACT_ROOT:-${root}/artifacts/load-dev}"
upstream_key=""
proxy_key=""
stack_started=0

cleanup() {
  if (( stack_started )); then
    MORPHEUS_LOAD_PROJECT="${project}" docker compose --project-name "${project}" \
      --file "${compose_file}" down --volumes --rmi local --remove-orphans
  fi
  if [[ -n ${upstream_key} ]]; then rm -f -- "${upstream_key}"; fi
  if [[ -n ${proxy_key} ]]; then rm -f -- "${proxy_key}"; fi
}
trap cleanup EXIT

existing_containers=$(docker ps -a --quiet --filter "label=io.morpheus.project=${project}")
existing_networks=$(docker network ls --quiet --filter "label=io.morpheus.project=${project}")
existing_volumes=$(docker volume ls --quiet --filter "label=io.morpheus.project=${project}")
if [[ -n ${existing_containers}${existing_networks}${existing_volumes} ]]; then
  echo "Refusing to reuse existing disposable load resources." >&2
  exit 2
fi

case "$(realpath -m -- "${artifact_root}")" in
  "${root}/artifacts"/*) ;;
  *)
    echo "LOAD_ARTIFACT_ROOT must be below repository artifacts." >&2
    exit 2
    ;;
esac
mkdir -p -- "${artifact_root}"
upstream_key=$(mktemp --tmpdir morpheus-load-upstream.XXXXXX)
proxy_key=$(mktemp --tmpdir morpheus-load-proxy.XXXXXX)
chmod 600 -- "${upstream_key}" "${proxy_key}"
printf '%s\n' 'morpheus-load-upstream-key' >"${upstream_key}"
printf '%s\n' 'morpheus-load-proxy-key' >"${proxy_key}"

stack_started=1
MORPHEUS_LOAD_PROJECT="${project}" docker compose --project-name "${project}" \
  --file "${compose_file}" up --detach --build --wait

LOAD_PHASE=direct \
WORKLOAD_PROFILE=dev \
LOAD_NETWORK="${network}" \
LOAD_PROJECT_ID="${project}" \
LOAD_API_KEY_FILE="${upstream_key}" \
LOAD_ARTIFACT_ROOT="${artifact_root}" \
  "${root}/validation/load/run.sh"

LOAD_PHASE=proxied \
WORKLOAD_PROFILE=dev \
LOAD_NETWORK="${network}" \
LOAD_PROJECT_ID="${project}" \
LOAD_API_KEY_FILE="${proxy_key}" \
LOAD_ARTIFACT_ROOT="${artifact_root}" \
  "${root}/validation/load/run.sh"

uv run --python 3.12 python "${root}/validation/load/summarize.py" \
  --direct "${artifact_root}/direct.json" \
  --proxied "${artifact_root}/proxied.json" \
  --output "${artifact_root}/comparison.json"

uv run --python 3.12 python "${root}/validation/load/resource_snapshot.py" \
  --project "${project}" \
  --component api \
  --component dashboard \
  --phase idle \
  --samples 3 \
  --interval-seconds 1 \
  --output "${artifact_root}/resources-idle.json"

jq -e '.status == "pass"' "${artifact_root}/comparison.json" >/dev/null
jq -e '.status == "pass"' "${artifact_root}/resources-idle.json" >/dev/null
printf '%s\n' 'load_dev_rehearsal=passed'
