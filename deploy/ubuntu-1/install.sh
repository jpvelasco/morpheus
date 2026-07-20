#!/usr/bin/env bash
# Install Morpheus control plane for ubuntu-1 next to the existing inference stack.
# Never mutates history-coder, Open WebUI, or their Compose project.
set -euo pipefail

umask 077
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "${script_dir}/../.." && pwd)

usage() {
  cat <<'EOF' >&2
Usage:
  deploy/ubuntu-1/install.sh --runtime-root ABSOLUTE_DIR [--candidate-dir ABSOLUTE_DIR]

Loads candidate OCI images when --candidate-dir is given, writes a private
runtime environment, installs the host runtime agent from the candidate agent
bundle (or repo venv fallback), and starts API + dashboard on loopback.

Does not restart, reconfigure, or write to external inference / Open WebUI.
EOF
  exit 64
}

runtime_root=""
candidate_dir=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --runtime-root)
      runtime_root=${2:?}
      shift 2
      ;;
    --candidate-dir)
      candidate_dir=${2:?}
      shift 2
      ;;
    -h | --help) usage ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      ;;
  esac
done

if [[ -z ${runtime_root} || ${runtime_root} != /* ]]; then
  echo "--runtime-root must be an absolute path" >&2
  exit 2
fi
for command in docker openssl python3; do
  command -v "${command}" >/dev/null || {
    echo "Missing required command: ${command}" >&2
    exit 1
  }
done

mkdir -p -- "${runtime_root}"/{agent,data,run,logs}
chmod 700 "${runtime_root}" "${runtime_root}/data" "${runtime_root}/logs"
# Group-executable so the API container (group_add host GID) can open the agent socket.
chmod 750 "${runtime_root}/run"

env_file=${runtime_root}/morpheus.env
agent_env=${runtime_root}/agent.env
socket_dir=${runtime_root}/run
agent_home=${runtime_root}/agent/current

backend_image=${MORPHEUS_BACKEND_IMAGE:-}
dashboard_image=${MORPHEUS_DASHBOARD_IMAGE:-}

if [[ -n ${candidate_dir} ]]; then
  if [[ ${candidate_dir} != /* || ! -d ${candidate_dir} ]]; then
    echo "--candidate-dir must be an existing absolute directory" >&2
    exit 2
  fi
  manifest=${candidate_dir}/candidate-manifest.json
  if [[ ! -f ${manifest} ]]; then
    echo "candidate-manifest.json not found under ${candidate_dir}" >&2
    exit 2
  fi
  source_commit=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["source_commit"])' "${manifest}")
  short=${source_commit:0:12}
  version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["candidate_version"])' "${manifest}")
  backend_tar=${candidate_dir}/payload/images/morpheus-backend-${version}-${short}.oci.tar
  dashboard_tar=${candidate_dir}/payload/images/morpheus-dashboard-${version}-${short}.oci.tar
  agent_tar=${candidate_dir}/payload/agent/morpheus-agent-${version}-${short}.tar.gz
  for path in "${backend_tar}" "${dashboard_tar}" "${agent_tar}"; do
    [[ -f ${path} ]] || {
      echo "Missing candidate artifact: ${path}" >&2
      exit 2
    }
  done
  echo "Loading candidate images for ${source_commit}..."
  docker load -i "${backend_tar}"
  docker load -i "${dashboard_tar}"
  backend_image=morpheus/backend:${version}-${short}
  dashboard_image=morpheus/dashboard:${version}-${short}

  if [[ ! -x ${agent_home}/bin/morpheus-agent ]]; then
    echo "Installing host runtime agent..."
    work=$(mktemp -d --tmpdir="${runtime_root}" .agent-extract.XXXXXX)
    tar -xzf "${agent_tar}" -C "${work}"
    # Bundle layout: agent/{install.sh,wheelhouse,runtime-requirements.txt}
    bash "${work}/agent/install.sh" "${agent_home}"
    rm -rf -- "${work}"
  fi
fi

if [[ -z ${backend_image} || -z ${dashboard_image} ]]; then
  echo "Set MORPHEUS_BACKEND_IMAGE and MORPHEUS_DASHBOARD_IMAGE or pass --candidate-dir" >&2
  exit 2
fi

if [[ ! -f ${env_file} ]]; then
  api_key=$(openssl rand -hex 24)
  agent_key=$(openssl rand -hex 32)
  session=$(openssl rand -hex 32)
  gid=$(id -g)
  sed \
    -e "s|^MORPHEUS_API_KEY=.*|MORPHEUS_API_KEY=${api_key}|" \
    -e "s|^MORPHEUS_AGENT_KEY=.*|MORPHEUS_AGENT_KEY=${agent_key}|" \
    -e "s|^MORPHEUS_SESSION_SECRET=.*|MORPHEUS_SESSION_SECRET=${session}|" \
    -e "s|^MORPHEUS_BACKEND_IMAGE=.*|MORPHEUS_BACKEND_IMAGE=${backend_image}|" \
    -e "s|^MORPHEUS_DASHBOARD_IMAGE=.*|MORPHEUS_DASHBOARD_IMAGE=${dashboard_image}|" \
    -e "s|^MORPHEUS_AGENT_SOCKET_DIR=.*|MORPHEUS_AGENT_SOCKET_DIR=${socket_dir}|" \
    -e "s|^MORPHEUS_AGENT_GID=.*|MORPHEUS_AGENT_GID=${gid}|" \
    -e "s|^MORPHEUS_RUNTIME_AGENT_SOCKET=.*|MORPHEUS_RUNTIME_AGENT_SOCKET=${socket_dir}/agent.sock|" \
    "${script_dir}/env.example" >"${env_file}"
  chmod 600 "${env_file}"
  echo "Wrote ${env_file} (mode 0600). Record MORPHEUS_API_KEY somewhere safe."
else
  # Refresh image tags if candidate provided
  if [[ -n ${backend_image} ]]; then
    sed -i "s|^MORPHEUS_BACKEND_IMAGE=.*|MORPHEUS_BACKEND_IMAGE=${backend_image}|" "${env_file}"
    sed -i "s|^MORPHEUS_DASHBOARD_IMAGE=.*|MORPHEUS_DASHBOARD_IMAGE=${dashboard_image}|" "${env_file}"
  fi
fi

# Agent env: host data directory for host-side state; same secrets/keys.
{
  grep -v '^MORPHEUS_DATA_DIR=' "${env_file}" || true
  echo "MORPHEUS_DATA_DIR=${runtime_root}/data"
  echo "MORPHEUS_RUNTIME_AGENT_SOCKET=${socket_dir}/agent.sock"
  # Prefer socket; clear URL so agent binds the socket path.
  echo "MORPHEUS_RUNTIME_AGENT_URL="
} >"${agent_env}"
chmod 600 "${agent_env}"

# Compose env file must not force a host data path into containers.
if grep -q '^MORPHEUS_DATA_DIR=' "${env_file}"; then
  sed -i '/^MORPHEUS_DATA_DIR=/d' "${env_file}"
fi
if ! grep -q '^MORPHEUS_ENV_FILE=' "${env_file}"; then
  printf 'MORPHEUS_ENV_FILE=%s\n' "${env_file}" >>"${env_file}"
fi

export MORPHEUS_ENV_FILE=${env_file}
set -a
# shellcheck disable=SC1090
source "${env_file}"
set +a
export MORPHEUS_BACKEND_IMAGE=${backend_image}
export MORPHEUS_DASHBOARD_IMAGE=${dashboard_image}
export MORPHEUS_AGENT_SOCKET_DIR=${socket_dir}
export MORPHEUS_AGENT_GID=${MORPHEUS_AGENT_GID:-$(id -g)}

compose=(
  docker compose
  --project-name "${MORPHEUS_PROJECT_ID:-morpheus}"
  --env-file "${env_file}"
  -f "${repo_root}/deploy/compose.yaml"
  -f "${repo_root}/validation/candidate/compose.yaml"
  -f "${script_dir}/compose.yaml"
  -f "${repo_root}/deploy/compose.agent.yaml"
)

echo "Starting Morpheus API and dashboard (no-build, no-pull)..."
"${compose[@]}" up -d --no-build --pull never api dashboard

if [[ -x ${agent_home}/bin/morpheus-agent ]]; then
  # shellcheck disable=SC1090
  set -a
  source "${agent_env}"
  set +a
  export MORPHEUS_RUNTIME_AGENT_SOCKET=${socket_dir}/agent.sock
  export MORPHEUS_DATA_DIR=${runtime_root}/data
  if [[ -S ${socket_dir}/agent.sock ]]; then
    rm -f -- "${socket_dir}/agent.sock"
  fi
  nohup "${agent_home}/bin/morpheus-agent" \
    >"${runtime_root}/logs/agent.log" 2>&1 &
  echo $! >"${runtime_root}/run/agent.pid"
  echo "Runtime agent started (pid $(cat "${runtime_root}/run/agent.pid"))."
else
  echo "Warning: host agent binary not found; dashboard host metrics will be unavailable." >&2
fi

echo
echo "ubuntu-1 Morpheus install complete."
echo "  Runtime root: ${runtime_root}"
echo "  Dashboard:    http://127.0.0.1:${MORPHEUS_DASHBOARD_PORT:-7401}/"
echo "  API health:   http://127.0.0.1:${MORPHEUS_API_PORT:-7400}/healthz"
echo "  CLI (from repo venv or agent): morpheus status | models | doctor"
echo "  Env file:     ${env_file}"
echo
echo "External services (must remain untouched by Morpheus):"
echo "  history-coder, Open WebUI, network ${MORPHEUS_EXTERNAL_DOCKER_NETWORK:-ai_default}"
echo
echo "See docs/runbooks/ubuntu-operator.md for daily use and stop criteria."
