#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
work_dir=$(mktemp --directory --tmpdir morpheus-context.XXXXXXXX)
clean_context="${work_dir}/clean"
dirty_context="${work_dir}/dirty"
file_list="${work_dir}/files.zlist"
run_id="$(date -u +%Y%m%dT%H%M%SZ)-$$"
clean_tag="morpheus-context-clean:${run_id}"
dirty_tag="morpheus-context-dirty:${run_id}"
clean_container="morpheus-context-clean-${run_id}"
dirty_container="morpheus-context-dirty-${run_id}"

cleanup() {
  docker container rm --force "${clean_container}" "${dirty_container}" >/dev/null 2>&1 || true
  docker image rm --force "${clean_tag}" "${dirty_tag}" >/dev/null 2>&1 || true
  rm -rf -- "${work_dir}"
}
trap cleanup EXIT INT TERM

for command in docker git tar; do
  command -v "${command}" >/dev/null || {
    echo "Missing required command: ${command}" >&2
    exit 1
  }
done

mkdir -p "${clean_context}" "${dirty_context}"
git -C "${repo_root}" ls-files --cached --others --exclude-standard -z >"${file_list}"
tar -C "${repo_root}" --null --files-from "${file_list}" --create --file - \
  | tar -C "${clean_context}" --extract --file -
cp -a "${clean_context}/." "${dirty_context}/"

mkdir -p \
  "${dirty_context}/.git" \
  "${dirty_context}/secrets" \
  "${dirty_context}/artifacts" \
  "${dirty_context}/data" \
  "${dirty_context}/.venv/bin" \
  "${dirty_context}/.pytest_cache" \
  "${dirty_context}/dist" \
  "${dirty_context}/src/morpheus/__pycache__" \
  "${dirty_context}/web/node_modules" \
  "${dirty_context}/web/coverage"
printf 'ref: refs/heads/dirty\n' >"${dirty_context}/.git/HEAD"
printf 'MORPHEUS_API_KEY=dirty-canary\n' >"${dirty_context}/.env"
printf 'dirty-canary\n' >"${dirty_context}/secrets/token"
printf '{}\n' >"${dirty_context}/artifacts/result.json"
printf 'not-a-database\n' >"${dirty_context}/data/morpheus.sqlite3"
printf '#!/bin/false\n' >"${dirty_context}/.venv/bin/python"
printf 'dirty-cache\n' >"${dirty_context}/.pytest_cache/state"
printf 'dirty-wheel\n' >"${dirty_context}/dist/package.whl"
printf 'dirty-bytecode\n' >"${dirty_context}/src/morpheus/__pycache__/module.pyc"
printf 'dirty-module\n' >"${dirty_context}/web/node_modules/module.js"
printf 'dirty-coverage\n' >"${dirty_context}/web/coverage/index.html"
printf 'services: {}\n' >"${dirty_context}/compose.override.yaml"

docker build \
  --pull=false \
  --no-cache \
  --file "${clean_context}/validation/docker-context/Dockerfile" \
  --tag "${clean_tag}" \
  "${clean_context}" >/dev/null
docker build \
  --pull=false \
  --no-cache \
  --file "${dirty_context}/validation/docker-context/Dockerfile" \
  --tag "${dirty_tag}" \
  "${dirty_context}" >/dev/null

clean_id=$(docker image inspect --format '{{index .RootFS.Layers 0}}' "${clean_tag}")
dirty_id=$(docker image inspect --format '{{index .RootFS.Layers 0}}' "${dirty_tag}")
if ! [[ "${clean_id}" == "${dirty_id}" ]]; then
  echo "Docker contexts differ: clean=${clean_id} dirty=${dirty_id}" >&2
  mkdir -p "${work_dir}/clean-rootfs" "${work_dir}/dirty-rootfs"
  docker container create --name "${clean_container}" "${clean_tag}" /bin/true >/dev/null
  docker container create --name "${dirty_container}" "${dirty_tag}" /bin/true >/dev/null
  docker container export "${clean_container}" \
    | tar -C "${work_dir}/clean-rootfs" --extract --file -
  docker container export "${dirty_container}" \
    | tar -C "${work_dir}/dirty-rootfs" --extract --file -
  diff --recursive --brief "${work_dir}/clean-rootfs" "${work_dir}/dirty-rootfs" >&2 || true
  exit 1
fi

echo "LAB-002 context equivalence passed: ${clean_id}"
