# Morpheus v0.2 Architecture Rectification Plan

Status: Active source milestone

Plan date: 2026-08-22

Audited source: `9b4cda09d4b064f160902b9dd25387cf3129cdb3`

Supersedes as an execution handoff:

- the stale active queues in `AGENTS.md`, `README.md`,
  `IMPLEMENTATION_GAP_REVIEW.md`, and `RELEASE_STATE.md`;
- the completion claim implied by `97 implemented, 0 planned, 0 deferred`;
- the long-horizon implementation prompt in
  `OPENCODE_IMPLEMENTATION_BOOTSTRAP.md`.

It does not supersede the product intent in
[`PRODUCT_SPECIFICATION.md`](PRODUCT_SPECIFICATION.md), the architecture in
[`ARCHITECTURE.md`](ARCHITECTURE.md), accepted ADRs, or the phase exit criteria
in [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).

## 1. Objective

Realign the v0.2 implementation with the accepted architecture by turning the
current collection of strong but partly disconnected components into one
coherent, durable, evidence-backed product workflow:

```text
stable machine profile + retained catalog + workload + policy + benchmark evidence
  -> reproducible recommendation
  -> one canonical immutable deployment plan
  -> verified acquisition
  -> target-native engine staging
  -> bounded campaign
  -> confirmed promotion
  -> durable observation and events
  -> rollback/recovery using the same identities
```

The exact plan, artifact, machine, campaign, recommendation, and operation
identities must survive API/CLI/browser/desktop boundaries and process restart.
No implementation may redefine the accepted architecture merely to preserve a
green component test.

## 2. Authority and Safety Boundary

When sources disagree, use this order:

1. product invariants and functional behavior in `PRODUCT_SPECIFICATION.md`;
2. ownership, component, identity, and data-flow rules in `ARCHITECTURE.md` and
   accepted ADRs;
3. phase dependencies and exit gates in `IMPLEMENTATION_PLAN.md`;
4. this rectification plan and `requirements.json` for active execution;
5. dated audits and historical release evidence for context only.

This plan authorizes source, test, documentation, and disposable DEV/VM work.
It does **not** authorize mutation of the external inference/Open WebUI stack,
HOST-RO or HOST-MAINT execution, model/cache downloads outside a disposable
lane, release publication, signing credentials, licensing changes, or adoption
of an external runtime. Preserve the deployed v0.1 read-only operator surface.

[ADR-0010](adr/0010-optional-external-harness-qualification-evidence.md)
recognizes a future optional evidence boundary with independent harness labs
such as Tonos. Implementing that exchange is not part of R0 through R9 and must
not delay rectification. R1 and R2 should keep canonical evidence imports
producer-neutral; they must not add Tonos-specific domain identities, a sibling
repository dependency, harness orchestration, or remote fleet control.

## 3. Reproduced Findings at the Audited Source

| Finding | Disposition | Current evidence | Rectification owner |
|---|---|---|---|
| AUD-001 canonical identities fragmented | Open, critical | `core/records.py` and `core/deployment.py` define incompatible `DeploymentPlan` types; parallel model, workload, campaign, and recommendation identities remain. | R1 |
| AUD-002 recommendation bypasses evidence | Open, critical | `POST /api/v1/recommendations` uses `SEED_CATALOG`, does not query `BenchmarkStore`, and stores `host.observed_at` as `reference_machine_id`. | R2 |
| AUD-003 managed components are not one workflow | Open, critical | `DevWorkflowExecutor` intentionally fails mutating steps; sessions are in-memory and the runner is synchronous; workflow definitions do not carry a canonical plan or resource identity. | R3 |
| AUD-004 metrics are request-driven and incomplete | Open, high | collection occurs inside `GET /operations/metrics`; the signal registry omits required signals and even exposes `temperature_c` with the default `count` unit. | R5 |
| AUD-005 events have no production ingestion/search | Open, high | production code has no event producers; message search is absent; retention pruning occurs after the query. | R5 |
| AUD-006 native shutdown bypasses supervision | Open, high | `NativeEngineRunner` uses plain `Popen`; `EngineRuntime.stop` calls the child handle directly instead of `ProcessSupervisionPort`. | R4 |
| AUD-007 traceability proves file existence, not behavior | Open, high | the manifest accepts component-only owning files, has no test-level requirement metadata, and excludes important composition roots from meaningful coverage. | R0, R9 |
| AUD-008 current-state documents contradict each other | Open, high | the final GitHub tree simultaneously claims no v0.2 work, Phase 11.5 next, Phase 18 next, and all 97 requirements implemented. | R0 |
| AUD-009 deferred scope was converted to shallow completion | New, critical | the 12 focused-v0.2 deferred requirements were changed to `implemented`; RAG/image modules have no product composition and the original priority boundary was not superseded by an ADR. | R0, R8 |
| AUD-010 desktop and native packaging are scaffolds | New, critical | the shell probes `/healthz` but never performs the authenticated compatibility handshake; only an unsigned `.mrpkg` dev bundler and side-effect-free install executor exist; no native service/installer lanes exist. | R4, R6 |
| AUD-011 diagnosis is only partly composed | New, high | live evidence supplies empty metrics/log sections; local provider wiring is deliberately unavailable; proposed policy plans do not re-enter the ordinary policy/preflight path. | R7 |
| AUD-012 support declarations exceed delivered target paths | New, critical | a frozen claim registry exists, but no Windows/macOS native package, managed-engine application path, or physical qualification evidence exists. | R4, R6, R10 |

The dated audit remains the detailed provenance for AUD-001 through AUD-008.
This plan is their current disposition and closure path.

## 4. Corrected Requirement Posture

`implemented` means the complete specified product behavior exists at its
stable boundary and has meaningful owning tests. A pure policy record, parser,
mocked adapter, UI card, or test-file reference is useful progress but is not
completion. `validated` remains reserved for retained passing evidence from all
required environments.

At this plan revision the honest inventory is:

- 59 implemented;
- 28 planned rectification and accepted-scope requirements;
- 12 deferred requirements;
- 0 validated requirements.

The planned requirements and implementation tasks are:

| Requirements | Task | Missing product behavior |
|---|---|---|
| RUNM-001 | IMP-RUNM-001-02 | carry the canonical ownership and plan identity through API, CLI, UI, agent, persistence, and adoption boundaries |
| BENCH-001, BENCH-005 | IMP-BENCH-001-02, IMP-BENCH-005-02 | canonical suite plus durable authorized execution through a public application boundary |
| SEL-004, SEL-005 | IMP-SEL-004-02, IMP-SEL-005-02 | retained evidence ranking, exact replay inputs, plan conversion, preview, and operator selection |
| PLAT-002, PLAT-003 | IMP-PLAT-002-02, IMP-PLAT-003-02 | integrated process/service adapters and real target-native backend lifecycle executors/packages |
| RUNM-002 through RUNM-006, GATE-001 | IMP-RUNM-002-02 through IMP-RUNM-006-02, IMP-GATE-001-02 | canonical-plan engine lifecycle, mounted bounded managed endpoint, and the integrated stage/campaign/promote/rollback/recovery path |
| UI-003, OUI-005, OUI-006 | IMP-UI-003-02, IMP-OUI-005-02, IMP-OUI-006-02 | real owned-service controls, settings that feed startup/deployment plans, and durable lifecycle-backed workflows |
| OUI-002, OUI-003 | IMP-OUI-002-02, IMP-OUI-003-02 | background metrics and real approved event ingestion/search |
| DESK-001 through DESK-003 | IMP-DESK-001-02 through IMP-DESK-003-02 | shared React desktop delivery, authenticated handshake/bootstrap, native packages, and local/tunnel parity |
| CHAT-001 | IMP-CHAT-001-01 | bounded memory-only model console bound to the canonical selected target, with explicit identity, submission, streaming/cancellation, and no tool execution |
| AID-001, AID-002, AID-004 | IMP-AID-001-02, IMP-AID-002-02, IMP-AID-004-02 | complete live evidence inputs, usable local provider, and proposals routed back through ordinary typed policy plans |
| CHAT-002 | IMP-CHAT-002-01 | optional setup copilot over bounded evidence using diagnosis provider/privacy/advisory boundaries without making setup provider-dependent |
| HOST-003, PLAT-004 | IMP-HOST-003-02, IMP-PLAT-004-02 | actual named-target/native-engine paths and the source prerequisites for later physical evidence |

SRCH-002, VOICE-003, VOICE-004, RSCH-001, RSCH-002, RAG-001 through RAG-003,
and IMG-001 through IMG-004 return to `deferred`. Existing preparatory modules
may remain if they are safe and accurately described, but they are not on the
rectification critical path and may not drive support or completion claims.

## 5. Execution Rules for the Implementing Agent

For every work package:

1. Read the linked product requirements, invariants, architecture sections,
   phase gates, and existing tests before changing code.
2. Record the exact failing acceptance/contract test first. The failure must be
   at the stable public or application boundary named by the requirement.
3. Preserve existing useful component tests. Change or delete a test only when
   the accepted contract changes, and explain the migration.
4. Implement the smallest vertical behavior that crosses the real composition
   boundary. Do not satisfy a gate with a fake production adapter, a hard-coded
   seed, a side-effect-free executor, or a route that only returns a schema.
5. Put side effects behind typed ports and keep domain logic dependency-free.
6. Persist state before every state-changing edge; prove restart, retry,
   cancellation, and recovery behavior.
7. Run the smallest relevant lane while iterating, then the package gate and the
   complete non-live gate named below.
8. Update `requirements.json`, `IMPLEMENTATION_GAP_REVIEW.md`, and
   `RELEASE_STATE.md` in the same change. Do not advance a requirement early.

One integration owner must own R1 through R3. Do not parallelize downstream
schema consumers until R1 freezes the canonical contracts. After R3 lands,
R4, R5, R6, and R7 may proceed in parallel if they consume rather than fork the
canonical identities and operation service.

## 6. Work Packages

### R0 — Restore Truthful Ledgers and Enforce Semantic Traceability

Requirements: all status changes above; TRACE-001/TRACE-002 delivery tasks.

Entry: clean tree at the audited source.

First failing tests:

- manifest test rejects an `implemented` row unless at least one owning test
  contains that exact requirement ID in a test name or explicit metadata;
- manifest test requires a public-boundary owner for requirements whose product
  behavior is API, CLI, browser, desktop, or end-to-end workflow behavior;
- documentation consistency test derives counts from `requirements.json` and
  rejects multiple active milestones or the phrases superseded by this plan;
- coverage configuration test proves API and agent composition roots are either
  measured or represented in a complete route/operation matrix.

Implementation:

- apply the corrected posture in section 4 without deleting partial code;
- add machine-readable test ownership metadata and semantic lane classification;
- report collected, selected, passed, skipped, and deselected counts separately;
- make `RELEASE_STATE.md` the sole current-state ledger and this file the sole
  active source plan;
- classify the August 15 audit, vertical-slice assessment, and original
  long-horizon prompt as historical inputs.

Exit:

- status counts are generated and consistent everywhere;
- no document claims 97 complete, Phase 11.5 next, or physical qualification
  ready;
- manifest checks fail on shallow file-only ownership.

### R1 — Freeze One Canonical Identity and Plan Family

Requirements: RUNM-001; protects INV-001, INV-002, INV-007, INV-008, INV-009.

Entry: R0 green.

First failing acceptance tests:

- one machine/catalog/workload recommendation becomes one canonical deployment
  plan and retains the same IDs through codec, repository, API, and restart;
- lossy conversion from any legacy recommendation/deployment/campaign record is
  rejected;
- state-changing API, agent, and audit records reject a missing, observed, or
  mismatched plan/ownership identity;
- v0.1 observe-only API/CLI/browser behavior remains unchanged.

Implementation:

- select the comprehensive immutable records family as the canonical semantic
  model, adjusting it only through a versioned migration;
- retire or rename competing semantic types in `core/deployment.py`,
  `core/recommendation.py`, `core/workload.py`, `core/models.py`, and benchmark
  modules; retain explicit read/query DTOs only with total, tested mappings;
- define repositories for exact machine profile, catalog snapshot, workload,
  recommendation, plan, campaign, operation, and active/last-known-good plan;
- make content-derived IDs exclude observation timestamps while preserving
  timestamps as provenance;
- migrate or explicitly invalidate current DEV records; do not silently reinterpret them.

Exit:

- exactly one semantic `DeploymentPlan` remains;
- `rg` and architectural tests find no competing identity family;
- one plan ID crosses selection through rollback after application restart;
- the VSLICE-001 fixture and real disposable CPU lane use the same public
  application service and records as production code.

### R2 — Rebuild Recommendation on Retained Catalog and Benchmark Evidence

Requirements: SEL-004, SEL-005; supports BENCH-002 through BENCH-004 and INV-008.

Entry: canonical R1 repositories and migrations fixed.

First failing acceptance tests:

- API recommendation loads one retained catalog digest and stable machine
  profile instead of `SEED_CATALOG` and `observed_at` identity;
- measured, foreign-machine, stale, incomparable, estimated, and missing
  evidence produce distinct confidence/provenance outcomes;
- replaying only the immutable record inputs yields byte-equivalent ranking and
  exclusions;
- choosing a lower-ranked candidate creates a canonical plan that records the
  operator choice without rewriting the recommendation.

Implementation:

- add an application recommendation service over catalog, machine, workload,
  benchmark, policy, and plan repositories;
- preserve catalog versions/digests, full machine profile identity, evidence
  record IDs/digests, estimates, margins, confidence, unknowns, exclusions, and
  score contributions;
- expose preview and selection through authenticated API and CLI, then the
  existing React workspace;
- seed a catalog only during explicit repository initialization; never bypass a
  present repository from the request path.

Exit: the public recommendation path is deterministic, evidence-ranked,
replayable, and losslessly produces the canonical R1 plan.

### R3 — Compose the Durable Managed Operation Service

Requirements: BENCH-001, BENCH-005, GATE-001, RUNM-003 through RUNM-006,
UI-003, OUI-005, OUI-006;
protects INV-007 and INV-009.

Entry: R2 produces canonical plans.

First failing acceptance lane:

```text
authenticated preview
  -> explicit confirmation
  -> verified acquisition
  -> stage engine away from active endpoint
  -> behavioral smoke
  -> bounded benchmark
  -> promotion gate
  -> activate
  -> observe
  -> forced failure
  -> rollback last-known-good
  -> reconnect after API restart
```

The lane uses real disposable local processes, public authenticated API/CLI
boundaries, durable SQLite/application repositories, and no external runtime.
Inject interruption at every durable edge.

Implementation:

- replace `DevWorkflowExecutor` on production routes with an application
  operation service composed from acquisition, engine, campaign, deployment,
  gateway, persistence, audit, and policy ports;
- keep a dev/fake executor only behind explicit test/development injection;
- persist operation inputs, plan ID, state, current step, checkpoints, outcomes,
  confirmation, cancellation request, error, and recovery instructions;
- execute long operations outside the request task with bounded concurrency;
- make start idempotent by operation token and make cancellation cooperative at
  declared safe boundaries;
- resume or safely terminalize interrupted operations after process restart;
- correlate campaign, deployment, event, metric, and audit records to the same plan.
- apply settings overrides through the real startup configuration source and
  convert deployment-affecting changes into canonical plan previews rather than
  writing an inert journal file;
- expose actual Morpheus-owned service actions behind the same plan, ownership,
  authorization, confirmation, and audit boundary; keep external services read-only.

Exit: every OUI-006 workflow either performs the specified owned action or is
honestly unavailable; no production route advertises a simulated mutation.

### R4 — Integrate Target-Native Process and Backend Lifecycle

Requirements: PLAT-002, PLAT-003, RUNM-002, PLAT-004.

Entry: R1 plan and R3 operation contracts fixed.

First failing tests:

- native engine launch creates a POSIX process group or Windows Job Object and
  all graceful/forced cleanup uses `ProcessSupervisionPort`;
- a child/grandchild cannot survive cancellation, timeout, process crash, or
  API restart;
- backend install/restart/upgrade/rollback/uninstall calls real systemd-user,
  Windows per-user, or LaunchAgent adapters in target-native disposable labs;
- locked file, junction/reparse point, symlink, low disk, interrupted update,
  sleep/resume, and reboot preserve last-known-good state.

Implementation:

- inject platform process supervision into `NativeEngineRunner` and
  `EngineRuntime`; remove direct tree-unaware termination;
- derive the engine allowlist and minimum build from the retained engine catalog
  and evidence, including the VSLICE-001 build where still approved;
- implement native install executors behind `InstallAdapter`; the current
  `DevInstallExecutor` remains test-only;
- build actual target-native backend packages and per-user registration assets;
  do not represent `.mrpkg` archives alone as `.deb`, AppImage, MSI, or DMG;
- add native CI/lab lanes, but do not claim physical support from CI.

Exit: target-native DEV/lab lifecycle gates are green and no managed process or
service can outlive its owned operation unintentionally.

### R5 — Make Metrics and Events Independent, Complete Data Pipelines

Requirements: OUI-002, OUI-003.

Entry: R1 correlation identities fixed; may proceed beside R4.

First failing tests:

- background collection persists the full typed signal registry without any
  dashboard request;
- each specified supported signal crosses collector, store, API parser, and
  accessible UI with correct unit/freshness/gap semantics;
- approved API, agent, managed-engine, campaign, deployment, and diagnosis
  events ingest through one redaction-before-persistence boundary;
- expired events are never returned and bounded server-side text/correlation
  search cannot bypass privacy or query limits;
- restart, collector failure, clock change, and engine transition preserve
  honest gaps and unavailable states.

Implementation:

- add a bounded periodic collector lifecycle independent of GET routes;
- define requested/queued concurrency, cache, token-rate, TTFT, throughput,
  error, restart, accelerator memory/utilization/temperature/power, host memory,
  and storage signals with explicit source capability states;
- move pruning before event queries or enforce the retention cutoff in SQL;
- connect approved structured producers; never scrape arbitrary logs or persist
  unredacted free text;
- carry plan, deployment, campaign, operation, request, and diagnosis
  correlation IDs end to end.

Exit: metrics and events remain useful across idle UI periods and process
restart, with privacy canaries absent from producer-to-browser integration tests.

### R6 — Deliver the Real Shared Desktop, Model Console, and Bootstrap Path

Requirements: DESK-001, DESK-002, DESK-003, CHAT-001.

Entry: R3 APIs durable; R4 native backend executors available.

First failing tests:

- the packaged desktop runs the shared React workspace and sends its version in
  an authenticated compatibility handshake;
- missing, unhealthy, compatible, and version-mismatched backends yield real
  install/repair/update/no-op plans and cannot silently replace a running service;
- unsigned developer packages require checksum verification and confirmation;
- close/reopen, backend restart, reboot, browser fallback, session revocation,
  and SSH-tunnel reconnect preserve the same operation/cancellation/recovery semantics;
- capability tests prove the webview has no general shell, filesystem, process,
  or arbitrary network grants while the narrow bootstrap bridge remains usable.
- an explicit model-console submission displays and preserves the canonical
  target, ownership, requested/reported model, and managed plan identity across
  streaming, cancellation, timeout, and model-mismatch outcomes;
- page load, health polling, diagnostics, and background refresh send no
  completion, and model/tool output cannot invoke an operation.

Implementation:

- integrate the built React application with Tauri rather than relying only on
  an unauthenticated health probe and fallback HTML;
- implement secure credential/session handoff and the actual compatibility call;
- connect bootstrap plans to R4 native executors through a narrow confirmed
  command boundary;
- build and inventory the development package formats declared in Phase 16.5 on
  their native runners; keep public signing optional.
- compose a memory-only model console through the versioned API against an
  explicitly selected managed or external-observed target; render structured or
  tool-call output as inert data and persist no conversation content by default.

Exit: Linux, Windows, and macOS native DEV/lab desktop gates pass. Stable target
claims remain blocked on R10 physical evidence. The model console provides a
bounded end-to-end validation workflow without becoming a general-purpose chat
client or granting ownership/lifecycle authority.

### R7 — Complete Diagnostic Evidence, Setup Copilot, and Advisory Re-entry

Requirements: AID-001, AID-002, AID-004, CHAT-002; preserves AID-003.

Entry: R1 deployment identity, R3 plan-preview boundary, and R5 data pipelines
fixed.

First failing tests:

- API-built evidence contains bounded real deployment, metrics, approved log,
  event, regression, and runbook inputs with exact provenance;
- configured local mode calls an explicitly selected local OpenAI-compatible
  provider through a typed inference port and carries its canonical ownership
  and model identity; an external-observed provider requires explicit user
  submission and gains no management authority;
- external mode sends the documented provider schema only after consent, cost,
  destination, retention, timeout, and canary checks;
- a proposed change becomes an ordinary typed R3 plan preview and cannot skip
  policy, preflight, or confirmation;
- provider failure leaves non-AI diagnostics fully functional.
- setup conversation identifies local versus external provider, model,
  destination, retention implications, timeout, cost, and consent, while
  provider absence leaves ordinary setup and the model console fully usable.

Implementation: remove empty placeholder evidence sections, wire the local
provider, define provider-specific transport adapters, present the same bounded
evidence/provider path as an optional setup copilot, and map allowlisted advisory
proposals to ordinary non-executing plan previews. Do not bundle or implicitly
download a helper model.

Exit: diagnosis is grounded in real retained evidence and has no privileged
execution path. The setup copilot shares that boundary, persists no conversation
content by default, and cannot become a prerequisite for setup or operation.

### R8 — Reinstate the Focused v0.2 Scope Boundary

Requirements: the 12 deferred IDs listed in section 4.

Entry: R0 status reconciliation.

Implementation:

- retain safe parsers, policy records, and documentation only as preparatory
  code, clearly labeled incomplete and off by default;
- ensure no capability/support response describes the deferred services as
  usable without their full deployment, integration, lifecycle, privacy, and
  acceptance gates;
- remove false phase-completion language and do not schedule optional service
  work ahead of R1 through R7;
- reopen a deferred requirement only with the trigger, interaction analysis,
  priority decision, and ADR/spec/plan updates required by Phase 30.

Exit: the focused managed developer-inference appliance is the only v0.2 source
critical path.

### R9 — Prove Product Behavior, Not Component Shape

Requirements: all planned rows before they can return to `implemented`.

Entry: R1 through R8 green.

Implementation and gates:

- create a requirement-to-public-boundary matrix covering API, CLI, browser,
  desktop, agent, persistence, and native adapters as applicable;
- add at least one true requirement-level acceptance test per rectified behavior;
- include `api/app.py`, `agent/app.py`, and operation composition roots in
  branch coverage or exhaustive route/operation decision tests;
- run mutation testing for ownership, plan identity, recommendation evidence,
  redaction, process cleanup, and transition policy;
- run the complete Python, frontend, browser, Rust, packaging, security, and
  disposable managed-workflow gates from a clean checkout;
- record exact selected/pass/skip/deselect counts and generated artifact digests.

Exit: every `implemented` row is backed by the behavior its specification
actually names, and every unresolved behavior remains `planned` or `deferred`.

### R10 — Physical Qualification and Release Validation

Requirements: HOST-003, PLAT-004, ACCESS-003, plus all selected release rows.

Entry: R9 green, a clean candidate frozen, and separate explicit authorization
for each HOST-RO/HOST-MAINT lane.

Follow Phase 18 and `RELEASE_VALIDATION_PLAN.md`; do not reinterpret source or CI
success as physical support. Run Ubuntu, Windows, and Apple Silicon lanes
independently, retain evidence, and advance only requirements whose complete
environment matrix passes. Missing signing credentials do not block the
developer/source lane.

## 7. Required Validation by Merge Boundary

| Boundary | Minimum gate |
|---|---|
| R0 documentation/manifest | requirement manifest tests, documentation consistency/link checks |
| R1 core contracts | unit + contract + VSLICE acceptance + schema migration tests |
| R2 recommendation | unit + contract + public API/CLI acceptance + replay fixtures |
| R3 managed operations | unit + contract + integration + disposable process acceptance + restart/recovery |
| R4 native lifecycle | target-native unit/contract/integration and package build gates |
| R5 data pipelines | unit + SQLite integration + API + browser + privacy acceptance |
| R6 desktop | React gate + browser gate + Rust fmt/clippy/test + native package/install lanes |
| R7 diagnosis | unit + provider contract + API integration + adversarial privacy/grounding tests |
| R9 closure | complete non-live repository gate and clean disposable end-to-end lane |
| R10 qualification | separately authorized retained physical and release evidence |

## 8. Migration and Rollback Strategy

- Add schema versions and explicit migrations before switching writers.
- Dual-read is permitted only during one documented migration window; all new
  writes use the canonical schema.
- Preserve current DEV stores as fixtures or export them before destructive
  migration tests. Production v0.1 state is out of scope and must not be touched.
- Keep the old application path available behind a development-only rollback
  switch until R3 end-to-end promotion/rollback passes.
- Each work package lands independently revertible. If a package gate fails,
  revert that package rather than weakening the canonical contract.
- Never relabel historical candidate artifacts or v0.1 evidence as evidence for
  the rectified source.

## 9. Completion Standard

Rectification is complete only when:

- one canonical identity/plan family drives recommendation through rollback;
- recommendations are reproducible from retained catalogs, machine profiles,
  policy, workloads, and benchmark evidence;
- managed operations perform real owned work through durable application
  services and recover across restart;
- native process trees and backend services are supervised by target adapters;
- metrics and approved events are collected independently of UI requests;
- desktop, browser, CLI, and tunneled access share the same authenticated
  operation semantics;
- the bounded model console and setup copilot bind to canonical target/provider
  identities, preserve content privacy, and expose no tool or lifecycle bypass;
- diagnosis uses complete bounded evidence and only proposes ordinary plans;
- deferred optional capabilities remain deferred unless explicitly reopened;
- requirement status, tests, current-state documentation, and release evidence
  agree without qualification by test-count volume;
- the complete source gate passes before any Phase 18 physical lane begins.
