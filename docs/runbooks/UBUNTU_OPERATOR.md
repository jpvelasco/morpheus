# ubuntu-1 Operator Runbook

Morpheus on ubuntu-1 is a **read-only operator control plane** beside the
existing inference stack. It answers: is inference usable, which model is
served, host GPU/disk when the agent is up, and what is blocked.

It does **not** install models, manage `coder-model`, manage Open WebUI, or
replace Docker for external services.

## Scope stop-line

Product work for ubuntu-1 stops when this runbook’s install path works and daily
checks use Morpheus instead of ad-hoc scripts. Optional sidecars (search, voice,
workflows, research, image generation) are out of scope unless reopened later.

## Never do

- Restart, recreate, stop, or reconfigure `coder-model` or Open WebUI via Morpheus
- Enable lifecycle purge on production data without a disposable lab
- Point lifecycle compose at the external inference project as if Morpheus owned it
- Commit `morpheus.env`, API keys, or agent keys

## Prerequisites

- Docker Engine + Compose on ubuntu-1
- Existing shared network (default `ai_default`) with `coder-model`
- Candidate artifacts under `artifacts/candidate-aa7174a/candidate/` **or**
  already-loaded image tags
- CPython 3.12 available as `python3` (or `MORPHEUS_AGENT_PYTHON`) for agent install

## Install (once)

From the repository root, as the operator user (docker group required):

```bash
# Prefer the frozen candidate tree
deploy/ubuntu-1/install.sh \
  --runtime-root /home/operator/morpheus-runtime \
  --candidate-dir "$PWD/artifacts/candidate-aa7174a/candidate"
```

What it does:

1. `docker load` backend/dashboard OCI images from the candidate
2. Installs the offline host agent under the runtime root
3. Writes mode-`0600` `morpheus.env` + `agent.env` (secrets generated once)
4. Starts **API + dashboard** with `--no-build --pull never`
5. Starts the host **runtime agent** with a Unix socket for host metrics

Record `MORPHEUS_API_KEY` from the generated env file for dashboard sign-in.

### Verify

```bash
curl -sS http://127.0.0.1:7400/healthz
# open http://127.0.0.1:7401/ and sign in with the API key

# From a venv that has the Morpheus CLI, or the agent venv:
export $(grep -v '^#' /home/operator/morpheus-runtime/morpheus.env | xargs -d '\n')
morpheus status
morpheus models
morpheus doctor
```

Expect inference readiness against the live vLLM endpoint configured as
`MORPHEUS_LLM_BASE_URL` (default `http://coder-model:8000/v1` on `ai_default`).

GPU, storage, and host diagnostics need the **runtime agent socket**. The
install script sets `run/` to mode `0750` so the API container can open the
socket. If the dashboard shows those as unavailable:

```bash
chmod 750 /home/operator/morpheus-runtime/run
# refresh the dashboard
```

Confirm the agent is running: `kill -0 "$(cat /home/operator/morpheus-runtime/run/agent.pid)"`.

## Daily use

| Goal | Command / UI |
|---|---|
| Is inference ready? | Dashboard **Overview**, or `morpheus status` |
| Which model? | Overview metric, or `morpheus models` |
| Why degraded? | Dashboard **Diagnostics**, or `morpheus doctor` |
| GPU / disk | Overview host panel (agent required) |
| Refresh | Dashboard refresh control |

Keep using Docker / existing tools for:

- restarting or tuning `coder-model`
- Open WebUI admin and chat
- deep log dives on external containers

## Stop / start Morpheus only

```bash
RUNTIME=/home/operator/morpheus-runtime
export $(grep -v '^#' "$RUNTIME/morpheus.env" | xargs -d '\n')

docker compose \
  --project-name "${MORPHEUS_PROJECT_ID:-morpheus}" \
  --env-file "$RUNTIME/morpheus.env" \
  -f deploy/compose.yaml \
  -f validation/candidate/compose.yaml \
  -f deploy/ubuntu-1/compose.yaml \
  -f deploy/compose.agent.yaml \
  stop

# Agent
if [[ -f $RUNTIME/run/agent.pid ]]; then
  kill "$(cat "$RUNTIME/run/agent.pid")" || true
fi
```

Start again with the same `install.sh` (idempotent image load) or `compose up`
for API/dashboard plus the agent command shown in install output.

## Uninstall Morpheus (preserve external stack)

```bash
# Stop and remove only the Morpheus Compose project
docker compose --project-name morpheus \
  --env-file /home/operator/morpheus-runtime/morpheus.env \
  -f deploy/compose.yaml \
  -f validation/candidate/compose.yaml \
  -f deploy/ubuntu-1/compose.yaml \
  -f deploy/compose.agent.yaml \
  down

# Optional: remove Morpheus volumes (Morpheus data only)
# docker volume ls | grep morpheus

# Stop agent; remove runtime root only if you accept losing local Morpheus state
```

Confirm `coder-model` and Open WebUI still run and were not recreated.

## Live read-only checks (optional)

```bash
export MORPHEUS_LIVE_TESTS=1
export MORPHEUS_LIVE_ALLOWED_HOSTS=127.0.0.1
export MORPHEUS_LIVE_VLLM_URL=http://127.0.0.1:8082/v1
export MORPHEUS_LIVE_VLLM_METRICS_URL=http://127.0.0.1:8082/metrics
export MORPHEUS_LIVE_TIMEOUT_SECONDS=5
make test-live-readonly
```

This never sends completions and never mutates the external service.

## What “done” means

ubuntu-1 operator stop-line is met when:

1. Morpheus is installed via `deploy/ubuntu-1/install.sh`
2. Dashboard + CLI show live model/health for the existing vLLM
3. Host metrics appear when the agent is running
4. External inference and Open WebUI identity stay unchanged across Morpheus ops
5. No further feature work is required for daily operator understanding

Further product work is optional and should wait for a concrete ubuntu-1 need.
