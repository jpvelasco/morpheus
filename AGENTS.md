# AGENTS.md

## Where We Left Off (2026-08-12)

**Product direction reopened for v0.2 planning.** Morpheus is now planned as a
focused developer-inference appliance with stable native paths on Ubuntu,
Windows, and Apple Silicon macOS. Batwing and Batmobile remain named Linux
qualification machines. The plan adds evidence-ranked model/engine selection,
managed runtime, benchmark history, Tauri desktop plus independent backend,
operations, and bounded AI-assisted diagnosis. The plan has passed a handoff
consistency review; read `docs/IMPLEMENTATION_PLAN.md` Phase 11 onward, including
the Phase 11 implementation handoff, Phase 11.5 walking-skeleton/replan gate,
and ADR-0005 through ADR-0009.

This plan update does not authorize v0.2 runtime implementation or live target
mutation. The next source milestone is Phase 11 contracts and ownership only
when explicitly requested. Search, voice, workflows, research, RAG, image
generation, and other ODS-like breadth are outside the focused v0.2 critical
path unless separately reopened.

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

### Live install (Batwing)

| Item | Value |
|---|---|
| Runtime root | `/home/batjp/morpheus-runtime` |
| Dashboard | `http://127.0.0.1:7401/` (loopback only; use SSH tunnel off-box) |
| API | `http://127.0.0.1:7400/` |
| Env / API key | `/home/batjp/morpheus-runtime/morpheus.env` (mode 0600) |
| Host agent | `/home/batjp/morpheus-runtime/agent/current`, socket under `run/` |
| Install path | `deploy/batwing/install.sh` + `docs/runbooks/BATWING_OPERATOR.md` |
| Candidate | rewritten source `fa5fe3ca2e393d6d20c1afa89dff2452650bf180`; deployed artifacts retain legacy build ID `aa7174aff3194ffeb1ca455d53005f242abe6d82` under `artifacts/candidate-aa7174a/` |

Agent socket directory must be mode `0750` so the API container (host GID) can
reach `agent.sock`. If GPU/storage show unavailable: `chmod 750 …/run` and
confirm the agent PID is alive.

Daily CLI (after sourcing env or using agent venv):

```bash
/home/batjp/morpheus-runtime/agent/current/bin/morpheus status
/home/batjp/morpheus-runtime/agent/current/bin/morpheus models
/home/batjp/morpheus-runtime/agent/current/bin/morpheus doctor
```

### Resume ledger

Read `docs/RELEASE_STATE.md` for candidate evidence and milestone status. The
v0.1 Batwing install remains the operational baseline; the active product queue
starts with the unimplemented v0.2 Phase 11 contract milestone.

## Project Boundary

Morpheus is an independent project. Do not import, vendor, symlink, or depend
on ODS source code. ODS may be consulted for ideas and upstream project names,
but Morpheus implementations and contracts must be written for this system.

The active `qwopus-coder` vLLM service, existing Open WebUI container, their
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
- Prefer `docs/runbooks/BATWING_OPERATOR.md` for host operator install/use.
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
