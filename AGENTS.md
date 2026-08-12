# AGENTS.md

## Where We Left Off (2026-08-11)

**Product direction reopened for v0.2 planning.** Morpheus is now planned as a
focused developer-inference appliance with stable native paths on Ubuntu,
Windows, and Apple Silicon macOS. ubuntu-1 and ubuntu-2 remain named Linux
qualification machines. The plan adds evidence-ranked model/engine selection,
managed runtime, benchmark history, Tauri desktop plus independent backend,
operations, and bounded AI-assisted diagnosis. Read
`docs/IMPLEMENTATION_PLAN.md` Phase 11 onward and ADR-0005 through ADR-0008.

This plan update does not authorize v0.2 runtime implementation or live target
mutation. The next source milestone is Phase 11 contracts and ownership only
when explicitly requested. Search, voice, workflows, research, RAG, image
generation, and other ODS-like breadth are outside the focused v0.2 critical
path unless separately reopened.

The deployed v0.1 Morpheus remains a **read-only operator surface** next to
existing inference. It answers: is inference up, which model, GPU/disk via the
agent, and basic diagnostics. It is **not** chat, model management, or vLLM
control. Planning language must not be mistaken for deployed behavior.

### Live install (ubuntu-1)

| Item | Value |
|---|---|
| Runtime root | `/home/operator/morpheus-runtime` |
| Dashboard | `http://127.0.0.1:7401/` (loopback only; use SSH tunnel off-box) |
| API | `http://127.0.0.1:7400/` |
| Env / API key | `/home/operator/morpheus-runtime/morpheus.env` (mode 0600) |
| Host agent | `/home/operator/morpheus-runtime/agent/current`, socket under `run/` |
| Install path | `deploy/ubuntu-1/install.sh` + `docs/runbooks/ubuntu-operator.md` |
| Candidate | rewritten source `fa5fe3ca2e393d6d20c1afa89dff2452650bf180`; deployed artifacts retain legacy build ID `aa7174aff3194ffeb1ca455d53005f242abe6d82` under `artifacts/candidate-aa7174a/` |

Agent socket directory must be mode `0750` so the API container (host GID) can
reach `agent.sock`. If GPU/storage show unavailable: `chmod 750 …/run` and
confirm the agent PID is alive.

Daily CLI (after sourcing env or using agent venv):

```bash
/home/operator/morpheus-runtime/agent/current/bin/morpheus status
/home/operator/morpheus-runtime/agent/current/bin/morpheus models
/home/operator/morpheus-runtime/agent/current/bin/morpheus doctor
```

### Resume ledger

Read `docs/RELEASE_STATE.md` for candidate evidence and milestone status. The
v0.1 ubuntu-1 install remains the operational baseline; the active product queue
starts with the unimplemented v0.2 Phase 11 contract milestone.

## Project Boundary

Morpheus is an independent project. Do not import, vendor, symlink, or depend
on ODS source code. ODS may be consulted for ideas and upstream project names,
but Morpheus implementations and contracts must be written for this system.

The active `history-coder` vLLM service, existing Open WebUI container, their
Compose project, model caches, and persistent data are externally owned. Never
restart, recreate, stop, reconfigure, or write to them unless the user gives an
explicit state-changing instruction in the current request.

In v0.2 terms, that stack is `external_observed`. Future managed inference must
use separate Morpheus-owned roots, labels, manifests, and endpoints. Do not
adopt the existing stack merely because it is discoverable or appears in a
recommendation.

## Engineering Rules

- Follow `docs/PRODUCT_SPECIFICATION.md`, `docs/ARCHITECTURE.md`, and
  `docs/IMPLEMENTATION_PLAN.md` when product work is authorized.
- Prefer `docs/runbooks/ubuntu-operator.md` for host operator install/use.
- Use TDD: failing requirement test, minimal implementation, refactor.
- Keep core domain logic pure and dependency-free.
- Put external behavior behind typed adapter protocols.
- Use structured parsers for JSON, YAML, metrics, and Compose data.
- Do not expose secrets or retrieve secret values for diagnostics.
- Do not weaken tests, security controls, or type checks to make a build pass.
- Add concise comments only for non-obvious decisions.
- Keep generated output under ignored `artifacts/`.

## Validation

Run the smallest relevant test lane while iterating, then the complete required
gate for the affected phase. Live-system tests are opt-in and read-only unless
the user explicitly authorizes mutation.

Do not treat remaining formal release checklist items (24h soak, full browser
matrix, dual-VM rebuilds, optional sidecars) as open mandatory work unless the
user asks.
