#!/usr/bin/env bash
set -euo pipefail

umask 077
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
lock="${root}/validation/tools/images.lock.json"
artifact_root="${BROWSER_ARTIFACT_ROOT:-${root}/artifacts/browser-dev}"

case "$(realpath -m -- "${artifact_root}")" in
  "${root}/artifacts"/*) ;;
  *)
    echo "BROWSER_ARTIFACT_ROOT must be below the ignored repository artifacts directory." >&2
    exit 2
    ;;
esac

reference=$(jq -er '.tools[] | select(.id == "playwright") | .reference' "${lock}")
expected=$(jq -er '.tools[] | select(.id == "playwright") | .platform_digest' "${lock}")
actual=$(docker image inspect --format '{{.Id}}' "${reference}")
if [[ ${actual} != ${expected} ]]; then
  echo "Pinned Playwright image identity does not match the tool lock." >&2
  exit 2
fi

mkdir -p -- "${artifact_root}"
docker run --rm \
  --network none \
  --user "$(id -u):$(id -g)" \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --pids-limit 512 \
  --memory 2g \
  --shm-size 1g \
  --tmpfs /tmp:size=512m,mode=1777 \
  --tmpfs /work/node_modules/.vite:size=128m,mode=1777 \
  --tmpfs /work/node_modules/.vite-temp:size=32m,mode=1777 \
  --env HOME=/tmp/home \
  --env BROWSER_ARTIFACT_ROOT=/artifacts \
  --volume "${root}/web:/work:ro" \
  --volume "${root}/validation/browser/scan_evidence.py:/scan-evidence.py:ro" \
  --volume "${artifact_root}:/artifacts" \
  --workdir /work \
  "${reference}" \
  sh -lc 'npm run test:e2e && python3 /scan-evidence.py /artifacts'
