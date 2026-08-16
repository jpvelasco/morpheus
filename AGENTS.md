# AGENTS.md

## Where We Left Off (2026-08-15)

**Phase 16 (16.1-16.5, Tauri shell + package trust), Phase 17.1 (AID-001
diagnostic evidence packages), Phase 17.2 (AID-002/003/004 grounded
AI-assisted diagnosis), Phase 17.3 (ACCESS-001 + DESK-003 loopback
and SSH-tunnel access profiles), and Phase 17.4 (ACCESS-002 optional
TLS network profile) are implemented and merged.** 16.4 shipped the
Tauri 2 shell (`desktop/src-tauri/`: loopback health discovery on 7400/7401,
no shell/fs/http/process/opener webview capability - enforced by a startup
manifest check and Rust tests, fallback page with open-in-browser and
bootstrap-plan status, 10 Rust tests). 16.5 shipped the package-trust core
(`core/package_trust.py`: developer/source vs signed-distribution
qualifications; unsigned packages always require confirmation and can never
enable unattended update), the confirmed bootstrap planner
(`core/bootstrap.py`: install/repair/update/rollback/noop plans; a running
backend is never replaced silently), the install adapter + dev executor
(`adapters/install/`), a Rust plan-gating module (17 cargo tests total), and
`desktop/package/package-dev.sh` which bundles the compiled shell into a
checksummed `.mrpkg` with SHA256SUMS. CI desktop job now also builds the
binary. 17.1 (AID-001) shipped bounded redacted diagnostic evidence packages:
`core/runbooks.py` (known-runbook registry), `core/diagnostic_evidence.py`
(schema v1, 8 bounded sections, per-section digest manifest, canary and
secret-shaped content scrubbed), `ops/diagnostics.py` (EvidenceRun-backed
package writer), and `POST /api/v1/diagnostics/evidence` which assembles a
DEV evidence run from live health, host snapshot, events store, and benchmark
regressions - never prompts, responses, or secrets. 17.2 (AID-002/003/004)
shipped disabled/local/external provider adapters with grounded structured
findings: `core/diagnosis.py` (strict schema parser - provider output can
never become an executable operation, deterministic grounding evaluation,
typed runbook/policy-plan proposals), `adapters/diagnosis/` (local via a
typed inference port with real timeout; external with consent gate, cost
guard, and canary-absence check before any request), `ops/diagnosis.py`
(provider failure never blocks ordinary diagnostics), and
`GET /api/v1/diagnostics/provider` + `POST /api/v1/diagnostics/analyze`.
17.3 (ACCESS-001 + DESK-003) shipped the access-profile core
(`core/access.py`: loopback and ssh_tunnel profiles, loopback-only binding
enforced at settings validation, proxy headers never trusted,
`GET /api/v1/system/access` posture report), the
`docs/runbooks/ACCESS.md` tunneling runbook registered as `access-operator`,
and parity/revocation/reconnect contract suites proving tunneled access
shares identical authorization, CSRF, and cookie semantics with direct
loopback access.
17.4 (ACCESS-002) shipped the optional TLS network profile
(`core/access.py` AccessProfile.NETWORK: requires allow_lan, tls cert+key
paths, explicit https `allowed_origins`, secure cookies, and api_key;
origin enforcement middleware rejects disallowed Host headers with 403;
proxy headers never bypass authorization; uvicorn TLS wiring for API,
telemetry, and dashboard runners; `docs/runbooks/ACCESS.md` network
profile section), with exposure, origin, proxy-header, brute-force, and
recovery contract suites proving non-loopback exposure stays confined to
the network profile and rate-limited recovery after restart.
17.5 (ACCESS-003) shipped the evidence-bounded support matrix
(`core/support_matrix.py`: pure deterministic derivation of os,
architecture, accelerator, engine, install, lifecycle, access, recovery,
and benchmark claims from retained PASS evidence runs and completed
benchmark runs; claims always carry exact `run_id:digest` references;
named targets are advertised only from physical HOST-RO/HOST-MAINT
evidence naming the machine), the read-only evidence scanner
(`ops/support.py` SupportReportService), `GET /api/v1/support`, and
unit + contract suites proving absent evidence never becomes a claim and
DEV/VM evidence never names a physical target.
18.1 (HOST-003 + PLAT-004) shipped the frozen target/support matrix
(`core/targets.py`: immutable declarations for ubuntu-1, ubuntu-2,
windows-x64, and macos-arm64; every declared claim maps to an exact
artifact kind, machine, lane (HOST-RO/HOST-MAINT), and rollback path;
nothing outside the registry is advertised), target posture derivation
(`derive_target_posture` in `core/support_matrix.py`: per-claim proven/
unproven state strictly from retained evidence, `validated` only when
every declared claim is proven), the `docs/runbooks/QUALIFICATION.md`
runbook registered as `qualification-operator`, and `GET /api/v1/support`
now returns the full declared matrix with artifact/lane/rollback mapping
per claim.
Gate totals: 1587 collected backend (1578 passed, 9 skipped, 91%
coverage), 131 vitest (99.01%), 48 Playwright e2e, 17 cargo tests.
All planned requirements are flipped to `implemented` at 0.2.0 in
`requirements.json` (85 implemented, 12 deferred); HOST-003 and PLAT-004
retain `requires_live_evidence` and `requires_hardware_evidence` — the
physical qualification lanes (Phase 18.2-18.4) are their remaining gates.
AID-001 retains
`requires_live_evidence: true`; live HOST-RO validation happens in the
physical qualification lane.

The v0.2 product direction paragraph below remains the standing context:
focused developer-inference appliance, Phase 11 onward plan, ADR-0005 through
ADR-0009, evidence-ranked selection, managed runtime, benchmark history, Tauri
desktop, operations, and bounded diagnosis. The standing continuation for
v0.2 work stays in force; the active product queue now continues with Phase
18 (frozen target/support matrix and physical qualification lanes) in
dependency order. 18.1 is delivered; 18.2-18.4 are the physical lanes and
never run without explicit live-host authorization.

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
