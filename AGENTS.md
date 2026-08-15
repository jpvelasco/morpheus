# AGENTS.md

## Where We Left Off (2026-08-15)

**Phase 16.2 (OUI-002 bounded metrics rollups + OUI-003 redacted logs/events +
OUI-004 analytics and comparisons) is implemented and merged.** Backend
(`core/metrics_history.py` rollups, gaps, freshness, units, 240-bucket bound;
`core/events.py` redaction and bounded filtering; `core/analytics.py` scorecards,
comparisons, regressions; `api/operations.py` metrics/events/benchmarks/analytics
routes plus navigation `data_states`), contract tests
(`test_operations_contract.py`), and the frontend workspace SPA (trend charts,
event log with filters, benchmark history, analytics views) are green: 892 unit,
428 contract, 29 integration, 26 acceptance, 114 vitest (99.62% statements),
48 Playwright e2e instances. OUI-002, OUI-003, and OUI-004 are flipped to
`implemented` at 0.2.0 in `requirements.json` (71 implemented, 14 planned,
12 deferred).

The v0.2 product direction paragraph below remains the standing context:
focused developer-inference appliance, Phase 11 onward plan, ADR-0005 through
ADR-0009, evidence-ranked selection, managed runtime, benchmark history, Tauri
desktop, operations, and bounded diagnosis. The standing continuation for
v0.2 work stays in force; the active product queue now starts with Phase 16.3
(OUI-005 settings, OUI-006 managed workflows) in dependency order.

The deployed v0.1 Morpheus remains a **read-only operator surface**; planning
language must not be mistaken for deployed behavior.

Once a user explicitly authorizes long-horizon v0.2 implementation, agents may
continue across green DEV and disposable-lab subphases without asking at every
phase boundary. They must run the Phase 11.5 Ubuntu CPU walking skeleton, record
its self-assessment, apply any bounded evidence-driven replan, and then continue
in dependency order. This standing continuation never authorizes a live-host
operation, external-service/cache mutation, release publication, or access to
signing credentials.

Windows public signing and Apple signing/notarization are optional final
distribution-hardening lanes. Missing credentials must not delay source,
packaging, DEV/VM, or physical product work. Unsigned development artifacts stay
checksummed and explicitly confirmed, and unattended update remains disabled.

The repository currently declares `Proprietary - no license granted`. Public
visibility alone is not an open-source license. Do not change licensing metadata,
add a license, or claim Morpheus is open source until the user explicitly chooses
the license and publication policy; that decision does not block implementation.

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

Do not pull formal release checklist items (24h soak, full browser matrix,
dual-VM rebuilds, optional sidecars, public signing/notarization) ahead of their
declared phase. Missing optional distribution credentials are never a reason to
stop independent implementation work.
