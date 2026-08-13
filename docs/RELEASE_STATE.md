# Morpheus Release State

This is the durable resume ledger for the current release effort. Update it at
the start and end of each material milestone, and commit it with the related
source change or evidence-plan update. It contains no secrets, credentials,
private request data, host addresses, or unredacted evidence.

## Current Position

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
- **Current release development line:** the rewritten pre-soak source is frozen
  at `fa5fe3c`. Scanner-harness and rebuild-determinism tooling may still land
  after that freeze without relabelling the already-built OCI and Python
  artifacts; any change that alters product source requires a new candidate.
- **Active product direction:** v0.2 reopens Morpheus as a focused developer
  inference appliance with stable native paths on Ubuntu, Windows, and Apple
  Silicon macOS. Batwing and Batmobile remain named Linux qualification
  machines. The accepted plan adds evidence-ranked selection, managed inference,
  benchmark history, a Tauri desktop plus independent backend, operations, and
  bounded AI-assisted diagnosis. The planning handoff was consistency-audited
  and refined on 2026-08-12 with an early vertical slice, bounded self-replan,
  smaller delivery subphases, and optional distribution signing; no v0.2 runtime
  implementation or target mutation has started.
- **Implementation inventory:** 44 implemented, 41 planned, 12 deferred; see
  [`requirements.json`](../requirements.json) and the
  [implementation gap review](IMPLEMENTATION_GAP_REVIEW.md).
- **Release posture:** not yet release-ready. A passing candidate does not
  replace lifecycle, browser, load, fault, supply-chain finalize, or soak
  evidence.
- **GPU posture:** GPU/image-generation work is deliberately excluded from the
  pre-soak core-release lane. It requires a later, separately authorized
  host-maintenance release candidate.

## Handoff and Resume

An agent starting from the repository should read this file first, then
[`IMPLEMENTATION_GAP_REVIEW.md`](IMPLEMENTATION_GAP_REVIEW.md),
[`requirements.json`](../requirements.json), and
[`validation/README.md`](../validation/README.md). Those files define the
remaining requirements, priority, environment boundaries, evidence policy,
and next task; no chat transcript is required to select the next source task.

The P0 pre-soak source queue is complete. Build the candidate only from the
clean source revision containing this ledger, record its full identity in the
candidate manifest, run its early supply-chain gate, and begin clean-VM
container and lifecycle validation. The older baseline evidence must not be
relabelled as evidence for that new candidate.

Normal validation must never restart, reconfigure, or otherwise mutate the
external inference or Open WebUI services. Use disposable stacks/VMs for all
mutating tests. Do not enable persistent user-service linger. GPU allocation,
voice-GPU, and image-generation work are excluded until separately authorized
host-maintenance work begins.

## Completed Current-Candidate Evidence

| Milestone | Result | Notes |
|---|---|---|
| Python quality gate | Pass | 311 tests, 90.28% coverage; format, lint, type checking, Bandit, and offline package build passed. |
| Dashboard quality gate | Pass | Pinned offline Node image: formatting, type check, 31 tests, and production build passed. |
| Reproducible candidate build | Pass | Two independent disposable VM builds used blocked outbound networking and produced five byte-identical artifacts: Python sdist/wheel, agent bundle, backend OCI image, and dashboard OCI image. |

## Approved Candidate-Source Checkpoint

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
candidate (reviewer JP Velasco; no exceptions; no forbidden licenses) and
`validation/security/run.sh finalize` produced a passing supply-chain
manifest.

Candidate container smoke for CONT-002/CONT-003 then passed on a disposable
fixture network using the loaded `morpheus/backend:0.1.0-aa7174aff319` and
`morpheus/dashboard:0.1.0-aa7174aff319` images with Compose `--no-build`. API,
dashboard, and telemetry became healthy; the core probe verified auth, model
discovery, dashboard framing headers, and non-streaming/streaming completions.
Hardening checks confirmed non-root users, read-only roots, `cap_drop ALL`,
`no-new-privileges`, tmpfs, memory limits, loopback-only publications, and no
Docker socket. Selected `qwopus-coder` and Open WebUI identity fields were
unchanged before and after; the disposable project containers, volume, and
network were removed. Evidence:
`artifacts/release-validation/cont002-aa7-cand-evidence/`.

A disposable lifecycle lab then drove the authenticated runtime agent and
`morpheus-lifecycle` against the same candidate images: validate, install,
idempotent reinstall, start, core smoke (API/dashboard/telemetry), named
backup, restore-preflight, stop, and default uninstall that preserved
Morpheus-owned data markers while removing project containers. Every step
reported `protected_external_runtime: unchanged`; selected `qwopus-coder` and
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

**Phase 11 contract foundation is implemented; the next source milestone is the
Phase 11.5 Ubuntu CPU walking skeleton.** RUNM-001 (exactly two ownership modes,
workflow-scoped adoption records, immutable planning contracts, and separate
state machines) is `implemented` with unit, contract, and acceptance coverage
and a complete non-live gate that runs without GPU access or model downloads.
Deployed Batwing v0.1 read-only behavior is preserved; required HOST-RO evidence
for `validated` status remains a later, separately authorized validation step.

## v0.2 Queue

1. **Phase 11 — contracts and ownership:** exactly two typed ownership modes,
   workflow-scoped adoption transfer records, immutable planning records and
   versioned envelopes, and five separate lifecycle state machines. **Done —
   RUNM-001 `implemented`.**
2. **Phase 11.5 — walking skeleton and replan:** run one real disposable Ubuntu
   CPU `llama.cpp` discovery-to-rollback path, record the findings, apply a
   bounded evidence-driven plan adjustment, and continue automatically when its
   gate is green.
3. **Phase 12 — portable discovery and catalogs:** prepare privacy-reviewed
   Batwing, Batmobile, Windows, and Apple Silicon macOS profiles through
   read-only lanes; define native platform ports and versioned catalogs.
4. **Phase 13 — benchmark foundation:** normalize and import the existing
   Qwopus result history before creating new model-management workflows.

The optional search, voice, workflow, research, RAG, and image-generation suite
is not on this critical path. Any product-source change after the existing v0.1
freeze creates a distinct v0.2 candidate; existing artifacts retain their
recorded identity.

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
- Treat Batwing's current coder as `external_observed` until a later request
  explicitly authorizes a tested adoption or replacement workflow.
- Use only disposable candidate stacks and validation VMs for mutation.
- Do not enable persistent user-service linger as a workaround for agent tests.
- Keep GPU allocation and image-generation transitions out of the core-release
  lane until explicit host-maintenance authorization is granted.
