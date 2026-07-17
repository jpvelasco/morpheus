#!/usr/bin/env bash
set -euo pipefail

umask 077
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
lock="${root}/validation/tools/images.lock.json"
phase=${LOAD_PHASE:?LOAD_PHASE must be direct or proxied}
profile=${WORKLOAD_PROFILE:-dev}
network=${LOAD_NETWORK:?LOAD_NETWORK must name the disposable internal network}
project=${LOAD_PROJECT_ID:?LOAD_PROJECT_ID must name the disposable Morpheus project}
key_file=${LOAD_API_KEY_FILE:?LOAD_API_KEY_FILE must name a private synthetic credential file}
artifact_root=${LOAD_ARTIFACT_ROOT:-${root}/artifacts/load-dev}
docker_pid=""

if [[ ${phase} != direct && ${phase} != proxied ]]; then
  echo "LOAD_PHASE must be direct or proxied." >&2
  exit 2
fi
if [[ ${profile} != dev && ${profile} != qualification && ${profile} != soak ]]; then
  echo "WORKLOAD_PROFILE must be dev, qualification, or soak." >&2
  exit 2
fi
if [[ ! ${network} =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ ]]; then
  echo "LOAD_NETWORK is invalid." >&2
  exit 2
fi
if [[ ! ${project} =~ ^[a-z][a-z0-9_-]{1,62}$ ]]; then
  echo "LOAD_PROJECT_ID is invalid." >&2
  exit 2
fi
if [[ -L ${key_file} || ! -f ${key_file} ]]; then
  echo "LOAD_API_KEY_FILE must be a regular non-symlink file." >&2
  exit 2
fi
key_mode=$(stat -c '%a' -- "${key_file}")
if (( (8#${key_mode} & 077) != 0 )); then
  echo "LOAD_API_KEY_FILE must not be accessible by group or other." >&2
  exit 2
fi

artifact_root=$(realpath -m -- "${artifact_root}")
case "${artifact_root}" in
  "${root}/artifacts"/*) ;;
  *)
    echo "LOAD_ARTIFACT_ROOT must be below the ignored repository artifacts directory." >&2
    exit 2
    ;;
esac

runner_token="${BASHPID}-$(date -u +%Y%m%dT%H%M%SZ)"
runner_name="${project}-load-${phase}-${BASHPID}"
cidfile="${artifact_root}/.${runner_name}.cid"

cleanup() {
  if [[ -n ${docker_pid} ]] && kill -0 "${docker_pid}" 2>/dev/null; then
    kill "${docker_pid}"
    wait "${docker_pid}" || true
  fi

  container_document=""
  if container_document=$(
    docker container inspect --format '{{json .}}' -- "${runner_name}" 2>/dev/null
  ) && jq -e \
    --arg name "/${runner_name}" \
    --arg project "${project}" \
    --arg token "${runner_token}" \
    '.Name == $name
      and .Config.Labels["io.morpheus.project"] == $project
      and .Config.Labels["io.morpheus.component"] == "load-runner"
      and .Config.Labels["io.morpheus.run-token"] == $token' \
    <<<"${container_document}" >/dev/null; then
    docker stop --time 10 -- "${runner_name}" >/dev/null || true
  fi
  rm -f -- "${cidfile}"
}
trap cleanup EXIT

network_document=$(docker network inspect --format '{{json .}}' -- "${network}")
jq -e --arg project "${project}" \
  '.Internal == true and ((.Labels // {}) | .["io.morpheus.project"] == $project)' \
  <<<"${network_document}" >/dev/null || {
    echo "LOAD_NETWORK must be internal and carry the exact disposable project label." >&2
    exit 2
  }

reference=$(jq -er '.tools[] | select(.id == "load-test") | .reference' "${lock}")
expected=$(jq -er '.tools[] | select(.id == "load-test") | .platform_digest' "${lock}")
actual=$(docker image inspect --format '{{.Id}}' "${reference}")
if [[ ${actual} != ${expected} ]]; then
  echo "Pinned load-test image identity does not match the tool lock." >&2
  exit 2
fi

mkdir -p -- "${artifact_root}"
docker run --rm \
  --name "${runner_name}" \
  --cidfile "${cidfile}" \
  --label "io.morpheus.project=${project}" \
  --label "io.morpheus.component=load-runner" \
  --label "io.morpheus.run-token=${runner_token}" \
  --network "${network}" \
  --user "$(id -u):$(id -g)" \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --pids-limit 256 \
  --memory 256m \
  --tmpfs /tmp:size=64m,mode=1777 \
  --env LOAD_PHASE="${phase}" \
  --env WORKLOAD_PROFILE="${profile}" \
  --env SUMMARY_PATH="/artifacts/${phase}.json" \
  --volume "${root}/validation/load:/scripts:ro" \
  --volume "$(realpath -- "${key_file}"):/run/secrets/load-api-key:ro" \
  --volume "${artifact_root}:/artifacts" \
  "${reference}" \
  run --quiet /scripts/workload.js &
docker_pid=$!
wait "${docker_pid}"
docker_pid=""
