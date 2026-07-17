#!/usr/bin/env bash
set -euo pipefail

umask 077
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
confirmation=${SOAK_CONFIRM_DURATION:?SOAK_CONFIRM_DURATION must be exactly 24h}
manifest=${CANDIDATE_MANIFEST:?CANDIDATE_MANIFEST must identify the exact candidate}
network=${LOAD_NETWORK:?LOAD_NETWORK must identify the candidate internal network}
project=${LOAD_PROJECT_ID:?LOAD_PROJECT_ID must identify the candidate project}
key_file=${LOAD_API_KEY_FILE:?LOAD_API_KEY_FILE must identify a private synthetic key file}
artifact_root=${LOAD_ARTIFACT_ROOT:?LOAD_ARTIFACT_ROOT must identify the release evidence directory}
resource_monitor_pid=""
load_pid=""

cleanup() {
  if [[ -n ${load_pid} ]] && kill -0 "${load_pid}" 2>/dev/null; then
    kill "${load_pid}"
    wait "${load_pid}" || true
  fi
  if [[ -n ${resource_monitor_pid} ]] && kill -0 "${resource_monitor_pid}" 2>/dev/null; then
    kill "${resource_monitor_pid}"
    wait "${resource_monitor_pid}" || true
  fi
}
trap cleanup EXIT

if [[ ${confirmation} != 24h ]]; then
  echo "The release soak requires an exact SOAK_CONFIRM_DURATION=24h confirmation." >&2
  exit 2
fi
if [[ $(jq -er '.profiles.soak.measurement_duration' "${root}/validation/load/workload.json") != 24h ]]; then
  echo "The checked-in soak workload is not exactly 24 hours." >&2
  exit 2
fi

uv run --python 3.12 python "${root}/validation/load/verify_candidate.py" \
  --manifest "${manifest}" \
  --output "${artifact_root}/candidate-verification.json"
source_commit=$(jq -er '.source_commit' "${artifact_root}/candidate-verification.json")
release_version=$(jq -er '.candidate_version' "${artifact_root}/candidate-verification.json")
max_memory_growth=$(jq -er '.abort_limits.max_memory_growth_bytes' "${root}/validation/load/workload.json")
max_pid_growth=$(jq -er '.abort_limits.max_pid_growth' "${root}/validation/load/workload.json")

uv run --python 3.12 python "${root}/validation/load/resource_snapshot.py" \
  --project "${project}" \
  --source-commit "${source_commit}" \
  --release-version "${release_version}" \
  --component api \
  --component dashboard \
  --phase active \
  --samples 1 \
  --interval-seconds 0 \
  --output "${artifact_root}/resources-start.json"

uv run --python 3.12 python "${root}/validation/load/resource_snapshot.py" \
  --project "${project}" \
  --source-commit "${source_commit}" \
  --release-version "${release_version}" \
  --component api \
  --component dashboard \
  --phase active \
  --samples 2885 \
  --interval-seconds 30 \
  --max-memory-growth-bytes "${max_memory_growth}" \
  --max-pid-growth "${max_pid_growth}" \
  --output "${artifact_root}/resources-soak.json" &
resource_monitor_pid=$!

LOAD_PHASE=proxied \
WORKLOAD_PROFILE=soak \
LOAD_NETWORK="${network}" \
LOAD_PROJECT_ID="${project}" \
LOAD_API_KEY_FILE="${key_file}" \
LOAD_ARTIFACT_ROOT="${artifact_root}" \
  "${root}/validation/load/run.sh" &
load_pid=$!

completed_pid=""
if wait -n -p completed_pid "${resource_monitor_pid}" "${load_pid}"; then
  :
else
  status=$?
  if [[ ${completed_pid} == "${resource_monitor_pid}" ]]; then
    echo "The resource monitor failed before the soak workload completed." >&2
  else
    echo "The soak workload failed before resource monitoring completed." >&2
  fi
  exit "${status}"
fi

if [[ ${completed_pid} == "${resource_monitor_pid}" ]]; then
  echo "The resource monitor ended before the soak workload completed." >&2
  exit 1
fi

load_pid=""

wait "${resource_monitor_pid}"
resource_monitor_pid=""
jq -e '.status == "pass"' "${artifact_root}/resources-start.json" >/dev/null
jq -e '.status == "pass"' "${artifact_root}/resources-soak.json" >/dev/null
jq -e '.phase == "proxied" and .workload_profile == "soak"' \
  "${artifact_root}/proxied.json" >/dev/null
printf '%s\n' 'soak_24h=passed'
