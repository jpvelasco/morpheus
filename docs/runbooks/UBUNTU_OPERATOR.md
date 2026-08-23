# ubuntu-1 Operator Runbook

Morpheus on ubuntu-1 is a **read-only operator control plane** beside the
existing inference stack. It answers: is inference usable, which model is
served, host GPU/disk when the agent is up, and what is blocked.

It does **not** install models, manage `coder-model`, manage Open WebUI, or
replace Docker for external services.

## Scope stop-line

The deployed v0.1 path stops when this runbook’s install and daily checks work;
do not use it as a v0.2 development target. Optional sidecars (search, voice,
n8n workflows, research, RAG, and image generation) remain outside the focused
v0.2 critical path unless reopened through change control.

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

## Search: documented Open WebUI query URL

When the search control is enabled, the existing Open WebUI can query the
Morpheus-owned SearXNG sidecar through exactly one documented URL
(SRCH-002). Configuration through the Open WebUI admin interface remains
operator-controlled; Morpheus never edits the Open WebUI database.

Documented query URL (JSON contract):

```
http://searxng:8080/search?q={query}&format=json
```

- `{query}` is the operator query, URL-encoded, 1-512 characters, no control
  characters
- the response must contain a `results` list; every result carries `title`,
  `url`, and `content` strings and `url` must be http(s)
- verification is enforced by `morpheus.core.search_contract`
  (`documented_query_url`, `verify_search_payload`) at every search call

## GPU resource policy

GPU acceleration for owned services is **opt-in** (VOICE-004): it stays
disabled unless `MORPHEUS_ENABLE_GPU_ACCELERATION=true` is set, and any GPU
use is rejected when it would violate the configured headroom policy:

- `MORPHEUS_GPU_HEADROOM_FREE_MIB` (default 4096) — free GPU memory that
  must remain after the requested use
- `MORPHEUS_GPU_MAX_TEMPERATURE_C` (default unset) — temperature ceiling;
  use is rejected above it when an observation is available

Enforcement is pure (`morpheus.core.gpu_policy.evaluate_gpu_use`); live
memory and temperature observations come from the host agent.

## Voice: documented Open WebUI contract

When the voice control is enabled, the voice gateway exposes an
OpenAI-compatible audio surface the existing Open WebUI can use (VOICE-003).
Documented endpoints (port 7420):

```
STT: http://127.0.0.1:7420/v1/audio/transcriptions   (multipart/form-data: file + model)
TTS: http://127.0.0.1:7420/v1/audio/speech           (application/json: model, input, voice, response_format, speed)
```

- STT model: `whisper-1`; accepted uploads: audio/wav, audio/mpeg, audio/webm,
  audio/ogg, audio/mp4, bounded by the configured upload limit
- TTS model: `kokoro`; documented voices: `af_heart`, `af_bella`, `af_nicole`,
  `af_aoede`, `am_michael`, `am_fenrir`, `bf_emma`, `bm_george`
- verification is enforced by `morpheus.core.voice_contract`
  (`documented_stt_url`, `documented_tts_url`, `verify_stt_payload`,
  `verify_speech_response`)

## Research: pinned Perplexica wiring

When the research control is enabled, Morpheus deploys a pinned Perplexica
service (digest-pinned, profile-gated, loopback port 7412, Morpheus-owned
`research_data` volume) wired to SearXNG and the configured
OpenAI-compatible model (RSCH-001):

```
[API_ENDPOINTS] SEARXNG = "http://search:8080"   OPENAI = "http://coder-model:8000/v1"
[MODEL]         NAME = <configured model id>
```

The wiring contract is enforced by `morpheus.core.research_deployment`
(`validated_research_deployment`, `render_perplexica_config`): the image
must be sha256-digest pinned, endpoints must be http(s) without credentials,
and the model id must be bounded.

Research requests always use the configured model ID and preserve the
server's no-thinking behavior (RSCH-002): the request builder
(`morpheus.core.research_routing.build_research_request`) pins the
configured model id, and `verify_research_request` rejects any request that
names a different model or asks for thinking.

## RAG: explicit need only

Qdrant or a separate embedding server is **not enabled by default** (RAG-001)
because Open WebUI already maintains local vector state. Enabling
`MORPHEUS_ENABLE_RAG` requires an explicit, operator-confirmed need; the
enablement policy (`morpheus.core.rag_policy.evaluate_rag_enablement`)
returns a typed denial otherwise, and the RAG capability stays disabled.

When RAG is enabled, vector and embedding data is owned by Morpheus and
never reads or mutates Open WebUI's database (RAG-002): every declared RAG
storage path is validated against the Morpheus-owned data root
(`morpheus.core.rag_ownership.validate_rag_storage`), and Open WebUI
database paths are rejected.

Ingestion and retrieval use documented service APIs and versioned
collection metadata (RAG-003): the documented Qdrant REST shape
(`morpheus.core.rag_contract.documented_ingest_url` /
`documented_search_url`, collection-scoped points endpoints) plus
schema-version-1 collection metadata; payload verification rejects
vectors without a matching collection schema version or embedding model
id, and retrieval must filter on the pinned version.

## Image generation: upstream integration with owned paths

Image generation integrates upstream ComfyUI through its documented API
(`POST /prompt`, `GET /history/{prompt_id}`, `GET /view`) and only with
Morpheus-owned models, input, output, and workflow paths (IMG-001):
`morpheus.core.image_paths.validate_owned_image_paths` requires every
ComfyUI root under the Morpheus data root, and
`verify_workflow_references` rejects any workflow path reference that is
absolute, parent-traversing, or null-byte.

Image generation start is blocked when configured free-memory,
temperature, process, or ownership checks fail (IMG-002):
`morpheus.core.image_gate.evaluate_image_start` combines the GPU headroom
policy (VOICE-004), the process-ownership observation, and the owned-paths
decision into one typed start decision with every blocker reported.

Any action that would stop or restart external inference is outside normal
Morpheus ownership (IMG-003): it requires an operator-run, separately
authorized transition workflow — `morpheus.core.transition_authority.
authorize_transition` only issues a `TransitionSession` when the operator
confirms in a separate session; normal operations are always denied with
the transition note.

The transition workflow records the verified pre-state and proves that
inference returned to the same image, model revision, arguments, and a
healthy endpoint afterward (IMG-004):
`morpheus.core.recovery_evidence.build_recovery_evidence` produces a
schema-version-1 evidence record listing every verified field; secret-shaped
argument values are rejected and never embedded.

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
