# Morpheus Inventory

This document records the assets that existed before the Morpheus specification
and the useful architectural ideas discovered during investigation. The product
specification and architecture documents are authoritative when this inventory
uses older terminology.

## What We Already Have

These are immediate Morpheus inputs because they are already tuned for our machine and workflow.

- `open-webui` front end
- `qwopus-coder` vLLM service
- The current vLLM launch configuration in `/mnt/data/AI/docker-compose.yml`
- Prefix caching enabled on the running vLLM service
- Chunked prefill enabled on the running vLLM service
- Async scheduling enabled on the running vLLM service
- FP8 KV cache on the running vLLM service
- MTP speculative decoding settings
- Qwen3 reasoning / tool-call parsing settings
- The `enable_thinking=false` chat template override
- The current benchmark and verification commands we already used
- The recent speed observations and log-based performance notes
- The current ports and runtime wiring for `open-webui` and `qwopus-coder`

## Ideas Learned From ODS

Use these as research input only. Morpheus implements its own code and integrates
third-party services from their upstream projects. It does not import ODS source,
images, runtime files, or installer behavior.

- Service layout discipline
- Clear split between core logic, adapters, tools, docs, and artifacts
- Compose overlay pattern for backend-specific runtime flags
- Healthcheck and startup-period discipline
- Environment-driven configuration
- Gateway pattern via LiteLLM if we want one stable API entrypoint
- Token and latency tracking via Token Spy
- GPU telemetry and status presentation patterns from the dashboard API
- Extension/module structure for reusable capabilities
- Operational docs structure:
  - setup
  - troubleshooting
  - validation
  - runtime contracts

## Suggested Morpheus Split

Use this as the default home for each class of work.

| Area | Put it in |
|---|---|
| Core orchestration logic | `src/morpheus/core/` |
| vLLM/Open WebUI/LiteLLM integration | `src/morpheus/adapters/` |
| Runtime agent and host inspection | `src/morpheus/agent/` |
| API and CLI | `src/morpheus/api/`, `src/morpheus/cli/` |
| Operational dashboard | `web/` |
| Deployment configuration | `deploy/` |
| Tests and fixtures | `tests/` |
| Runbooks and design notes | `docs/` |
| Generated benchmark output and captures | `artifacts/` |

## First Candidate Modules

- `src/morpheus/core/health.py`
- `src/morpheus/core/capabilities.py`
- `src/morpheus/ports/inference.py`
- `src/morpheus/adapters/inference/vllm.py`
- `src/morpheus/adapters/metrics/prometheus.py`
- `src/morpheus/agent/`
- `src/morpheus/api/`
- `src/morpheus/cli/`

The existing benchmark harness remains independently maintained at
`/home/batjp/Documents/qwopus-tool-tests`. Under the v0.2 plan, Morpheus imports
its published JSONL and reports through a versioned, checksummed mapping without
modifying the source files or pretending missing historical provenance exists.
New managed campaigns use Morpheus's canonical benchmark schema and can continue
to invoke validated Qwopus workload implementations behind an adapter.

## Recommendation

The v0.1 recommendation was to codify the existing working server before adding
dependencies. That work produced the deployed read-only status plane. The v0.2
next step is the dual-mode contract foundation followed by a module that can:

1. describe the current runtime config,
2. inspect the running service,
3. measure throughput,
4. snapshot logs into `artifacts/`.

The broader v0.2 workflow then adds normalized host discovery, catalog-backed
model/engine recommendations, durable benchmark history, managed deployment
plans, and operations views.
