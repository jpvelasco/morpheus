# AGENTS.md

## Where We Left Off (2026-08-23)

Current `main`: `11f8fdccc50228026fdd606c21d7ed901d1b7770`. Rectification is in
progress; the v0.2 product is **not** source-complete or release-ready.

- Landed: **R0** truthful ledgers + semantic traceability (#67), **R1** one
  canonical identity and plan family (#68, closes #55).
- Next package: **R2** evidence-backed recommendation (#56), then **R3** durable
  managed operation service (#57). One integrator owns R2 and R3.
- Do not resume the old Phase 11-to-18 implementation prompt or jump directly to
  physical qualification (R10).

`requirements.json` stands at 59 implemented, 28 planned, 12 deferred, 0
validated. Component scaffolds do not establish product behavior. Still open:

- managed operation routes use a deliberately non-mutating DEV executor;
- recommendation bypasses retained catalogs and benchmark evidence;
- metrics are collected on page requests and events have no producers;
- native engine shutdown bypasses process-tree supervision;
- desktop/native package and local diagnosis paths remain incomplete;
- model console / setup copilot are planned only; optional search/voice/RAG/etc.
  stay deferred.

Read before working: `docs/RELEASE_STATE.md` (current state),
`docs/RECTIFICATION_PLAN.md` (execution order and gates), `requirements.json`,
then `docs/PRODUCT_SPECIFICATION.md` / `docs/ARCHITECTURE.md` /
`docs/IMPLEMENTATION_PLAN.md`. Historical detail:
`docs/IMPLEMENTATION_AUDIT_2026-08-15.md`.

Deployed v0.1 remains a **read-only operator surface** next to the existing
inference stack (up/down, served model, GPU/disk via agent, diagnostics). It is
not chat, model management, or vLLM control. Never present plans/scaffolds as
deployed behavior.

### R1 Canonical Identity Rules (do not regress)

- The ONLY semantic `DeploymentPlan`, `ModelIdentity`, and `WorkloadProfile`
  live in `core/records.py`.
  `tests/contract/test_r1_identity_architecture.py` enforces this by AST scan;
  adding a second class with those names anywhere under `src/` fails CI.
- Renamed read/query DTOs: `core/models.py:ServedModel` (live serving identity),
  `core/workload.py:WorkloadPolicy` (ranking policy). Do not rename back.
- The retired lean plan family (`ManagedCandidate`, derived sha256 `plan_id`) is
  gone. `core/deployment.py:migrate_snapshot` rejects v1 snapshot documents as
  lossy (`LossyMigrationError`) — never reinterpret them.
- Content-derived IDs exclude observation timestamps. Recommendation records are
  schema v2 (`created_at` = provenance only); campaign `run_id` is a required
  caller-declared argument. Never derive IDs from wall-clock time.
- Repositories: protocols in `core/repositories.py`, owned-path adapter in
  `adapters/persistence/records_store.py`; `core/deployment.py:DeploymentStore`
  stays the promotion/rollback engine over canonical plans.
- `ops/planning.py:PlanningService` owns selection → promote → rollback identity
  enforcement. State-changing calls reject missing, observed (`external_observed`),
  or mismatched plan/ownership identity BEFORE mutating. API surface:
  `/api/v1/plans/*`. Audit rows carry `plan_id`/`ownership` (sqlite schema v4).
- The VSLICE fixture (`validation/vslice/harness.py`) selects through the
  production `PlanningService` — keep it that way.

### Continuation and Authorization

Implementation requires explicit authorization. When granted, agents may continue
across green DEV and disposable-lab packages in `RECTIFICATION_PLAN.md` order
without asking at every boundary. HOST-RO and HOST-MAINT lanes always require
explicit current authorization. Release publication and signing credentials stay
separately authorized; missing signatures never block source/packaging work.

The repository declares `Proprietary - no license granted`. Do not change
licensing metadata or claim Morpheus is open source until the user chooses the
license and publication policy.

### Live Install (ubuntu-1)

| Item | Value |
|---|---|
| Runtime root | `/home/operator/morpheus-runtime` |
| Dashboard | `http://127.0.0.1:7401/` (loopback only; SSH tunnel off-box) |
| API | `http://127.0.0.1:7400/` |
| Env / API key | `/home/operator/morpheus-runtime/morpheus.env` (mode `0600`) |
| Host agent | `/home/operator/morpheus-runtime/agent/current`, socket under `run/` |
| Install path | `deploy/ubuntu-1/install.sh` and `docs/runbooks/UBUNTU_OPERATOR.md` |

Agent socket directory must be mode `0750` so the API container can reach
`agent.sock`. If GPU/storage looks unavailable, check that mode first and confirm
the agent PID is alive.

Daily CLI (after sourcing the env or using the agent venv):

```bash
/home/operator/morpheus-runtime/agent/current/bin/morpheus status
/home/operator/morpheus-runtime/agent/current/bin/morpheus models
/home/operator/morpheus-runtime/agent/current/bin/morpheus doctor
```

## Project Boundary

- Morpheus is independent. Do not import, vendor, symlink, or depend on ODS
  source code; consult ODS for ideas only.
- Tonos is an independent peer harness, not a component or dependency
  (`docs/adr/0010-...`, `docs/TONOS_INTEROPERABILITY.md`). No import/vendor/
  start/configure of a Tonos checkout. Sanitized evidence exchange is deferred
  until R1+R2 are green AND separately authorized. A shared correlation value is
  untrusted search metadata, never canonical identity or control channel.
- The active `coder-model` vLLM service, Open WebUI container, their Compose
  project, caches, and data are externally owned. Never restart/recreate/stop/
  reconfigure/write them without an explicit state-changing instruction in the
  current request. In v0.2 terms that stack is `external_observed`; managed
  inference must use separate Morpheus-owned roots, labels, manifests, endpoints.

## Engineering Rules

- TDD: failing requirement test first, minimal implementation, refactor.
- Keep core domain logic pure and dependency-free; external behavior behind
  typed adapter protocols.
- Use structured parsers for JSON, YAML, metrics, Compose data.
- Do not expose or retrieve secret values for diagnostics.
- Do not weaken tests, security controls, status semantics, or type checks to
  make a build pass.
- Map boundary DTOs explicitly onto the canonical record family; never add a
  competing identity, plan, lifecycle, or evidence representation.
- Concise comments only for non-obvious decisions; generated output goes under
  ignored `artifacts/`.

## Validation

Lanes (see `Makefile`); run the smallest relevant lane while iterating, full
`make gate` before merge:

```
make format-check lint typecheck test-unit test-contract test-integration \
     test-acceptance test-e2e test-coverage security build   # = make gate
```

- Env setup: `make bootstrap` (`uv sync --python 3.12 --extra dev --frozen`);
  every lane runs through `uv run`.
- Single test file/lane examples: `uv run pytest tests/unit/test_deployment.py -q`,
  `uv run pytest tests/acceptance -m acceptance -q`.
- Coverage threshold is 90% and includes `api/app.py` + `agent/app.py`; do not
  re-add omissions to pass.
- CI (`.github/workflows/quality.yml`) also gates the non-Python packages; the
  Makefile does not cover them:
  - `web/` dashboard: node 22 container — `npm ci --ignore-scripts`,
    `npm run format-check`, `npm run typecheck`, `npm test`, `npm run build`;
  - `desktop/` Tauri backend: Rust 1.97.1 — `cargo fmt --check`, clippy
    `-D warnings`, `cargo test --lib --locked`, `cargo build --locked`
    (all with `--manifest-path desktop/src-tauri/Cargo.toml`).
- **Windows quirk:** `make typecheck` fails locally on four pre-existing
  POSIX-API mypy errors (`agent/host.py` clock_gettime/CLOCK_BOOTTIME,
  `agent/app.py` AF_UNIX). Linux CI passes them; everything else must be clean.
- Acceptance tests must exercise the real public/application composition
  boundary (e.g., `create_app(...)` + `TestClient`); component test volume does
  not substitute for specified behavior.
- Live-system tests are opt-in and read-only
  (`MORPHEUS_LIVE_TESTS=1 MORPHEUS_LIVE_MUTATION=0 make test-live-readonly`)
  unless mutation is explicitly authorized. Do not pull release-checklist items
  (24h soak, browser matrix, multi-host rebuilds, sidecars, signing,
  notarization) ahead of their declared gate.
