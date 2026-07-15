# Morpheus TDD Implementation Plan

Status: Proposed

Plan version: 0.1

Requirements source: [PRODUCT_SPECIFICATION.md](PRODUCT_SPECIFICATION.md)

Architecture source: [ARCHITECTURE.md](ARCHITECTURE.md)

## 1. Delivery Policy

Morpheus is delivered as a sequence of independently useful, releasable phases.
No phase begins by deploying into the production server. Behavior is first
specified through tests, implemented against fakes and disposable dependencies,
then validated through an explicitly authorized live lane.

The active inference and Open WebUI services are protected fixtures, not a
development sandbox. Live tests are read-only until a later requirement
explicitly authorizes a state transition.

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
| Container policy | deploy changes | rendered config | no | none |
| Security | every change/nightly | disposable | no | disposable only |
| Live read-only | manual/scheduled | production endpoint | observe | none |
| Dedicated GPU | image/runtime changes | lab deployment | yes | lab only |
| Soak | release candidate | isolated candidate | optional | isolated only |

Required checks are path-aware but never omitted for a release candidate.

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
