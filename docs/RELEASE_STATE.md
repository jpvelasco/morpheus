# Morpheus Release State

This is the durable resume ledger for the current release effort. Update it at
the start and end of each material milestone, and commit it with the related
source change or evidence-plan update. It contains no secrets, credentials,
private request data, host addresses, or unredacted evidence.

## Current Position

- **Authoritative development source reviewed:**
  `9b4cda09d4b064f160902b9dd25387cf3129cdb3` (final GitHub implementation
  run, audited on 2026-08-22). The active worktree may contain the documentation
  and requirement reconciliation that follows that source.
- **Active source milestone:** architecture rectification R0 through R9; see
  [`RECTIFICATION_PLAN.md`](RECTIFICATION_PLAN.md). R1 canonical identity/plan
  consolidation is the first dependency-critical implementation package.

- **Validated baseline source equivalent:** `aa094172764a4de3e5dc91324306b14857706c4e`
  (`security: bound API request work`). Its pre-publication build evidence
  retains legacy source ID `ae3a98d74b055672c37ae608805e21804d4e609b`.
- **Active pre-soak source equivalent:** `fa5fe3ca2e393d6d20c1afa89dff2452650bf180`
  (`security: scope candidate secret allowlists`). Existing candidate manifests,
  images, and artifacts retain the pre-publication build ID
  `aa7174aff3194ffeb1ca455d53005f242abe6d82`; their manifest remains
  authoritative for that already-built artifact set.
- **Last committed handoff:** `47a36cd` (`docs: make release handoff
  self-contained`; 2026-07-15). Later freeze commits supersede that handoff for
  candidate identity while preserving its documentation role.
- **Historical v0.1 release development line:** the rewritten pre-soak source is
  frozen at `fa5fe3c`. Scanner-harness and rebuild-determinism tooling landed
  around that freeze without relabelling the already-built OCI and Python
  artifacts. The v0.2 development line is separate and has no frozen candidate.
- **Active product direction:** v0.2 reopens Morpheus as a focused developer
  inference appliance with stable native paths on Ubuntu, Windows, and Apple
  Silicon macOS. ubuntu-1 and ubuntu-2 remain named Linux qualification
  machines. The accepted plan adds evidence-ranked selection, managed inference,
  benchmark history, a Tauri desktop plus independent backend, operations, and
  bounded AI-assisted diagnosis. The planning handoff was consistency-audited
  and refined on 2026-08-12 with an early vertical slice, bounded self-replan,
  smaller delivery subphases, and optional distribution signing. Substantial
  v0.2 component implementation now exists, but the final run did not satisfy
  several architecture and phase-integration gates. No live v0.2 adoption or
  target mutation has occurred.
- **Implementation inventory:** 59 implemented, 26 planned, 12 deferred, and 0
  validated; see
  [`requirements.json`](../requirements.json) and the
  [implementation gap review](IMPLEMENTATION_GAP_REVIEW.md). The 26 planned
  rows represent incomplete product composition, not erased component work.
  The 12 optional-scope rows are restored to deferred because no ADR reopened
  that priority boundary and their full product paths do not exist.
- **External harness qualification:** ADR-0010 records Tonos and similar tools
  as optional independent evidence producers. No interoperability code is on the
  R0-through-R9 critical path, no requirement status changes, and no source,
  runtime, control, or release dependency exists.
- **Release posture:** not yet release-ready. A passing candidate does not
  replace architecture conformance, lifecycle, browser, load, fault,
  supply-chain finalize, physical qualification, or soak evidence.
- **GPU posture:** GPU/image-generation work is deliberately excluded from the
  pre-soak core-release lane. It requires a later, separately authorized
  host-maintenance release candidate.

## Handoff and Resume

An agent starting from the repository should read this file first, then
[`RECTIFICATION_PLAN.md`](RECTIFICATION_PLAN.md),
[`requirements.json`](../requirements.json), and
[`IMPLEMENTATION_GAP_REVIEW.md`](IMPLEMENTATION_GAP_REVIEW.md). Those files
define the remaining requirements, priority, environment boundaries, evidence
policy, and next task; no chat transcript is required.

Do not build a v0.2 qualification candidate yet. Execute R0, then R1 through R9
in dependency order. Existing component tests and historical candidate evidence
must not be relabelled as evidence for the rectified source. Only after R9 is
green should a clean candidate be frozen and the separately authorized R10
physical/release lanes begin.

Normal validation must never restart, reconfigure, or otherwise mutate the
external inference or Open WebUI services. Use disposable stacks/VMs for all
mutating tests. Do not enable persistent user-service linger. GPU allocation,
voice-GPU, and image-generation work are excluded until separately authorized
host-maintenance work begins.

## Historical v0.1 Candidate Evidence

| Milestone | Result | Notes |
|---|---|---|
| Python quality gate | Pass | 311 tests, 90.28% coverage; format, lint, type checking, Bandit, and offline package build passed. |
| Dashboard quality gate | Pass | Pinned offline Node image: formatting, type check, 31 tests, and production build passed. |
| Reproducible candidate build | Pass | Two independent disposable VM builds used blocked outbound networking and produced five byte-identical artifacts: Python sdist/wheel, agent bundle, backend OCI image, and dashboard OCI image. |

## Historical v0.1 Candidate-Source Checkpoint

At handoff commit `3d1feaa`, the Python quality gate passed with 345 tests and
90.52% coverage; formatting, lint, type checking, Bandit, pip-audit, and the
offline package build also passed. This confirms source health at that point,
but it is not release evidence: the SEC-005 and REL-003 source gaps were still
open at that checkpoint, no new candidate has been frozen, and all
candidate-specific startup/lifecycle/browser/load/soak
evidence must be produced again after the freeze.

On 2026-07-16, the current worktree implemented the guarded `tests/live` vLLM
lane and added compatibility for the current KV-cache metric name. A HOST-RO
development-line rehearsal then passed model discovery, health, and all six
expected metrics signals with protected container identity unchanged.

The same worktree completed a disposable core-container startup rehearsal
against the internal-only fixture. API, dashboard, and telemetry health,
authentication, model discovery, non-streaming, and streaming all passed. The
actual run exposed and fixed private env-file isolation, host/container port
separation, and premature streaming cancellation. Cleanup removed the named
containers, network, volume, and temporary secret file; the protected external
runtime identity remained unchanged. The final non-live gate passed with 362
tests and 90.13 percent coverage. The next telemetry compatibility increment
then normalized upstream HTTP errors, timeouts, and empty streams before
response headers for both streaming and non-streaming requests. The latest
full gate passes 367 tests at 90.16 percent coverage; the disposable
restart/retention/backup/cancellation matrix then completed successfully.

The OPT-TEL-001 DEV rehearsal compared direct and proxied streaming and
non-streaming bytes, usage fields, authentication, upstream HTTP failures,
empty streams, timeouts, cancellation, capacity recovery, and direct bypass on
an internal-only fixture network. The live run exposed and fixed two additional
gaps: configured telemetry retention was never invoked by the running service,
and Starlette disconnect cancellation could interrupt persistence and limiter
cleanup. Startup and per-record pruning now enforce the retention window, and
stream cleanup is cancellation-shielded with guaranteed slot release. A real
restart pruned an explicitly expired record while preserving 15 recent records
identical to the SQLite backup; post-restart traffic increased the final
privacy-clean backup to 24 records with all five expected outcomes. Core and
telemetry smoke passed after restart, content canaries were absent from raw
database files, backup, and all disposable container logs, and hardening plus
loopback bindings matched policy. Cleanup removed every named container,
network, volume, project image, and temporary secret file. The protected vLLM
identity, image, start time, restart count, and healthy state were unchanged.
After these fixes, the complete non-live gate passed 373 tests at 90.19 percent
coverage with strict formatting, linting, typing, Bandit, pip-audit, and the
offline sdist/wheel build green.

IMP-SEC-005-01 then added the locked two-stage supply-chain gate. It inventories
the Trivy database, stages only tracked and non-ignored worktree inputs, runs
redacted Git/worktree/candidate secret scans, blocks unresolved high/critical
filesystem and OCI findings without ignoring unfixed vulnerabilities, produces
CycloneDX JSON and SPDX JSON for every candidate artifact, and binds a human
license approval to the exact report digests. A closed verifier rejects stale,
missing, altered, unsafe, or incomplete evidence. The DEV rehearsal passed the
real pinned Gitleaks history and worktree scans and an offline Trivy scan with
zero high/critical vulnerabilities, misconfigurations, or secrets; its license
inventory contained Apache-2.0, BSD-2-Clause, BSD-3-Clause, BlueOak-1.0.0,
CC-BY-4.0, ISC, MIT, MIT-0, MPL-2.0, and Python-2.0. This is implementation
evidence only; the exact candidate must still produce SUPPLY-001 through
SUPPLY-004 evidence after the next freeze.

IMP-REL-003-01 then added a disabled-by-default signed runtime-agent endpoint
and separate `morpheus-lifecycle` CLI for fixed install, validate, start, stop,
migrate, backup, restore-preflight, upgrade, rollback, and uninstall actions.
The concrete adapter accepts only versioned manifests below one configured
deployment root, uses no-build/no-pull Compose commands, checks existing
project resources for the exact ownership label, compares selected protected
external identity fields before and after every action, writes atomic owned
state, backs up before upgrade, recovers failed replacement, restores state on
rollback, preserves data on default uninstall, and gates purge behind lab
configuration plus exact project confirmation. Adversarial tests cover forged
labels, corrupt state, unsafe manifests, unmarked data, failed first install,
and failed running upgrade. The complete gate now passes 495 tests at 91.16
percent coverage; format, lint, strict typing, Bandit, pip-audit, and offline
sdist/wheel builds are green. This remains DEV implementation evidence until
the exact candidate passes the clean-VM lifecycle and integrity matrix.

The current worktree also added the digest-pinned, network-disabled Playwright
gate for the production dashboard build. A TDD browser case reproduced an
overlapping-refresh race in which an older response replaced newer evidence;
the dashboard now keeps one active abortable refresh and cancels superseded,
sign-out, and unmount work. The final DEV rehearsal passes 36 tests across
Chromium, Firefox, WebKit, and mobile Chromium, including axe serious/critical
checks, keyboard focus, reduced motion, responsive bounds, failure retention,
state rendering, session storage, and retained-evidence canary scanning. The
pinned frontend gate passes 31 unit tests with 96.77 percent statement, 90.06
percent branch, and 90 percent function coverage plus strict lint, typecheck,
and production build. The complete non-live repository gate now passes 533
tests at 90.56 percent coverage with every security and build check green.
Exact-candidate CSP, CORS, CSRF, framing, request-ID, and reviewed screenshot
evidence remains pending and no BROW task is marked
release-validated by this DEV rehearsal.

IMP-PERF-002-01 then added pure load-overhead and resource-budget decisions,
strict k6 and Docker-stats parsers, whole-host CPU normalization, and a
read-only adapter that discovers only exact ownership-labeled containers. The
fixed pinned-k6 workload declares stream mix, synthetic latency, VUs, warm-up,
duration, sampling, thresholds, and DEV, ten-minute qualification, and 24-hour
profiles. Its disposable DEV rehearsal initially failed at 44.10 ms added
median wait and 6.57 percent throughput loss, exposing synchronous SQLite
persistence on the successful response path. Persistence now runs as shielded
response-background cleanup while retaining the bounded concurrency slot. The
latest rehearsal passed with zero failures, 1.85 ms added median wait, 1.10
percent throughput loss, 84–85 MiB combined idle API/dashboard memory, and
0.50–0.51 percent whole-host CPU across three samples. The load runner now
labels and verifies its exact one-run container before interrupt cleanup, and
the soak supervisor fails and terminates its peer when either load or resource
monitoring exits early. Cleanup removed every labeled container, image,
network, volume, runner identity file, and temporary key file; selected
protected vLLM and Open WebUI identity fields were unchanged. This is DEV
implementation evidence, not the required candidate VM, target-host, two-hour,
or 24-hour validation.

These ignored rehearsal manifests are not candidate evidence because the runs
were on DEV rather than a clean VM and do not identify a built candidate
artifact set. The linked requirements therefore remain `implemented`, not
`validated`.

The first frozen pre-soak source at `5688aed` passed two independent
byte-for-byte VM rebuilds and closed ten-artifact verification, then the early
candidate secret scan stopped on nine reviewed false positives: the official
Python base image's public 40-hex GPG signing fingerprint repeated in OCI and
rollback archives, plus empty assignments from `.env.example` inside a nested
archive path. The scanner policy now permits only that exact public-fingerprint
shape and recognizes the already-reviewed empty template through `/` or archive
`!` boundaries. Because scanner policy is release source, `5688aed` is
superseded and must not be promoted.

The superseding source at `fa5fe3c` (legacy built-artifact ID `aa7174a`)
completed two independent disposable VM rebuilds with guest and container
egress blocked. Five primary artifacts
compared byte-for-byte; the full ten-artifact set verified under
`verify_candidate` with candidate-manifest digest
`fee82dfc8b892a82298b4308e7e558ad3e9d635ed61d2cce0bdb937a3191a5f7`. The early
network-disabled supply-chain scan then reported zero Gitleaks findings across
history, worktree, and candidate archives; zero high/critical Trivy findings on
repository, candidate filesystem, and both OCI images; and CycloneDX plus SPDX
SBOMs for every declared artifact. Human license review was approved for that
candidate (reviewer: project maintainer; no exceptions; no forbidden licenses) and
`validation/security/run.sh finalize` produced a passing supply-chain
manifest.

Candidate container smoke for CONT-002/CONT-003 then passed on a disposable
fixture network using the loaded `morpheus/backend:0.1.0-aa7174aff319` and
`morpheus/dashboard:0.1.0-aa7174aff319` images with Compose `--no-build`. API,
dashboard, and telemetry became healthy; the core probe verified auth, model
discovery, dashboard framing headers, and non-streaming/streaming completions.
Hardening checks confirmed non-root users, read-only roots, `cap_drop ALL`,
`no-new-privileges`, tmpfs, memory limits, loopback-only publications, and no
Docker socket. Selected `coder-model` and Open WebUI identity fields were
unchanged before and after; the disposable project containers, volume, and
network were removed. Evidence:
`artifacts/release-validation/cont002-aa7-cand-evidence/`.

A disposable lifecycle lab then drove the authenticated runtime agent and
`morpheus-lifecycle` against the same candidate images: validate, install,
idempotent reinstall, start, core smoke (API/dashboard/telemetry), named
backup, restore-preflight, stop, and default uninstall that preserved
Morpheus-owned data markers while removing project containers. Every step
reported `protected_external_runtime: unchanged`; selected `coder-model` and
Open WebUI identity fields matched before/after. Evidence:
`artifacts/release-validation/life003-aa7-lab/`. External-network integrity
hashing no longer includes live endpoint membership so expected Morpheus
attachments do not false-fail the gate.

During the supply-chain gate, two scanner-harness defects were fixed without
changing the frozen product artifacts: Trivy image scans now extract OCI-layout archives
before `--input`, and Syft SBOM generation uses a 1 GiB tmpfs so large OCI
unpacks cannot leave empty report files. The offline rebuild path also forces
`install.sh` mode `0755` so clone umask cannot diverge the agent tarball on a
future freeze.

Release evidence is intentionally ignored from Git. Store it only under the
configured `artifacts/release-validation/` location or a disposable validation
workspace; refer to the candidate commit and task ID in its redacted manifest.

## Last Completed Source Milestones

| Commit | Milestone |
|---|---|
| `b07ffce` | Windows parity for the local validation lanes; POSIX behavior unchanged (bounded fixes only). |
| `aa09417` | Request body limits, content/schema checks, timeouts, rate limits, and bounded concurrency across exposed APIs. |
| `cdb3eba` | Signed browser-session decision record and validation-plan correction. |
| `3c4ba66` | Browser API-key removal; signed, expiring cookie sessions with CSRF-protected logout. |
| `1cb3e5c` | RUN-005 now derives optional-capability state from live, Morpheus-owned runtime-agent container health evidence. |
| `7c84ebc` | SEC-002 now authorizes only explicit read-only resource actions on owned, non-protected identities. |
| `c108108` | SEC-006 now resolves configured data, persistence, archives, generated output, evidence, and restore staging through owned-path boundaries. |
| `14d93da` | REL-002 now applies bounded retry/backoff/deadline recovery to idempotent inference discovery. |
| `3d1feaa` | OPS-002 now preflights schema/free space and performs durable rollback-capable restore swaps. |

## Active Milestone

**Architecture rectification is active; R0 documentation/status reconciliation
is followed by R1 canonical identity and deployment-plan consolidation.** The
final component run is not a phase-exit record. RUNM-001 and the other planned
rows remain incomplete until their canonical behavior crosses the required
public/application boundaries and their affected gates pass.

## v0.2 Queue

1. **R0 — truthful ledgers and semantic traceability.** Reconciled in this
   documentation change; implementation must add the planned enforcement tests.
2. **R1 — canonical identity and plan family.** Required before downstream fan-out.
3. **R2 — evidence-backed recommendation.** Use retained catalog, machine, and
   benchmark records and produce the canonical plan losslessly.
4. **R3 — durable managed application service.** Replace DEV-only workflow
   simulation and inert settings/control paths with real owned operations.
5. **R4 through R7 — native lifecycle, observability, desktop, and diagnosis.**
   These may fan out only after the R3 application boundary is fixed.
6. **R8/R9 — focused-scope and product-boundary closure.** Keep optional scope
   deferred and prove each status at its real boundary.
7. **R10 — physical qualification.** Blocked until R9 and separately authorized.

Any v0.2 product-source candidate is distinct from the existing v0.1 freeze;
historical artifacts retain their recorded identities.

### Historical Component Implementation Record

The following records useful components that landed during the implementation
run. The word “added” does not mean the corresponding phase or requirement exit
gate is satisfied after the 2026-08-22 audit.

Phase 16.2 added three data workspaces behind the Phase 16.1
operations navigation: OUI-002 bounded metrics rollups (per-signal units,
freshness, gaps, retention, and a 240-bucket query bound), OUI-003 redacted
logs and events (approved sources, normalized severity/correlation, redaction
before persistence or display, and bounded filtering), and OUI-004
analytics and comparisons (benchmark run history, usage and reliability
scorecards, directly-comparable before/after comparisons, and regressions).
Phase 16.3 added OUI-005 settings validation/preview components (pydantic-free catalog,
plan preview, apply, and rollback through an atomic overrides journal) and
OUI-006 managed workflow sessions (typed definitions, confirmation, progress,
cancellation, and audit trail). The settings journal is not a startup source and
the workflow production route uses a non-mutating DEV executor. Phase 16.4
added DESK-001's minimal-capability
Tauri 2 shell (`desktop/src-tauri/`) and DESK-002's authenticated
`GET /api/v1/system/compatibility` API contract; the shell does not yet call that
handshake. The webview holds only core
window/webview/event permissions — no shell, filesystem, HTTP, or process
capability — enforced by a startup manifest check and Rust tests, with a
bundled open-in-browser fallback page when no loopback backend is reachable.
Phase 16.5 completed DESK-002 with the package-trust core
(`core/package_trust.py`, developer/source vs signed-distribution
qualifications; unsigned packages always require confirmation and can never
enable unattended update), the confirmed bootstrap planner (`core/bootstrap.py`
with install/repair/update/rollback/noop plans that never silently replace a
running backend), the install adapter with a side-effect-free dev executor
(`adapters/install/`), a Rust plan-gating module, and
`desktop/package/package-dev.sh` bundling the compiled shell into a
checksummed `.mrpkg` with per-file digests, an SPDX SBOM, and a SHA256SUMS
sidecar. Native lifecycle executors and the declared platform package formats
remain planned. At that historical checkpoint the complete non-live gate passed
1458 tests with 91.05 percent
coverage; strict formatting, linting, Bandit, pip-audit, and offline package
builds are green, the pinned frontend gate passes 131 unit tests at 99.01
percent statement coverage with strict lint, typecheck, and production build,
and the desktop gate passed 17 Rust tests under fmt/clippy `-D warnings` with
a pinned 1.97.1 toolchain. The browser lane keeps 48 passing Playwright e2e
instances (sequentially flaky only on this harness's chromium-mobile infra
under sustained load; each instance passed standalone). These counts are
historical component evidence, not current completion evidence; no v0.2
candidate exists yet.

Developer/source qualification uses checksummed, scanned, SBOM-backed native
packages and never waits on public signing credentials. Windows signing, Apple
signing/notarization, Linux distribution signing, and trusted unattended update
are optional post-qualification work under ADR-0009.

The repository still declares `Proprietary - no license granted`. A possible
future open-source publication is a separate operator decision and does not block
implementation; no agent may infer or announce an open-source license.

## Operating Constraints

- Never restart, reconfigure, or mutate external inference/Open WebUI services
  during normal validation.
- Treat ubuntu-1's current coder as `external_observed` until a later request
  explicitly authorizes a tested adoption or replacement workflow.
- Use only disposable candidate stacks and validation VMs for mutation.
- Do not enable persistent user-service linger as a workaround for agent tests.
- Keep GPU allocation and image-generation transitions out of the core-release
  lane until explicit host-maintenance authorization is granted.
