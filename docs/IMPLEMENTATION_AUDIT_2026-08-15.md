# Morpheus v0.2 Implementation Audit — 2026-08-15

Status: Historical audit; reproduced against final implementation source and
superseded for execution by `RECTIFICATION_PLAN.md`

Audited source: `c955adf6f0fa63983d34f3b58f027d5fcef43ab9`

Repository visibility at audit time: GitHub reported the repository as
`PRIVATE`. This document nevertheless contains no secrets, credentials, prompt
content, private runtime data, or authorization for live-host changes.

## Purpose

This is a dated review snapshot of the Phase 11 through Phase 16.2 v0.2 work.
It preserves concerns that should be reconciled after the implementation agent
finishes the planned source phases. It is not a replacement for
`requirements.json`, not proof that a finding still exists on a later revision,
and not authorization to interrupt otherwise green, in-scope DEV work.

Before acting on a finding, reproduce it against the then-current source. Close
or supersede findings with code, tests, and evidence rather than deleting this
historical snapshot.

## 2026-08-22 Disposition

All eight findings were reproduced against final GitHub source
`9b4cda09d4b064f160902b9dd25387cf3129cdb3`; none is closed. Phase 16.3 added a
workflow UI and runner, but its production route uses `DevWorkflowExecutor`,
which intentionally performs no managed mutation, so AUD-003 remains critical.
Later phases also introduced deferred-scope, desktop/native-package, diagnosis,
and target-support overclaims.

The current evidence, corrected requirement posture, dependency order, tests,
and closure gates are in the active
[`architecture rectification plan`](RECTIFICATION_PLAN.md). Preserve the detail
below as historical finding provenance; do not use its old “after the current
implementation run” wording as the active queue.

## Executive Assessment

Overall assessment at the audited revision: **B- / approximately 7 out of 10**.

The implementation is strong at bounded component engineering, typed domain
logic, adversarial tests, owned-path enforcement, and external-runtime safety.
It is weaker at composing the components into one product, preserving a single
identity model across phases, and matching `implemented` requirement status to
the complete behavior in the product specification.

The central risk is not generally poor code. It is that individually credible
subsystems and large green test counts can make end-to-end completeness look
greater than it is.

## Verified Strengths

- The phase order followed the dependency plan and included the mandatory
  VSLICE-001 acquire-to-rollback exercise before broader implementation.
- Observe-mode and external-resource boundaries remain explicit. No ordinary
  managed action is allowed to infer ownership from a resource name or endpoint.
- Core modules use immutable records, typed settings, bounded identifiers,
  structured parsers, and injected side-effect ports extensively.
- Acquisition, benchmark persistence, state machines, package verification,
  redaction, recovery, and owned-path behavior have substantial negative and
  fault-injection coverage.
- The operations UI handles unavailable, partial, stale, and empty data more
  honestly than a typical early-stage dashboard.
- At the audited revision, the following non-live checks passed:
  - Ruff formatting and lint;
  - strict mypy over 106 source files;
  - 899 unit/repository tests passed, 1 skipped;
  - 356 marker-selected contract tests passed;
  - 29 integration tests passed;
  - 20 marker-selected acceptance tests passed;
  - 1 Python end-to-end test passed;
  - the complete coverage invocation passed 1,383 tests with 1 skip and 90.41%
    branch-aware coverage.

## Findings to Reconcile

### AUD-001 — Canonical planning identities fragmented after Phase 11

Severity: high

`core/records.py` defines the comprehensive Phase 11 `DeploymentPlan` used by
the walking skeleton. `core/deployment.py` later defines a second, incompatible
`DeploymentPlan` with a smaller schema. There are also parallel workload and
identity types in `core/records.py`, `core/workload.py`, `core/models.py`, the
catalog, solver, recommendation, and deployment modules.

The duplication is not merely separate read and write DTOs with an explicit
mapping boundary. The Phase 15 orchestration does not consume the Phase 11 plan
used by the vertical slice. Consequently, the repository does not yet have one
demonstrable identity chain from machine/catalog/workload inputs through
recommendation, acquisition, benchmark, promotion, rollback, and analytics.

Reconciliation target:

- select one canonical immutable plan and identity family;
- make boundary DTOs map explicitly to and from it;
- reject lossy mappings;
- prove that one exact plan ID survives the complete public workflow and restart.

### AUD-002 — Recommendation product path does not use its evidence foundation

Severity: critical

The public recommendation endpoint uses `SEED_CATALOG` directly rather than the
persistent versioned `CatalogRepository`. It does not load imported or measured
benchmark evidence from `BenchmarkStore`; `recommend_for_host` supplies resource
estimates only. It also uses the host observation timestamp as
`reference_machine_id`, which is not a stable machine identity.

`RecommendationRecord` preserves profile, constraints, budget, ranking, and
exclusions, but does not preserve the catalog versions/digests, complete machine
profile, raw evidence identities, estimates, and known unknowns required by
INV-008. Tests prove deterministic replay only when callers inject the same
creation timestamp; the ordinary API creates a new timestamp for each request.

Reconciliation target:

- load an exact persisted catalog version and stable machine profile;
- correlate applicable benchmark evidence and classify foreign/stale/estimated
  evidence explicitly;
- preserve all replay inputs and evidence identities in the immutable record;
- prove byte-equivalent ranking replay from the recorded inputs;
- ensure a recommendation maps losslessly to the canonical deployment plan.

### AUD-003 — Managed-runtime components are not yet one application workflow

Severity: critical until Phase 16.3 is complete

Acquisition, campaigns, deployment state machines, engine runtimes, compatibility
routing, packages, and backend service lifecycle exist as tested modules. At the
audited revision, they are not composed by a single application service or
public API/CLI workflow. Most production references to the acquisition and
deployment types remain inside their defining modules; tests provide the hooks.

Phase 16.3 is expected to add operator-facing managed workflows, so this finding
may be resolved by planned work. It must not be closed merely because forms and
routes exist: the test must cross the real composition boundary from an
authenticated plan preview through durable progress, cancellation/reconnect,
confirmation, activation, failure recovery, rollback, and audit evidence.

### AUD-004 — OUI-002 is a useful metrics foundation, not the full requirement

Severity: high

The rollup, gap, retention, freshness, source-state, SQLite, API, and chart
primitives are good. The product requirement additionally names accelerator
power, token rates, TTFT, throughput, errors, restarts, and other operational
signals. Several are absent from collection and the UI. `temperature_c` is not
declared in `SIGNAL_UNITS`, so it is exposed as the default unit `count`.

Collection currently occurs as a side effect of a metrics GET request. Without
an operator polling the Hardware workspace, no durable background history is
created. This does not yet support a reliable historical operations workspace.

Reconciliation target:

- define the complete typed signal registry and units;
- add bounded periodic collection independent of page views;
- retain explicit unavailable semantics for unsupported signals;
- cover restart, collector failure, retention, clock change, and multi-engine
  transitions;
- test each product-specified signal through collector, store, API, parser, and
  accessible UI presentation.

### AUD-005 — OUI-003 has storage and display but no production ingestion/search

Severity: high

Event normalization, redaction-before-persistence, bounded filters, SQLite
storage, API output, and UI filtering exist. No production source outside the
SQLite adapter calls `record_event` at the audited revision. Tests insert rows
directly. The UI filters the returned page by source and severity, but there is
no bounded message search and no service/engine log ingestion pipeline.

The events endpoint queries rows before pruning expired rows, so a row outside
retention may be returned once and only then deleted.

Reconciliation target:

- ingest only explicitly approved API, agent, and engine sources;
- redact before every persistence and display boundary;
- add bounded server-side search and correlation filters;
- prune before query or otherwise guarantee expired records are never returned;
- prove privacy canaries through a real producer-to-UI integration lane.

### AUD-006 — Engine shutdown bypasses platform process-tree supervision

Severity: high

Phase 12 supplies Windows and POSIX `ProcessSupervisionPort` implementations for
whole-tree termination. `NativeEngineRunner` instead launches a plain
`subprocess.Popen`, and `EngineRuntime.stop` calls terminate/kill only on that
handle. The engine runtime does not use the platform supervision port. A launcher
or engine child process can therefore survive cleanup.

The engine allowlist is also disconnected from the real walking-skeleton
evidence: VSLICE-001 exercised llama.cpp b10400, while the production adapter's
`KNOWN_GOOD_BUILDS` does not include b10400.

Reconciliation target:

- launch in an owned process group/job object appropriate to the target OS;
- route graceful and forced shutdown through the platform supervision contract;
- use the exact evidence-backed engine catalog rather than a disconnected
  hard-coded allowlist;
- add real child-process, interruption, locked-file, sleep/resume, and orphan
  tests on each target-native lab.

### AUD-007 — Requirement traceability can validate the appearance of ownership

Severity: high

The manifest test confirms that an implemented requirement names at least one
existing test file. It does not prove that the test asserts the requirement.
For example, RUNM-003, RUNM-004, and RUNM-005 cite only backend service tests in
the audited manifest, although their product behavior concerns acquisition,
staging, benchmarking, promotion, rollback, and adoption. The acquisition and
deployment suites are not named as owners.

Some per-lane counts are also misleading: the marker-filtered contract target
deselected 72 collected tests, and the marker-filtered acceptance target
deselected 6. The later coverage lane runs them, but handoff counts should say
whether they represent collected, selected, passed, skipped, or deselected tests.

Coverage omits `src/morpheus/api/app.py` and `src/morpheus/agent/app.py`, which
are the two most important composition/security roots. This allows high overall
coverage while end-to-end route composition remains incomplete.

Reconciliation target:

- make owning-test lists cumulative and semantically reviewed;
- add requirement IDs to the tests or machine-readable test metadata;
- require at least one public-boundary acceptance test for each implemented
  product behavior, not only a component test;
- include the API and agent composition roots in a meaningful coverage or
  explicit route/operation matrix;
- report selected/pass/skip/deselect counts accurately.

### AUD-008 — Documentation ledgers contain contradictory current-state claims

Severity: medium

At the audited revision, `AGENTS.md` and the end of `RELEASE_STATE.md` identify
Phase 16.3 as next, while earlier `RELEASE_STATE.md`, `README.md`, and
`IMPLEMENTATION_GAP_REVIEW.md` passages still say that v0.2 implementation has
not started or that Phase 11.5 is next. The manifest count is current, but the
human-readable disposition is not.

Reconciliation target:

- retain historical release evidence without presenting it as the active queue;
- make one clearly identified current-state section authoritative;
- update or mark superseded snapshots after every phase boundary;
- add documentation assertions for the active phase and inventory counts.

## Recommended Cleanup Order

After the implementation agent finishes the authorized source phases:

1. Re-audit every finding above against the final source and record
   `open`, `resolved`, `superseded`, or `accepted debt` with evidence.
2. Reconcile `requirements.json` before relying on its implemented count;
   downgrade claims whose complete specification behavior is still missing.
3. Unify canonical machine, model, engine, workload, recommendation, deployment,
   campaign, and lifecycle identities.
4. Build one application service that composes catalog, recommendation,
   acquisition, deployment, engines, benchmarks, events, and recovery.
5. Add a disposable end-to-end managed workflow using real local processes and
   the public authenticated API; keep all live external systems out of scope.
6. Complete metrics and event production pipelines independently of the UI.
7. Harden native process-tree lifecycle and target-specific recovery.
8. Correct traceability, coverage exclusions, lane markers/counts, and stale
   documentation.
9. Only then run Phase 18 physical qualification and decide which requirements
   can move from `implemented` to `validated`.

## Closure Standard

This audit is not closed by a green unit suite, a renamed type, or a UI mock.
Closure requires:

- one canonical identity trace across the complete workflow;
- public-boundary tests that exercise the actual application composition;
- fault injection and restart/reconnect behavior at every durable edge;
- exact external-resource snapshots proving observe-mode integrity;
- requirement status and owning-test metadata that match the full specification;
- updated human-readable ledgers with no contradictory active milestone.

No finding authorizes live-host mutation, adoption of `coder-model`, external
cache mutation, publication, licensing changes, or signing-credential access.
