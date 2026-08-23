# Morpheus TDD Implementation Plan

Status: Accepted v0.2 phase plan; phase completion claims are under
rectification; v0.1 foundation remains deployed

Plan version: 0.2

Requirements source: [PRODUCT_SPECIFICATION.md](PRODUCT_SPECIFICATION.md)

Architecture source: [ARCHITECTURE.md](ARCHITECTURE.md)

Active execution source: [RECTIFICATION_PLAN.md](RECTIFICATION_PLAN.md)

The original phase order and exit criteria remain normative. The final
implementation run produced many phase components without satisfying several
integration gates. Execute rectification packages R0 through R9 before Phase 18
physical qualification; do not restart this document at Phase 11 or treat later
component merges as proof that their phase exited.

## 1. Delivery Policy

Morpheus is delivered as a sequence of independently useful, releasable phases.
No phase begins by deploying into the production server. Behavior is first
specified through tests, implemented against fakes and disposable dependencies,
then validated through an explicitly authorized live lane.

The active inference and Open WebUI services are protected fixtures, not a
development sandbox. Live tests are read-only until a later requirement
explicitly authorizes a state transition.

Phase exit criteria are source-implementation gates unless they explicitly say
that retained target evidence is required. The `required_environments` and
`requires_live_evidence` fields in `requirements.json` describe the evidence
needed to advance a requirement to `validated`; they do not authorize a live
run and do not block an implemented status once the owning non-live tests pass.
Every HOST-RO or HOST-MAINT run remains a separate, explicitly authorized
validation action.

The v0.2 critical path begins at Phase 11 below. Phases 0 through 10 remain the
historical v0.1 implementation and release plan. Unfinished search, voice,
research, RAG, workflow, and image-generation work from those phases is not
automatically promoted into the v0.2 queue. The focused appliance first delivers
host discovery, model/engine selection, managed inference, durable benchmarks,
operations, and diagnosis.

## 2. Test-Driven Development Loop

Every requirement follows this loop:

1. **Select the contract.** Identify a product requirement ID and the observable
   behavior at the closest stable boundary.
2. **Write the failing test.** Prefer an acceptance or contract test before a
   unit test so implementation cannot redefine the requirement.
3. **Verify the failure.** The test must fail because behavior is missing or
   incorrect, not because the fixture or environment is broken.
4. **Implement minimally.** Add the smallest coherent domain and adapter change.
5. **Refactor under green.** Remove duplication and clarify names without
   broadening behavior.
6. **Run the affected pyramid.** Unit, contract, integration, and acceptance
   lanes run according to the changed boundary.
7. **Record evidence.** Link requirement, tests, commands, and results.

### 2.1 Agent Handoff and Merge Discipline

- `requirements.json` is authoritative for functional-requirement status,
  implementation task identity, and evidence obligations. `INV-*` identifiers
  are mandatory cross-cutting constraints traced through the functional
  requirements they protect; they are not separate status rows in that file.
- Assign each implementation task to one integration owner and one final owning
  change. Contributors may prepare non-overlapping slices after shared contracts
  land; the owner lists the functional requirement IDs, affected invariants,
  first failing tests, and explicit non-goals before implementation begins.
- Land shared domain contracts and schema versions before starting parallel
  adapter, API, persistence, or UI work that consumes them. Agents must not
  create competing representations of ownership, identity, lifecycle state, or
  evidence confidence in separate branches.
- A task may change `planned` to `implemented` only after its owning tests and
  the affected non-live gate pass. Only retained passing evidence from every
  required environment may change `implemented` to `validated`.
- Integration agents resolve contract changes at the domain boundary, run the
  complete affected pyramid, and update the gap review and release ledger in
  the same change. They do not weaken a contract to merge divergent adapters.

When the user explicitly authorizes long-horizon v0.2 source implementation,
agents continue through the dependency-ordered DEV and disposable-lab subphases
without requesting a new decision at every green gate. At each subphase they
must update tests, requirement ownership, the gap review, and the release ledger
before selecting the next unblocked subphase. They diagnose and repair ordinary
implementation failures rather than treating them as planning blockers.
Partial subphases leave a functional requirement `planned` until its complete
observable behavior and owning gate pass; progress is recorded in the ledger
rather than hidden behind a premature status change.

That continuation authority never implies HOST-RO or HOST-MAINT permission,
mutation of an external service or cache, use of private signing credentials,
publication of a release, or weakening an invariant. Missing optional signing,
notarization, hardware, or external-provider inputs are recorded and bypassed
through the declared development lane while independent source work continues.

Tests are not allowed to:

- assert private method calls when public behavior can be observed;
- mock the unit under test;
- silently skip when a required dependency is absent;
- accept multiple unrelated outcomes to avoid choosing a contract;
- use production secrets, prompts, conversations, or databases;
- mutate the current live stack in an ordinary test command.

## 3. Test Architecture

### 3.1 Unit Tests

Cover pure domain behavior, parsing, normalization, policy, state aggregation,
retention, redaction, authorization, and error mapping. Unit tests must not use
network, filesystem, clock, environment, subprocess, or database state unless a
port is supplied explicitly.

Targets:

- core branch coverage at least 95 percent;
- security and ownership policy branch coverage at 100 percent;
- overall Python branch coverage at least 90 percent;
- frontend statement and branch coverage at least 85 percent for non-generated
  application code.

Coverage is a floor, not completion evidence. Mutation testing is required for
core policy, ownership, health aggregation, redaction, and archive validation.

### 3.2 Contract Tests

Contract tests lock:

- OpenAI `/v1/models` and chat-completions behavior;
- vLLM metrics parsing across captured sanitized versions;
- runtime-agent request and response schemas;
- Control API OpenAPI schema;
- database migration compatibility;
- SearXNG JSON search;
- OpenAI-compatible STT and TTS;
- telemetry streaming and error semantics;
- machine-profile and desktop/backend compatibility-handshake schemas;
- managed-engine capability, launch-plan, health, metrics, and log contracts;
- n8n template schema and Perplexica configuration;
- Compose ownership labels, networks, volumes, ports, health checks, and image
  digests.

Third-party contract fixtures include provenance and capture date. Secrets and
content are replaced with deterministic canaries before commit.

### 3.3 Integration Tests

Integration tests use disposable temporary directories, networks, containers,
and databases. They prove adapter behavior, migrations, sidecar health, backup,
restore, and failure recovery.

Every integration resource receives a unique test project label and is removed
after the test. Cleanup failure is a test failure and prints safe recovery
instructions.

### 3.4 Acceptance Tests

Acceptance tests are named for requirement IDs and express operator-visible
workflows. They run through public CLI, API, or browser boundaries.

Examples:

- `test_INV_001_install_preserves_external_runtime`
- `test_RUN_006_doctor_reports_partial_dependency_failure`
- `test_VOICE_003_open_webui_compatible_audio_contract`
- `test_IMG_002_rejects_start_without_gpu_headroom`

### 3.5 Live Compatibility Tests

The default live lane is read-only and requires:

```text
MORPHEUS_LIVE_TESTS=1
MORPHEUS_LIVE_MUTATION=0
```

It may query health, models, metrics, GPU state, and safe container identity.
It may not send a completion by default because model traffic can affect latency
and metrics. A completion smoke test requires a separate explicit flag.

Any future stateful live test requires `MORPHEUS_LIVE_MUTATION=1`, a named
operation allowlist, pre-state capture, confirmation, rollback, and post-state
identity comparison.

### 3.6 Browser Tests

Playwright covers supported desktop and mobile viewports, keyboard workflows,
accessibility scans, slow responses, partial failures, session expiry, and
visual layout. Screenshot baselines are reviewed artifacts, not substitutes for
semantic assertions.

### 3.7 Desktop and Native OS Tests

The shared React feature suite remains authoritative for UI behavior. Native
Tauri tests add install/bootstrap, minimal capability grants, backend version
handshake, close/reopen, update/rollback, and local versus SSH-tunneled profile
workflows. Target-native integration tests cover paths, ACLs or modes,
process-tree cancellation, per-user service registration, reboot, sleep/resume,
locked files, and removal on Ubuntu, Windows, and macOS.

## 4. Standard Quality Gate

Phase 0 will implement one task runner entry point with these stable commands:

```text
make format-check
make lint
make typecheck
make test-unit
make test-contract
make test-integration
make test-acceptance
make test-e2e
make test-live-readonly
make security
make build
make gate
```

`make gate` runs all required non-live checks from a clean checkout. It does not
download models, inspect private host data, or access the production Docker
project.

## 5. Phase 0: Reproducible Engineering Foundation

### Objectives

- establish Python and frontend packages;
- lock dependencies and tool versions;
- configure formatting, linting, strict typing, tests, coverage, security scans,
  secret scanning, and license inventory;
- create task runner and CI workflows;
- create fixture, artifact, and requirement-traceability conventions.

### First tests

- repository policy test rejects committed `.env`, database, model, secret, and
  generated artifact patterns;
- documentation link test validates local references;
- dependency lock test proves clean, offline reinstall from a populated cache;
- Compose policy test rejects unpinned release images and unsafe host bindings;
- requirement metadata test rejects unknown requirement IDs.

### Implementation notes

- Python baseline: CPython 3.12 with a standard `src/` package layout;
- Python quality: Ruff formatting/lint, strict mypy, pytest, branch coverage,
  Bandit or equivalent static security analysis;
- frontend baseline: TypeScript strict mode, React, Vitest, Testing Library,
  ESLint, and Playwright;
- dependency lock files are committed;
- CI actions and container dependencies are pinned immutably where supported;
- local hooks are convenience only; CI is authoritative.

### Exit criteria

- a clean checkout can bootstrap, check, test, and build with documented commands;
- `make gate` is green and has no skipped required test;
- deliberate formatting, typing, secret, unsafe Compose, and failing-test defects
  are each proven to fail the gate;
- generated output is ignored and the Git worktree stays clean after the gate;
- CI uses least-privilege permissions and no repository secret is needed;
- contributor setup has been followed successfully from a clean environment.

## 6. Phase 1: Domain, Configuration, and Fake Runtime

Requirements: CFG-001 through CFG-004, RUN-001, RUN-002, RUN-005, REL-002,
REL-004.

### Objectives

- implement typed configuration and redaction;
- define domain health, model, service, capability, evidence, and error models;
- define inference, metrics, host, persistence, and clock ports;
- implement deterministic fake adapters;
- implement pure health and capability aggregation.

### First tests

- table-driven configuration precedence and validation acceptance tests;
- state-transition property tests for health freshness and aggregation;
- model discovery contract fixtures covering aliases and schema drift;
- redaction mutation tests with nested and adversarial secret names;
- capability tests proving one failed dependency does not hide another feature.

### Exit criteria

- all configuration and domain exit criteria in the product specification pass;
- core modules import no infrastructure package;
- mutation score for ownership, health, and redaction policy meets the agreed
  threshold of 90 percent or has reviewed equivalent tests;
- public JSON schemas are generated and versioned;
- no live host or Docker access is required by the complete phase gate.

## 7. Phase 2: Read-Only Runtime, API, Agent, and CLI

Requirements: RUN-001 through RUN-006, INV-001 through INV-006, SEC-001 through
SEC-003, REL-001.

### Objectives

- implement OpenAI/vLLM HTTP and metrics adapters;
- implement the read-only runtime agent;
- implement authenticated agent client and protocol;
- implement `/api/v1` health, models, capabilities, and diagnostics;
- implement `morpheus status`, `morpheus models`, and `morpheus doctor`;
- implement protected external-runtime baseline capture.

### First tests

- inference adapter contracts for timeout, cancellation, malformed JSON, multiple
  models, missing fields, and incompatible endpoints;
- metrics parser corpus with unknown and missing metric families;
- agent allowlist and request authentication tests;
- adversarial ownership tests using external container names and forged labels;
- CLI golden tests for human and JSON output and exit codes;
- acceptance test comparing external runtime identity before and after every
  Morpheus command.

### Exit criteria

- the API and CLI report the current vLLM model, aliases, context, health, and
  available metrics accurately in the opt-in live read-only lane;
- the agent is loopback-only and arbitrary command execution is structurally
  impossible through its schema;
- the API contains no Docker socket, subprocess, or NVIDIA command access;
- unauthenticated, expired, replayed, malformed, and over-sized requests fail;
- external resource mutation attempts are rejected and audited;
- disabling or stopping Morpheus has no effect on direct vLLM/Open WebUI use;
- Phase 2 has a packageable read-only release candidate.

## 8. Phase 3: Operational Dashboard

Requirements: UI-001 through UI-005, PERF-003, SEC-004.

### Objectives

- build the operational overview and diagnostics views;
- add authentication and safe session lifecycle;
- display health evidence, model identity, GPU state, request signals, storage,
  and capability blockers;
- establish component and visual design system;
- add accessible responsive behavior.

### First tests

- component tests begin with semantic roles, labels, and states;
- API mock scenarios cover ready, cold-start, degraded, unauthorized, stale,
  empty, partial, and recovery behavior;
- Playwright workflows cover login, overview, diagnostics, refresh, error detail,
  keyboard navigation, and session expiry;
- visual tests cover compact mobile, standard desktop, and wide desktop.

### Exit criteria

- every dashboard exit criterion in the product specification passes;
- no control is rendered for external services;
- a stale metric is visually and semantically distinct from zero;
- automated accessibility scan has no serious or critical issue;
- frontend has no runtime console error in acceptance workflows;
- API failure cannot resize, overlap, or blank the overall interface;
- measured local render and polling budgets pass.

## 9. Phase 4: Search Sidecar

Requirements: SRCH-001 through SRCH-003, SEC-005, SEC-007.

### Objectives

- select and validate an upstream SearXNG release;
- author Morpheus Compose and configuration from upstream documentation;
- attach search to the internal and external shared networks as required;
- add search health, dashboard status, doctor checks, and operator runbook;
- document operator-controlled Open WebUI setup.

### First tests

- Compose contract tests for digest, ownership labels, networks, read-only mounts,
  no host port, logging, health, and resource limits;
- SearXNG JSON contract and failure tests;
- Open WebUI query URL connectivity test from a disposable peer container;
- uninstall integrity test for the external Docker network.

### Exit criteria

- all search exit criteria pass;
- search can be enabled and removed without recreating core Morpheus services;
- Open WebUI can search through Docker DNS after operator configuration;
- no search service is reachable from the LAN by default;
- upstream version, digest, license, and validation evidence are recorded;
- vLLM and Open WebUI identity checks remain unchanged.

## 10. Phase 5: CPU-First Voice

Requirements: VOICE-001 through VOICE-004, SEC-003, REL-001.

### Objectives

- select pinned upstream OpenAI-compatible STT and Kokoro-compatible TTS;
- deploy CPU defaults with bounded memory and concurrency;
- implement behavioral health and Open WebUI compatibility tests;
- implement audio limits, temporary-file cleanup, and retention policy;
- add dashboard status and voice diagnostics.

### First tests

- fixed audio fixture transcription contract;
- generated speech content-type and decoder validation;
- invalid, oversized, slow, canceled, and concurrent request tests;
- temporary-file canary and cleanup tests;
- external runtime identity and vLLM latency control tests.

### Exit criteria

- all voice exit criteria pass;
- CPU voice operation stays within recorded CPU/RAM budgets;
- voice requests do not allocate GPU memory in the default profile;
- Open WebUI microphone upload and response playback work through documented
  settings without database edits;
- temporary audio and request metadata follow the retention policy;
- disabling voice leaves no running process or published port.

## 11. Phase 6: Private Request Telemetry

Requirements: TEL-001 through TEL-005, PERF-001, SEC-001 through SEC-004.

### Objectives

- implement Morpheus's own OpenAI-compatible streaming proxy;
- add authentication, correlation, usage accounting, and bounded retention;
- add usage, latency, errors, and session-health views;
- retain a direct documented vLLM rollback route.

### First tests

- protocol corpus for streaming and non-streaming chat completions;
- byte-timing tests proving early chunk forwarding;
- tools, structured output, errors, cancellation, and disconnect contracts;
- content canary tests across logs, metrics, traces, database, API, and support
  bundle;
- proxy-vs-direct benchmark with defined statistical method.

### Exit criteria

- all telemetry exit criteria pass;
- compatibility tests show no behavior change in approved request shapes;
- overhead budget passes on repeated warm runs;
- proxy failure is bypassable by one documented endpoint rollback;
- database growth is bounded by tested retention;
- clients cannot supply unbounded metric labels or spoof audit identity.

## 12. Phase 7: Workflows, Research, and Optional Gateway

Requirements: FLOW-001, FLOW-002, RSCH-001, RSCH-002, GATE-001 through
GATE-003.

### Objectives

- integrate upstream n8n with Morpheus-owned persistence;
- define and validate curated workflow templates;
- integrate Perplexica with SearXNG and the configured model endpoint;
- evaluate whether LiteLLM solves a demonstrated routing or authentication need;
- keep gateway adoption optional and reversible.

### First tests

- n8n clean-state, migration, credentials, template, and webhook contracts;
- workflow test that calls a fake OpenAI endpoint before live validation;
- research citation and timeout acceptance tests;
- gateway parity corpus comparing direct and routed responses;
- dependency failure tests proving chat and core dashboard remain healthy.

### Exit criteria

- workflow and research exit criteria pass;
- gateway exit criteria pass before any client is directed through it;
- no template contains a credential, fixed host IP, or production-only model ID;
- service backups round-trip on a clean disposable deployment;
- every new browser UI is authenticated and loopback-bound by default;
- optional-service removal preserves other feature state.

## 13. Phase 8: Independent RAG Decision Gate

Requirements: RAG-001 through RAG-003.

This phase begins with a written use case and decision record. It does not begin
because Qdrant or an embedding service is available.

### Decision tests

- measure the unmet retrieval behavior in existing Open WebUI;
- define corpus, relevance judgments, latency, storage, and privacy constraints;
- compare existing behavior with the proposed independent path;
- estimate migration and reindex cost.

### Exit criteria

- the explicit-need requirement is satisfied with reproducible evidence;
- the architecture decision is accepted;
- if approved, all RAG product exit criteria pass before default enablement;
- if rejected, the decision and evidence are recorded and no unused service is
  added to Morpheus.

## 14. Phase 9: ComfyUI and GPU Workload Coordination

Requirements: IMG-001 through IMG-004, INV-001, SEC-002, REL-003.

This is the highest-risk feature phase. It cannot run stateful acceptance tests
against the current server without separate operator authorization.

### Objectives

- integrate upstream ComfyUI through its API;
- define a versioned smoke-test workflow and model inventory;
- implement GPU headroom policy and safe rejection;
- design an operator-controlled inference-to-image transition;
- guarantee recovery to a captured inference baseline.

### First tests

- pure GPU policy tests across memory, temperature, process, ownership, and stale
  observations;
- fake transition state-machine tests with interruption at every edge;
- disposable GPU-lane ComfyUI API and workflow tests;
- external-resource rejection tests for normal Morpheus lifecycle APIs;
- recovery evidence comparison tests.

### Exit criteria

- all image-generation exit criteria pass on dedicated hardware validation;
- concurrent start is rejected on the current 0.95-reserved vLLM configuration;
- no ordinary dashboard action can stop or recreate external inference;
- operator transition requires an explicit command, warning, preflight, and
  confirmation separate from the dashboard's routine service controls;
- injected failure at each transition point recovers or stops with precise manual
  recovery instructions;
- the original inference image, revision, arguments, model IDs, context, and
  behavioral smoke test match after restoration.

## 15. Phase 10: Recovery, Security, and Stable Release

Requirements: OPS-001 through OPS-003, all SEC, REL, and PERF requirements, and
the release-level exit criteria.

### Objectives

- finalize backup, restore, support bundle, migrations, upgrade, rollback, and
  uninstall;
- complete threat model and supply-chain evidence;
- run failure injection, load, accessibility, and 24-hour soak validation;
- publish complete operator runbooks and stable artifacts.

### First tests

- malicious archive and path escape corpus;
- database migration interruption and rollback tests;
- disk-full, read-only filesystem, dependency outage, clock skew, and restart
  fault injection;
- secret/content canaries across every artifact;
- install/upgrade/uninstall external-integrity acceptance tests;
- clean-host documentation walkthrough.

### Exit criteria

- every release-level criterion in the product specification passes;
- all committed requirement IDs map to green evidence;
- no critical or high unresolved vulnerability lacks an approved exception;
- release artifacts are reproducible and include checksums, locks, digests, SBOM,
  migration version, and validation report;
- rollback is demonstrated from the exact candidate artifacts;
- a person other than the implementation author completes the operator runbook;
- the release is explicitly approved for stable use.

## 16. CI and Validation Matrix

| Lane | Trigger | External services | GPU | Mutation |
|---|---|---|---|---|
| Static | every change | none | no | none |
| Unit | every change | fakes | no | temp only |
| Contract | every change | fixtures/fakes | no | temp only |
| Integration | affected changes | disposable | no by default | disposable only |
| Browser | UI/API changes | disposable | no | disposable only |
| Desktop | UI/backend changes | local fake backend | no | temp only |
| Native packaging | release changes | none | no | isolated install root |
| Container policy | deploy changes | rendered config | no | none |
| Security | every change/nightly | disposable | no | disposable only |
| Live read-only | manual/scheduled | production endpoint | observe | none |
| Dedicated GPU | image/runtime changes | lab deployment | yes | lab only |
| Soak | release candidate | isolated candidate | optional | isolated only |

Required checks are path-aware but never omitted for a release candidate.
Static, unit, contract, desktop, and packaging lanes run on native Ubuntu,
Windows, and macOS workers. Hardware qualification remains separate from CI and
records the exact OS, architecture, accelerator, driver/API, engine, model
artifact, and package identities.

## 17. Requirement Traceability and Evidence

The repository will maintain a machine-readable requirements manifest during
Phase 0. Each entry contains:

- requirement ID and specification link;
- delivery phase and status;
- owning acceptance tests;
- relevant contract and integration tests;
- risk classification;
- live or hardware evidence requirement;
- release version that first satisfies it.

CI rejects unknown IDs and requirements marked complete without green evidence.
Release reports are generated from this manifest and immutable CI artifacts.

## 18. Risk Register

| Risk | Consequence | Primary control |
|---|---|---|
| External resource mutation | Working AI service outage | Ownership labels, protected inventory, integrity tests |
| GPU oversubscription | OOM or vLLM crash | CPU defaults, headroom policy, explicit transition |
| Docker privilege exposure | Host compromise | Separate loopback allowlisted agent |
| Moving upstream image | Irreproducible behavior | Digest pins and lock manifest |
| Prompt/content telemetry | Privacy loss | No-content storage default and canary tests |
| Dashboard false green | Delayed diagnosis | Behavioral probes, evidence, stale states |
| Proxy incompatibility | Tool/stream breakage | Direct parity corpus and bypass route |
| Optional-service coupling | Broad outage | Separate health, networks, and lifecycle |
| Database/archive corruption | Lost operational state | Atomic migration/restore and checksums |
| Platform behavior hidden by Python portability | Data loss or orphaned processes | Native path, service, process-tree, and recovery tests |
| Desktop/backend version drift | Broken management or unsafe actions | Compatibility handshake, package-trust-aware update plan, rollback |
| Unsupported engine parity claim | Failed or misleading installation | Evidence-bounded tier matrix and physical qualification |
| Scope growth | Never-stable project | Phase gates, explicit non-goals, ADRs |

## 19. Change Control

Changing an invariant, ownership boundary, security model, public API, persistent
format, external-resource policy, or release exit criterion requires:

1. a new or superseding ADR;
2. specification update;
3. acceptance-test update written before implementation;
4. migration and rollback analysis;
5. explicit review of the affected phase gate.

The plan may evolve, but an exit criterion is not removed merely because an
implementation has difficulty satisfying it.

## 20. v0.2 Delivery Strategy

The v0.2 plan preserves the running ubuntu-1 v0.1 status plane while building a
managed-runtime path in disposable environments. Product work follows this
order:

```text
contract and ownership
  -> Ubuntu CPU managed-inference walking skeleton
  -> evidence-driven self-assessment and bounded replan
  -> portable host/OS foundation and catalogs
  -> benchmark data foundation
  -> deterministic recommendation
  -> cross-platform backend, packaging, and managed engines
  -> Tauri desktop operations workspace
  -> bounded AI diagnosis, browser, and SSH access
  -> Ubuntu, Windows, and Apple Silicon macOS qualification
```

No phase requires adoption of the current ubuntu-1 coder. Observe mode remains
the recovery and comparison path until the managed candidate has independently
passed its target gates and the operator separately authorizes promotion or
adoption.

The primary workload is serious developer inference. Default scoring emphasizes
coding correctness, tool calls, structured output, agentic reliability,
long-context coherence, interactive TTFT, sustained decode, stability, and safe
resource headroom. Every default is versioned and operator-adjustable.

Stable v0.2 is one product contract with native target adapters, not one
identical runtime stack. Native `llama.cpp` is the common engine baseline. vLLM
is an additional stable Linux NVIDIA tier; Ollama is optional, while Windows
vLLM through WSL2 and Apple vLLM-Metal/MLX begin as experimental. ubuntu-1 and
ubuntu-2 remain named Linux targets but do not satisfy Windows or macOS release
evidence.

The dependency and parallel-work boundary is:

| Phase | Entry gate | Parallel work after shared contracts land |
|---:|---|---|
| 11 | v0.1 gate green | immutable record/schema lane, state-machine lane, and observe-mode regression lane |
| 11.5 | Phase 11 contracts fixed | one integrated Ubuntu CPU walking-skeleton lane; do not fan out yet |
| 12 | walking-skeleton assessment and bounded replan committed | platform collectors/ports and catalog validation |
| 13 | Phase 12 machine and catalog identities fixed | legacy import, result storage, and campaign policy |
| 14 | Phase 12 catalogs plus Phase 13 comparable evidence | constraint filtering, scoring profiles, and explanations |
| 15 | Phase 14 immutable deployment plans | engine adapters, acquisition, lifecycle, and target-native backend packaging |
| 16 | Phase 15 compatibility and lifecycle APIs fixed | React workspaces, metrics/logs, Tauri shell, and workstation packaging |
| 17 | Phase 16 authorization and evidence-query APIs fixed | diagnostic providers and local/remote access lanes |
| 18 | all selected requirements implemented | independent physical target evidence lanes and release integration |

An entry gate is a merge dependency, not permission to use a live target.

## 21. Phase 11: v0.2 Contracts and Dual Ownership

Functional requirement: RUNM-001.

Cross-cutting constraints: INV-001 through INV-009 and regression coverage for
all currently implemented v0.1 requirements, especially RUN-001 through
RUN-006, SEC-002, SEC-006, and REL-003.

### Objectives

- introduce exactly two inference ownership modes, `external_observed` and
  `morpheus_managed`, plus workflow-scoped adoption-candidate transfer records
  that are not ordinary runtime identities or lifecycle targets;
- define immutable machine, catalog, workload, recommendation, deployment-plan,
  campaign, comparison, and diagnosis contracts;
- separate staging, benchmark, promotion, rollback, and adoption state machines;
- define audit and confirmation boundaries for every managed operation;
- preserve current API/CLI/dashboard behavior as observe mode.

### First tests

- acceptance tests proving every existing ubuntu-1 operation remains read-only;
- property tests proving resource names and endpoints cannot transfer ownership;
- invalid state-transition tests across install, campaign, promotion, rollback,
  and adoption;
- schema compatibility tests for versioned persisted and API records;
- adversarial agent requests attempting arbitrary paths, flags, URLs, commands,
  or external targets.

### Exit criteria

- v0.1 observe-mode tests remain green without compatibility aliases that weaken
  ownership;
- every state-changing contract identifies one exact managed plan and owned root;
- adoption is impossible through ordinary install, settings, or lifecycle APIs;
- the complete Phase 11 gate runs without GPU access or model downloads.

### Phase 11 implementation handoff

`IMP-RUNM-001-01` is the only implementation task in this phase. Execute it in
this order:

1. A contract owner lands the two ownership modes, exact identity/plan binding,
   schema-version rules, and adoption-record boundary in the dependency-free
   domain core.
2. After that contract is fixed, agents may work in parallel on immutable
   planning-record codecs, the separate lifecycle state machines, and
   observe-mode API/CLI/dashboard regression tests.
3. An integration owner runs the full non-live gate, verifies schema round trips
   and invalid transitions through public boundaries, and updates
   `requirements.json`, the gap review, and `docs/RELEASE_STATE.md` together.

The phase does not implement host collectors, catalog contents, recommendation
algorithms, benchmark execution, model or engine acquisition, persistence
migrations, state-changing management endpoints, desktop UI, or target
packaging. DEV and disposable-VM evidence is sufficient to mark RUNM-001
`implemented`; its required HOST-RO evidence remains a later, separately
authorized validation step before it can be marked `validated`.

## 22. Phase 11.5: Ubuntu CPU Walking Skeleton and Replan Gate

Delivery milestone: VSLICE-001. It exercises provisional slices of HOST, SEL,
BENCH, RUNM, PLAT, and GATE behavior but does not by itself change any of those
functional requirements from `planned` to `implemented`.

### Objectives

- exercise the Phase 11 contracts through one real, narrow, end-to-end managed
  inference path before building the complete horizontal subsystems;
- use an Ubuntu x86-64 disposable lab, CPU-only pinned `llama.cpp`/`llama-server`,
  and a small license-reviewed GGUF artifact with an immutable revision and
  digest stored only in a Morpheus-owned development cache;
- run sanitized discovery, a minimal versioned catalog, deterministic selection,
  verified acquisition, bounded configuration rendering, loopback startup,
  OpenAI-compatible behavioral health, a short benchmark, promotion, rollback,
  and cleanup through public API or CLI boundaries;
- keep the offline CI lane deterministic with fixtures while requiring one real
  disposable `llama-server` run before the milestone exits;
- produce evidence about the contracts rather than polishing this narrow path
  into a premature platform implementation.

### First tests

- one acceptance chain proving machine, catalog, recommendation, deployment,
  acquisition, campaign, promotion, and rollback records retain the same exact
  correlated identities;
- digest mismatch, interrupted acquisition, low disk, invalid engine setting,
  startup timeout, failed health, benchmark abort, failed promotion, rollback,
  process-tree cleanup, and repeated-command cases;
- promotion from a known-good plan A to a distinct candidate plan B, followed by
  forced failure or explicit rollback that restores A and its behavioral health;
- protected external identity snapshots before and after the slice, proving no
  existing inference, Open WebUI, shared network, cache, or persistent data was
  changed;
- restart/resume tests proving durable checkpoints neither skip confirmation nor
  duplicate acquisition, process, campaign, or cleanup work.

### Self-assessment and bounded replan

After the slice passes, the integration owner writes
`docs/VERTICAL_SLICE_ASSESSMENT.md` with:

- the exact commands, artifact identities, environment, tests, and retained
  redacted evidence needed to reproduce the slice;
- which Phase 11 contracts survived unchanged and which caused duplication,
  unsafe coupling, lossy serialization, unclear ownership, or recovery friction;
- measured versus estimated CPU, RAM, storage, startup, TTFT, decode, and cleanup
  behavior, clearly labeled as development evidence rather than support data;
- every schema, state-machine, port, task-decomposition, or phase-order change
  recommended before broader implementation;
- a go, bounded-replan, or stop-and-escalate decision with unresolved risks and
  rollback.

Agents may autonomously apply evidence-backed changes to internal architecture,
schemas, adapters, task decomposition, and this implementation sequence, adding
or superseding ADRs as required. They must rerun the Phase 11 and VSLICE-001
gates after the replan. A proposed change to product scope, an invariant,
external-resource policy, live authorization, privacy policy, or the stable
support matrix requires explicit user review; otherwise the agents continue to
Phase 12 after the bounded replan is green.

### Exit criteria

- the real disposable CPU lane completes discovery through rollback and cleanup
  without an orphan process, unowned file, leaked credential, or external-state
  change;
- plan A is behaviorally healthy after plan B is rolled back;
- fixtures reproduce every failure found during the real run;
- the assessment and any bounded plan/ADR/schema updates are committed with a
  green non-live gate;
- no Windows, macOS, GPU, desktop, public signing, or stable-support claim is
  inferred from this milestone.

## 23. Phase 12: Portable Host Discovery and Catalogs

Requirements: HOST-001, HOST-002, SEL-001, PLAT-001, and PLAT-002.

### Delivery subphases

| Subphase | Primary IDs | Deliverable | Gate |
|---:|---|---|---|
| 12.1 | HOST-001, HOST-002, PLAT-001 | normalized machine/profile schemas and portable read-only collectors | stable fingerprint and missing-evidence fixtures green |
| 12.2 | PLAT-002 | Linux, Windows, and macOS owned-path, secret, process, service, replacement, and telemetry adapters | target-native contract suites clean up every disposable resource |
| 12.3 | SEL-001 | versioned model/engine catalog schemas, trust policy, and minimal reviewed seed catalogs | parser, provenance, freshness, and historical-version tests green |
| 12.4 | HOST-001, HOST-002 validation follow-up | privacy review, export format, and guarded real-host capture lanes | source lane green; each available host capture retained separately as HOST-RO evidence |

### Objectives

- implement normalized machine profiles and platform-specific collectors;
- record stable identity separately from volatile utilization observations;
- collect CPU, memory, accelerator, topology, storage, OS, driver/API, container,
  and engine-prerequisite evidence through allowlisted read-only operations;
- define signed/checksummed model and engine catalog schemas, provenance,
  freshness, license, formats, features, and compatibility expressions;
- define and implement typed hardware-telemetry, process-supervisor,
  service-manager, filesystem/owned-path, durable-replacement, and secret-store
  ports with separate Linux, Windows, and macOS adapters;
- implement portable system collection plus Linux/NVIDIA, Windows/DXGI/vendor,
  and Apple Metal collectors with explicit unavailable and permission states;
- prepare guarded capture lanes and, when separately authorized and available,
  capture initial privacy-reviewed profiles from ubuntu-1, ubuntu-2, one Windows
  11 x86-64 host, and one Apple Silicon macOS host.

### First tests

- fixtures for NVIDIA, non-NVIDIA, CPU-only, multi-device, partial permission,
  stale driver, low storage, and unknown platform cases;
- stable-profile fingerprint tests with volatile fields changing;
- catalog parser tests for unknown fields, unsafe URLs, duplicate identities,
  digest/revision drift, invalid constraints, and expired evidence;
- host-agent allowlist and support-claim tests;
- Windows drive, UNC, junction/reparse-point and ACL cases; POSIX symlink/mode
  cases; process-tree termination and service capability fixtures.

### Exit criteria

- sanitized target-shape fixtures prove discovery is read-only, repeatable,
  exportable, and contains no secret values; real captures remain required for
  `validated` and support claims but unavailable hardware does not block the
  Phase 13 source lane;
- catalog versions reproduce old inputs and never mutate installed plans;
- unsupported hardware and inaccessible telemetry are reported honestly;
- platform adapter contract suites pass in disposable target-native labs and
  cleanup leaves no registered service, child process, credential, or owned-path
  fixture behind;
- no compatibility result installs software or probes with a completion request.

## 24. Phase 13: Benchmark Data Foundation and History Import

Requirements: BENCH-001 through BENCH-005.

### Delivery subphases

| Subphase | Primary IDs | Deliverable | Gate |
|---:|---|---|---|
| 13.1 | BENCH-002, BENCH-003 | immutable benchmark entities, schema migrations, content-addressed raw store, and reducers | round-trip, migration, backup, restore, and regeneration tests green |
| 13.2 | BENCH-003 | checksummed history import and limitation mapping | every supported history shape imports without altering or inventing provenance |
| 13.3 | BENCH-001, BENCH-005 | authorized campaign runner with limits, checkpoints, cancellation, and cleanup | disposable fixture campaigns survive interruption without leaked work |
| 13.4 | BENCH-002, BENCH-004 | comparability, summaries, regressions, export, and cross-host review | decision tables and public query boundaries green |

### Objectives

- define the canonical developer benchmark suite and versioned run contracts;
- persist raw samples, provenance, summaries, comparison classification,
  dispersion, errors, and regression decisions;
- import existing `history-tool-tests` JSONL and reports without altering their
  source files or inventing missing provenance;
- correlate machine, model, engine, configuration, software, and benchmark
  revisions;
- add safe campaign authorization, resource limits, stop conditions, and cleanup.

### First tests

- golden imports for speed, coding, tools, long-context, context-bump, MTP, and
  supporting-software before/after histories;
- schema-migration and content-addressed artifact tests;
- direct-comparability, normalized-estimate, and incomparable decision tables;
- cache contamination, incomplete runs, outliers, cancellation, timeout, and
  resource-abort cases;
- backup, restore, export, and cross-host review tests.

### Exit criteria

- all existing history campaigns are discoverable with original checksums and
  explicit limitations;
- one new fixture campaign produces raw, summary, and comparison records through
  public application boundaries;
- a single percentage cannot be shown without sample count, statistic, baseline,
  configuration, and comparability;
- campaign interruption leaves no live workload and remains resumable or safely
  terminal according to its contract.

## 25. Phase 14: Constraint Solver and Explainable Recommendation

Requirements: SEL-002 through SEL-005.

### Delivery subphases

| Subphase | Primary IDs | Deliverable | Gate |
|---:|---|---|---|
| 14.1 | SEL-002 | hard compatibility and resource constraint solver | rejected tuples cannot enter ranking under any weight |
| 14.2 | SEL-003 | versioned developer workloads, estimates, margins, and operator constraints | deterministic and monotonic fixtures green |
| 14.3 | SEL-004 | evidence comparability, confidence, calibration, and weighted ranking | stale, foreign-machine, estimated, and measured evidence remain distinct |
| 14.4 | SEL-004, SEL-005 | immutable recommendation records and API/CLI/initial React explanations | byte-equivalent replay and complete exclusion/tradeoff explanations green |

### Objectives

- reject incompatible model, quantization, engine, context, concurrency, and
  configuration tuples using hard constraints;
- add versioned developer workload profiles and operator-defined weights;
- estimate accelerator/RAM/storage use with declared margins and confidence;
- rank viable plans using comparable evidence and explicit uncertainty;
- expose exclusion reasons, tradeoffs, catalog freshness, and recommendation
  reproducibility through API, CLI, and initial UI views.

### First tests

- deterministic Ubuntu/NVIDIA, Windows/NVIDIA, Apple Silicon, CPU-only, and
  ubuntu-1/ubuntu-2 ranking fixtures;
- tables for required tool/structured-output/long-context features, memory and
  storage pressure, unsupported engines, trust/license policy, and stale catalogs;
- monotonicity tests for harder resource limits and changed workload weights;
- explanation tests proving every score and exclusion maps to input evidence;
- calibration tests comparing estimates with imported measured campaigns.

### Exit criteria

- identical versioned inputs produce byte-equivalent recommendation records;
- no rejected tuple can re-enter through ranking weights;
- recommendations show confidence and never imply measured target performance
  when only estimates or another machine's results exist;
- changing weights previews a new recommendation without changing installed or
  active state.

## 26. Phase 15: Managed Models, Engines, and Serving

Requirements: RUNM-002 through RUNM-006, PLAT-003, and GATE-001. Existing
GATE-002 and GATE-003 behavior remains a regression contract. GATE-001 is the
bounded single-endpoint compatibility layer for managed inference, not a
LiteLLM or broad multi-provider control plane.

### Delivery subphases

| Subphase | Primary IDs | Deliverable | Gate |
|---:|---|---|---|
| 15.1 | RUNM-003 | verified resumable model/engine acquisition, reservations, quotas, cache, and cleanup | interruption, corruption, low-disk, license, and owned-path suites green |
| 15.2 | RUNM-004, RUNM-005, RUNM-006 | engine-neutral staging, campaign, promotion, rollback, removal, and disposable adoption orchestration | every state edge and recovery checkpoint passes fault injection |
| 15.3 | RUNM-002 | productionized native `llama.cpp` adapters on Linux, Windows, and Apple Silicon macOS | target-native DEV/lab API, process, metrics, lifecycle, and recovery suites green |
| 15.4 | RUNM-002, RUNM-006, GATE-001 | Linux NVIDIA vLLM tier and bounded stable compatibility endpoint with direct bypass | parity, exclusive-resource, failure, and bypass suites green |
| 15.5 | PLAT-003 | independently versioned backend services and checksummed target-native developer packages | install, restart, upgrade, rollback, uninstall, manifest, scan, and SBOM gates green |

### Objectives

- integrate the Phase 12 native-process, Docker Compose, process-supervision,
  and per-user OS service adapters with managed engines without making Docker
  the portable lifecycle boundary;
- freeze and validate native `llama.cpp`/`llama-server` as the common stable
  engine path and vLLM as an additional Linux NVIDIA tier;
- classify Ollama as optional and WSL2 vLLM plus Apple vLLM-Metal/MLX as
  experimental until their complete evidence lanes pass;
- implement immutable, verified, resumable model and engine acquisition;
- render bounded typed engine configurations from deployment plans;
- stage candidates, validate OpenAI-compatible developer features, benchmark,
  promote, observe, upgrade, roll back, and remove managed runtimes;
- preserve direct bypass and last-known-good recovery;
- design but do not automatically execute adoption of ubuntu-1's current coder;
- build a separately versioned frozen backend for each target and register it as
  a per-user systemd service, Windows background application, or macOS LaunchAgent;
  keep elevated always-on service mode deferred;
- reproducibly build, checksum, scan, and inventory each target-native
  backend/service payload on a native target runner and publish its SBOM;
  workstation desktop installers and formats are delivered in Phase 16 after
  the Tauri shell exists, while public signing remains an optional final lane.

### First tests

- engine capability and configuration corpora across supported versions;
- download checksum/signature, disk reservation, partial resume, license/trust,
  cache quota, and cleanup cases;
- state-machine interruption at every acquisition and promotion edge;
- streaming, tools, structured output, reasoning policy, cancellation, usage,
  model identity, metrics, logs, and health parity;
- exclusive-device and foreign-process safety cases;
- install/restart/upgrade/rollback/uninstall in disposable target-like labs;
- native process-tree cancellation, locked-file, sleep/resume, reboot,
  interrupted-update, low-disk, service-registration, and credential-protection
  cases on every target OS.

### Exit criteria

- the backend exposes an authenticated compatibility handshake containing API
  and backend versions, platform, adapters, operations, and compatibility state;
- each implemented engine tier passes its target-native disposable integration
  lane; it remains unvalidated and unadvertised as stable until Phase 18 retains
  the complete physical OS/architecture/accelerator evidence lane;
- staged candidates cannot receive active traffic before promotion;
- failed promotion restores the exact previous plan and behavioral health;
- removal cannot escape owned caches, artifacts, configuration, state, or labels;
- current external inference remains unchanged throughout ordinary development
  and qualification.

## 27. Phase 16: Focused Operations Workspace

Requirements: OUI-001 through OUI-006, DESK-001, DESK-002, UI-001 through UI-005,
TEL-001 through TEL-005, RUN-003, RUN-004, and PERF-003.

### Delivery subphases

| Subphase | Primary IDs | Deliverable | Gate |
|---:|---|---|---|
| 16.1 | UI-003, OUI-001 | versioned operations query models, navigation, partial states, and compatibility APIs | component, API, accessibility, and stale/error fixtures green |
| 16.2 | OUI-002, OUI-003, OUI-004 | metrics rollups, approved redacted logs/events, analytics, and comparisons | retention, redaction, units, gaps, bounds, and correlation suites green |
| 16.3 | OUI-005, OUI-006 | settings, managed workflows, progress/cancellation, and recovery UI | plan preview, confirmation, restart, rollback, reconnect, and session-expiry suites green |
| 16.4 | DESK-001, DESK-002 | minimal-capability Tauri shell with local/browser/SSH-profile parity | capability, close/reopen, backend mismatch, and browser fallback suites green |
| 16.5 | DESK-002 | checksummed Linux, Windows, and macOS developer packages and package-trust-aware bootstrap/update | native install/repair/update/rollback tests green; unattended unsigned update impossible |

### Objectives

- evolve the current React shell into the focused navigation model and package
  it in a Tauri 2 desktop shell for Windows, Linux, and macOS;
- keep the React workspace and versioned API shared with the loopback browser
  surface; grant the Tauri webview no general shell or filesystem capability;
- implement local backend discovery, authenticated compatibility handshake, and
  confirmed package-trust-aware install/repair/update flows without tying the
  service to the desktop window lifecycle;
- package the workstation development delivery as checksummed Linux `.deb` and
  AppImage artifacts, a Windows MSI, and a macOS DMG; label unsigned artifacts,
  disable unattended update for them, keep desktop/backend versions independent,
  and retain a backend-only installation path for headless hosts;
- wire live vLLM/engine metrics and bounded historical rollups;
- implement redacted log/event ingestion, search, filtering, correlation, and
  retention;
- expose model/engine plans, benchmark history, comparisons, analytics, settings,
  lifecycle progress, and recovery;
- generate settings forms from typed schemas with plan preview and rollback;
- retain accessibility, responsive behavior, honest partial states, and strict
  browser authorization.

### First tests

- component/API/browser states for every workspace and empty/slow/stale/error
  condition;
- chart unit, gap, timezone, aggregation, and accessibility tests;
- log-redaction, bounded-query, injection, correlation, and retention tests;
- settings source/default/secret/diff/preflight/restart/rollback tests;
- lifecycle refresh, cancellation, reconnect, duplicate submit, and session
  expiry during long operations;
- visual evidence for an Ubuntu desktop client and for tunneled ubuntu-1,
  ubuntu-2, and mobile browser viewports;
- target-native desktop install, close/reopen, backend restart, reboot,
  version-mismatch, update rollback, and browser-fallback workflows.

### Exit criteria

- operators can answer what is installed, why it was selected, how it is
  performing, what changed, and how to recover without reading raw Docker state;
- request metrics and benchmark history are real application data, not static
  cards or ignored artifacts;
- no UI action bypasses ownership, typed plans, confirmation, or agent policy;
- Windows, Linux, and macOS desktop artifacts pass checksum, capability,
  accessibility, security, polling/event, render, and backend-compatibility
  development gates; equivalent browser workflows remain green, and no stable
  target claim is made before Phase 18 physical qualification.

## 28. Phase 17: AI-Assisted Diagnosis and Secure Access

Requirements: AID-001 through AID-004, ACCESS-001, ACCESS-002, and DESK-003.

### Delivery subphases

| Subphase | Primary IDs | Deliverable | Gate |
|---:|---|---|---|
| 17.1 | AID-001 | bounded redacted diagnostic evidence packages and ordinary non-AI diagnosis | canary, size, provenance, and prompt/log-injection corpora green |
| 17.2 | AID-002, AID-003, AID-004 | disabled, local, and external provider adapters with grounded structured findings | timeout, malformed, hallucination, refusal, cost, consent, and advisory-boundary suites green |
| 17.3 | ACCESS-001, DESK-003 | loopback and operator-established SSH-tunnel access profiles | teardown, revocation, reconnect, cookie, CSRF, and parity suites green |
| 17.4 | ACCESS-002, DESK-003 | optional TLS-authenticated network profile and remote desktop/browser parity | exposure, certificate, origin, proxy-header, brute-force, and recovery suites green |

### Objectives

- create bounded redacted diagnostic evidence packages;
- implement disabled, local-model, and external-API provider adapters;
- require explicit data-destination, retention, timeout, and cost policy;
- return structured grounded findings with citations, confidence, and missing
  evidence;
- keep every suggestion advisory and route proposed checks or changes through
  typed Morpheus policy;
- qualify SSH-tunnel access and an optional TLS-authenticated network profile;
- allow the desktop to attach to local or operator-tunneled remote backends with
  identical API, authorization, progress, cancellation, and recovery semantics.

### First tests

- privacy canaries and adversarial prompt/log injection corpora;
- provider timeout, refusal, malformed output, hallucinated evidence, unsafe
  action, and cost/size-limit cases;
- deterministic grounding and uncertainty evaluation fixtures;
- proof that diagnostic output cannot call the runtime agent or lifecycle port;
- SSH teardown, session revocation, TLS, origin, cookie, CSRF, proxy-header,
  brute-force, and exposure tests.

### Exit criteria

- ordinary diagnostics remain complete when AI diagnosis is disabled or broken;
- every material AI claim cites available evidence or is labeled unsupported;
- no prompt, response, secret, raw credential, or unapproved log content reaches
  any provider;
- local/SSH remains the default and optional network access is independently
  secured and documented.

## 29. Phase 18: Three-OS Physical Qualification

Requirements: HOST-003, PLAT-004, ACCESS-003, all v0.2 requirements assigned to
the selected release, and the applicable original security, reliability,
performance, backup, and release requirements.

### Delivery subphases

| Subphase | Primary IDs | Deliverable | Gate |
|---:|---|---|---|
| 18.1 | HOST-003, PLAT-004, ACCESS-003 | frozen target/support matrix, native package manifests, runbooks, and evidence tasks | every claim maps to an exact artifact, machine, lane, and rollback path |
| 18.2 | HOST-003, PLAT-004, ACCESS-003 | Ubuntu, ubuntu-1, and ubuntu-2 physical lanes | named Linux discovery, managed-runtime, lifecycle, access, and recovery evidence green |
| 18.3 | HOST-003, PLAT-004, ACCESS-003 | Windows 11 x86-64 physical lane | native `llama.cpp`, desktop/backend, package, lifecycle, access, and recovery evidence green |
| 18.4 | HOST-003, PLAT-004, ACCESS-003 | Apple Silicon macOS physical lane | native `llama.cpp`, desktop/backend, package, lifecycle, access, and recovery evidence green |
| 18.5 | all selected v0.2 requirements | cross-target comparison, independent operator walkthrough, and developer/source release report | all three stable OS lanes green and unsupported combinations explicit |

### Objectives

- run clean target installs on ubuntu-1 and ubuntu-2, one Windows 11 x86-64
  NVIDIA host, and one Apple Silicon macOS host;
- qualify discovery, recommendation, acquisition, engine startup, API features,
  benchmark campaigns, operations UI, logs, analytics, settings, diagnosis,
  backup, restore, upgrade, rollback, uninstall, and access;
- compare predicted and measured resource/performance envelopes;
- complete fault, resource, short-soak, and full-soak validation;
- build artifacts on native runners and publish checksummed backend and desktop
  developer packages, catalogs, target profiles, runbooks, SBOMs, evidence maps,
  package qualification levels, and explicit support statements;
- classify AMD Windows, Intel Mac, WSL2 vLLM, vLLM-Metal/MLX, and additional
  Linux distributions as experimental until equivalent physical evidence exists.

### Exit criteria

- Ubuntu 26.04 x86-64, Windows 11 x86-64, and macOS 14+ on Apple Silicon each
  have one documented native `llama.cpp` developer-inference path with tested
  last-known-good recovery; Linux NVIDIA additionally qualifies vLLM;
- ubuntu-1 and ubuntu-2 retain their separate named-machine evidence;
- recommendation claims match actual target evidence and expose material
  differences between the machines;
- all observed external resources remain unchanged unless a distinct adoption
  authorization and report exists;
- an independent operator follows the complete install-to-recovery workflow;
- the release report distinguishes supported, experimental, deferred, and
  unsupported model/engine/platform combinations without optimistic inference;
- no stable v0.2 release is declared until every three-OS stable lane passes.

## 30. v0.2 Priority Boundary

The following remain outside the focused v0.2 critical path even where v0.1
source primitives exist:

- SearXNG/Open WebUI search rollout;
- voice integration and GPU voice profiles;
- n8n template expansion and Perplexica research;
- independent RAG;
- ComfyUI and inference-to-image transitions;
- a broad multi-provider or fleet-wide control plane;
- chat, training, fine-tuning, and quantization production workflows.

Reopening one of these areas requires a concrete need, interaction analysis with
managed inference, updated requirements and priority, and explicit review. It
must not delay the first complete Ubuntu, Windows, and Apple Silicon macOS
developer-inference release by default.

## 31. Optional Signed-Distribution Hardening

This post-qualification lane is deliberately outside the source-development and
developer/source release critical path. Agents attempt it only when the required
external accounts, identities, credentials, agreements, and operator authority
are available:

1. sign Windows backend and MSI artifacts and verify signatures on a clean host;
2. sign macOS backend and application bundles, notarize the DMG, staple and
   verify the result, and repeat install/update/rollback on a clean host;
3. apply any selected Linux repository/package signing policy and verify it from
   a clean installation root;
4. sign update metadata, enable unattended update only for the matching trusted
   channel, and exercise compromise, expiry, revocation, downgrade, and rollback
   cases;
5. publish a signed-distribution-qualified report bound to the already qualified
   source revision and exact package digests.

Missing credentials produce a documented `not_configured` optional-lane result,
not a failed product phase. Agents must not solicit, generate, retrieve, or store
private signing material as a workaround. Developer/source-qualified artifacts
remain checksummed, scanned, SBOM-backed, explicitly confirmed, and usable with
documented platform trust steps; they never claim unattended trusted update.

## 32. Optional Public Open-Source Publication

The current package metadata says `Proprietary - no license granted`. Product
implementation, testing, packaging, and private/source-available qualification
continue under that status. Public repository visibility does not itself grant
an open-source license, and agents must not select legal terms on the operator's
behalf.

If the operator explicitly chooses an open-source publication policy, the final
publication lane must:

1. add the selected `LICENSE` and align package, installer, documentation, and
   source-header metadata without retroactively relicensing third-party work;
2. regenerate and review third-party license inventories and notices against the
   chosen distribution policy;
3. finalize contribution terms, DCO/CLA policy if any, governance expectations,
   security reporting, release ownership, and trademark/name guidance;
4. verify that source archives, generated clients, bundled engine/model
   components, fixtures, documentation assets, and binary packages contain only
   material that may be redistributed under the declared policy;
5. publish an explicit source and artifact provenance statement.

An undecided license is a publication blocker, not a development blocker. Agents
record it as `decision_pending` and finish every independent product task without
claiming that Morpheus is open source.
