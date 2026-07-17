#!/usr/bin/env bash
set -euo pipefail

umask 077
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
action=${1:-}
: "${CANDIDATE_MANIFEST:?set CANDIDATE_MANIFEST to the verified candidate manifest}"
: "${SECURITY_OUTPUT_ROOT:?set SECURITY_OUTPUT_ROOT below the repository artifacts directory}"
: "${TRIVY_CACHE_DIR:?set TRIVY_CACHE_DIR to a populated Trivy database cache}"

definition=${CANDIDATE_DEFINITION:-${root}/validation/candidate/artifact-set.json}
tool_lock=${SECURITY_TOOL_LOCK:-${root}/validation/tools/images.lock.json}
policy=${SECURITY_POLICY:-${root}/validation/security/policy.json}
finalizer=${root}/validation/security/finalize.py
candidate_manifest=$(realpath -- "${CANDIDATE_MANIFEST}")
candidate_root=$(dirname -- "${candidate_manifest}")
output=$(realpath -m -- "${SECURITY_OUTPUT_ROOT}")
cache=$(realpath -- "${TRIVY_CACHE_DIR}")

case "${output}" in
  "${root}/artifacts/"*) ;;
  *) echo "SECURITY_OUTPUT_ROOT must be below ${root}/artifacts/" >&2; exit 2 ;;
esac
for command in docker git jq realpath sha256sum tar uv; do
  command -v "${command}" >/dev/null || { echo "Missing required command: ${command}" >&2; exit 1; }
done
for path in "${candidate_manifest}" "${definition}" "${tool_lock}" "${policy}"; do
  [[ -f "${path}" && ! -L "${path}" ]] || { echo "Unsafe or missing input: ${path}" >&2; exit 2; }
done
metadata=${cache}/db/metadata.json
[[ -f "${metadata}" && ! -L "${metadata}" ]] || {
  echo "Trivy cache must contain regular db/metadata.json" >&2
  exit 2
}
[[ -f "${cache}/SHA256SUMS" && -f "${cache}/cache-manifest.json" ]] || {
  echo "Trivy cache inventory is incomplete" >&2
  exit 2
}
(
  cd "${cache}"
  sha256sum --check SHA256SUMS
)
test "$(sha256sum "${cache}/SHA256SUMS" | cut -d' ' -f1)" = \
  "$(jq -er '.inventory_sha256' "${cache}/cache-manifest.json")"
test "$(sha256sum "${metadata}" | cut -d' ' -f1)" = \
  "$(jq -er '.metadata_sha256' "${cache}/cache-manifest.json")"

python_args=(
  --output-root "${output}"
  --candidate-manifest "${candidate_manifest}"
  --candidate-definition "${definition}"
  --tool-lock "${tool_lock}"
  --policy "${policy}"
)
uv run --offline python "${finalizer}" preflight "${python_args[@]}"

if [[ "${action}" == finalize ]]; then
  : "${LICENSE_REVIEW_FILE:?set LICENSE_REVIEW_FILE to the completed review template}"
  [[ -d "${output}/reports" && ! -L "${output}" ]] || {
    echo "Security scan output is missing or unsafe" >&2
    exit 2
  }
  uv run --offline python "${finalizer}" finalize "${python_args[@]}" \
    --database-metadata "${output}/reports/trivy-db-metadata.json" \
    --license-review "${LICENSE_REVIEW_FILE}"
  exit 0
fi
if [[ "${action}" != scan ]]; then
  echo "usage: $0 {scan|finalize}" >&2
  exit 64
fi
if [[ -e "${output}" ]]; then
  echo "Security scan output already exists: ${output}" >&2
  exit 2
fi

mkdir -p -- "${output}/reports/scans" "${output}/reports/sbom"
cp -- "${metadata}" "${output}/reports/trivy-db-metadata.json"
scan_cache=$(mktemp -d /tmp/morpheus-security-trivy.XXXXXX)
worktree=$(mktemp -d /tmp/morpheus-security-worktree.XXXXXX)
cleanup() {
  rm -rf -- "${scan_cache}"
  rm -rf -- "${worktree}"
}
trap cleanup EXIT
cp -a -- "${cache}/." "${scan_cache}/"
git -C "${root}" ls-files -z --cached --others --exclude-standard \
  | tar --create --directory="${root}" --null --files-from=- \
  | tar --extract --directory="${worktree}"

tool_reference() {
  jq -er --arg id "$1" '.tools[] | select(.id == $id) | .reference' "${tool_lock}"
}
secret_ref=$(tool_reference secret-scan)
vulnerability_ref=$(tool_reference vulnerability-scan)
sbom_ref=$(tool_reference sbom)
license_ref=$(tool_reference license-scan)
for reference in "${secret_ref}" "${vulnerability_ref}" "${sbom_ref}" "${license_ref}"; do
  expected=${reference##*@}
  actual=$(docker image inspect --format '{{.Id}}' "${reference}")
  [[ "${actual}" == "${expected}" ]] || {
    echo "Cached scanner image does not match locked platform digest" >&2
    exit 2
  }
done

container_common=(
  --rm
  --network=none
  --read-only
  --cap-drop=ALL
  --security-opt=no-new-privileges:true
  --user "$(id -u):$(id -g)"
  --tmpfs /tmp:size=64m,mode=1777
  -e HOME=/tmp
)

gitleaks() {
  docker run "${container_common[@]}" \
    -v "${root}:/repo:ro" -v "${worktree}:/worktree:ro" \
    -v "${candidate_root}:/candidate:ro" -v "${output}:/output:rw" \
    "${secret_ref}" "$@"
}
gitleaks git /repo --config=/repo/.gitleaks.toml --log-opts=--all \
  --redact=100 --no-banner --no-color --timeout=600 \
  --report-format=json --report-path=/output/reports/scans/gitleaks-history.json
gitleaks dir /worktree --config=/repo/.gitleaks.toml --redact=100 --no-banner --no-color \
  --timeout=600 --max-archive-depth=3 \
  --report-format=json --report-path=/output/reports/scans/gitleaks-worktree.json
gitleaks dir /candidate --config=/repo/.gitleaks.toml --redact=100 --no-banner \
  --no-color --timeout=600 \
  --max-archive-depth=3 --report-format=json \
  --report-path=/output/reports/scans/gitleaks-candidate-artifacts.json

trivy_common=(
  --cache-dir=/cache
  --disable-telemetry
  --offline-scan
  --skip-db-update
  --skip-java-db-update
  --skip-check-update
  --skip-vex-repo-update
  --skip-version-check
  --no-progress
  --timeout=10m
  --format=json
)
trivy_run() {
  local reference=$1
  shift
  docker run "${container_common[@]}" \
    -v "${root}:/repo:ro" -v "${worktree}:/worktree:ro" \
    -v "${candidate_root}:/candidate:ro" \
    -v "${output}:/output:rw" -v "${scan_cache}:/cache:rw" \
    "${reference}" "$@"
}
trivy_security_fs() {
  local target=$1 report=$2
  shift 2
  trivy_run "${vulnerability_ref}" filesystem "${trivy_common[@]}" \
    --scanners=vuln,misconfig,secret --severity=HIGH,CRITICAL --exit-code=1 \
    --output="/output/reports/scans/${report}.json" "$@" "${target}"
}
trivy_license_fs() {
  local target=$1 report=$2
  shift 2
  trivy_run "${license_ref}" filesystem "${trivy_common[@]}" \
    --scanners=license --license-full --exit-code=0 \
    --output="/output/reports/scans/${report}.json" "$@" "${target}"
}
repository_skips=(
  --skip-dirs=/worktree/.venv
  --skip-dirs=/worktree/web/node_modules
)
trivy_security_fs /worktree repository-filesystem-security \
  --include-dev-deps "${repository_skips[@]}"
trivy_license_fs /worktree repository-filesystem-license \
  --include-dev-deps "${repository_skips[@]}"
trivy_security_fs /candidate candidate-artifacts-security
trivy_license_fs /candidate candidate-artifacts-license

for image_id in backend-oci dashboard-oci; do
  image_path=$(jq -er --arg id "${image_id}" '.artifacts[] | select(.id == $id) | .path' \
    "${candidate_manifest}")
  trivy_run "${vulnerability_ref}" image "${trivy_common[@]}" \
    --input="/candidate/${image_path}" --scanners=vuln,misconfig,secret \
    --severity=HIGH,CRITICAL --exit-code=1 \
    --output="/output/reports/scans/${image_id}-security.json"
  trivy_run "${license_ref}" image "${trivy_common[@]}" \
    --input="/candidate/${image_path}" --scanners=license --license-full --exit-code=0 \
    --output="/output/reports/scans/${image_id}-license.json"
done

while IFS=$'\t' read -r artifact_id artifact_path media_type; do
  [[ "${artifact_id}" =~ ^[a-z0-9][a-z0-9-]{0,63}$ ]] || {
    echo "Unsafe artifact ID in candidate manifest" >&2
    exit 2
  }
  source="file:/candidate/${artifact_path}"
  if [[ "${media_type}" == application/vnd.oci.image.layout.v1.tar ]]; then
    source="oci-archive:/candidate/${artifact_path}"
  fi
  docker run "${container_common[@]}" \
    -v "${candidate_root}:/candidate:ro" -v "${output}:/output:rw" \
    "${sbom_ref}" scan "${source}" --quiet \
    -o "cyclonedx-json=/output/reports/sbom/${artifact_id}.cdx.json" \
    -o "spdx-json=/output/reports/sbom/${artifact_id}.spdx.json"
done < <(jq -r '.artifacts[] | [.id, .path, .media_type] | @tsv' "${candidate_manifest}")

uv run --offline python "${finalizer}" review-template "${python_args[@]}"
echo "security_scan=complete license_review=pending"
