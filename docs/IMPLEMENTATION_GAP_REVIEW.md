# Morpheus Implementation Gap Review

Review date: 2026-08-22

Reviewed source: `9b4cda09d4b064f160902b9dd25387cf3129cdb3`

Planning version: 0.2.0

Source of truth: [`requirements.json`](../requirements.json)

Active execution plan: [`RECTIFICATION_PLAN.md`](RECTIFICATION_PLAN.md)

## Status Semantics

- `implemented` means the complete specified product behavior exists at its
  stable boundary and has meaningful owning tests.
- `validated` requires retained passing evidence from every required
  environment, linked by a green evidence manifest.
- `planned` means product behavior is absent, materially incomplete, or only
  exists as uncomposed component scaffolding. Every planned row has an active
  `IMP-*` task.
- `deferred` means the accepted focused-v0.2 scope intentionally excludes the
  behavior until its documented trigger and change-control review occur.

A parser, pure policy record, fake or DEV-only executor, UI card, route schema,
or existing test file is progress but does not by itself satisfy a product
requirement. This strict interpretation restores the TDD and acceptance-boundary
rules in the original implementation plan.

## Current Disposition

| Status | Count | Meaning now |
|---|---:|---|
| Implemented | 59 | Complete source behavior at the currently claimed boundary; not release-validated |
| Planned | 28 | Requires architecture rectification, complete product composition, or accepted bounded feature delivery |
| Deferred | 12 | Outside the focused v0.2 critical path |
| Validated | 0 | No requirement has the complete retained evidence matrix |

Implemented: CFG-001 through CFG-004; RUN-001 through RUN-006; UI-001, UI-002,
UI-004, UI-005; SRCH-001, SRCH-003; VOICE-001, VOICE-002; TEL-001 through
TEL-005; FLOW-001, FLOW-002; GATE-002, GATE-003; OPS-001 through OPS-003;
SEC-001 through SEC-007; REL-001 through REL-004; PERF-001 through PERF-003;
HOST-001, HOST-002; SEL-001 through SEL-003; PLAT-001; BENCH-002 through
BENCH-004; OUI-001, OUI-004; AID-003; ACCESS-001 through ACCESS-003.

Planned: UI-003; GATE-001; HOST-003; SEL-004, SEL-005; RUNM-001 through
RUNM-006; PLAT-002 through PLAT-004; BENCH-001, BENCH-005; OUI-002, OUI-003,
OUI-005, OUI-006; CHAT-001, CHAT-002; DESK-001 through DESK-003; AID-001,
AID-002, AID-004.

Deferred: SRCH-002; VOICE-003, VOICE-004; RSCH-001, RSCH-002; RAG-001 through
RAG-003; IMG-001 through IMG-004.

The counts above are derived from the manifest. If a later edit changes them,
update this review and `RELEASE_STATE.md` in the same change.

CHAT-001 and CHAT-002 are new accepted bounded scope recorded by ADR-0011, not
claims about existing component work. The model console follows canonical target
identity and durable application composition in R6; the setup copilot follows
the diagnosis evidence/provider boundary in R7. General-purpose chat, persistent
conversation history, plugins, and model-directed tool execution remain out of
scope.

## Why the Completion Claim Was Reversed

The final implementation run changed all 97 rows to `implemented`. The source
contains substantial, well-tested component work, but the product specification
and phase exit gates require composition through real application/public
boundaries. The current source still has these blocking facts:

- incompatible semantic `DeploymentPlan` and identity families are used by the
  vertical slice, recommendation, and managed deployment components;
- the recommendation API uses a hard-coded seed catalog, ignores benchmark
  history, and uses an observation timestamp as machine identity;
- managed workflow routes use `DevWorkflowExecutor`, which intentionally refuses
  mutating steps, while sessions disappear on API restart;
- the bounded managed gateway router exists only as a component and is not
  mounted from a selected canonical managed deployment;
- settings “apply” writes an overrides journal that is not a real startup source,
  and the feature-controls page exposes state rather than owned actions;
- metrics collect as a GET side effect and the event store has no production
  producers or bounded message search;
- native engine shutdown uses a direct child process handle instead of the
  platform process-tree supervision port;
- the Tauri shell performs only an unauthenticated health probe, native install
  executors are absent, and `.mrpkg` scaffolding is not the declared native
  package matrix;
- diagnostic API evidence supplies empty metrics/log sections, local provider
  mode is deliberately unwired, and proposals do not re-enter ordinary plans;
- the optional-scope requirements were promoted without an ADR reopening the
  focused-v0.2 priority boundary or implementing their complete product paths.

These facts reproduce AUD-001 through AUD-008 and add AUD-009 through AUD-012 in
the rectification plan.

## Rectification Backlog

| Order | Package | Primary requirements | Outcome |
|---:|---|---|---|
| 0 | R0 | all affected rows | truthful ledgers plus semantic test ownership and documentation consistency checks |
| 1 | R1 | RUNM-001 | one canonical machine/model/engine/workload/recommendation/plan/campaign identity chain |
| 2 | R2 | SEL-004, SEL-005 | retained catalog/machine/benchmark evidence, deterministic replay, and lossless plan selection |
| 3 | R3 | UI-003, GATE-001, BENCH-001, BENCH-005, RUNM-003 through RUNM-006, OUI-005, OUI-006 | durable lifecycle-backed managed application workflows |
| 4 | R4 | PLAT-002 through PLAT-004, RUNM-002 | real process-tree, per-user service, package, and target-native DEV/lab paths |
| 5 | R5 | OUI-002, OUI-003 | complete background metric and approved event pipelines |
| 6 | R6 | DESK-001 through DESK-003, CHAT-001 | shared React Tauri app, bounded model console, authenticated bootstrap, native packages, and access parity |
| 7 | R7 | AID-001, AID-002, AID-004, CHAT-002 | complete evidence, optional setup copilot, usable provider paths, and advisory plan re-entry |
| 8 | R8 | 12 deferred IDs | focused-scope enforcement; safe scaffolds stay incomplete and off by default |
| 9 | R9 | all planned rows | public-boundary acceptance, mutation, coverage, clean-gate, and status closure |
| 10 | R10 | HOST-003, PLAT-004, ACCESS-003 and release set | separately authorized physical qualification and release evidence |

R1 is the shared-contract gate. Do not fan out downstream schema work until it
lands. R4 through R7 may run in parallel only after R3 fixes the application
operation boundary.

## Rectification Progress

- 2026-08-23: gate repair landed (#66): platform-neutral TLS path validation,
  unique research-deployment contract module name, portable Makefile test
  globs, locked pip refreshed past PYSEC-2026-3721, Linux-fatal fixture casing.
- 2026-08-23: R0 semantic traceability enforced — `requirements.json` rows carry
  machine-readable `boundaries`; manifest tests reject `implemented` rows whose
  owning tests lack requirement-ID test names or explicit
  `MORPHEUS_OWNED_REQUIREMENTS` metadata, require public-lane owners for public
  boundaries, derive documentation counts from the manifest, refuse stale
  completion claims, and keep `api/app.py`/`agent/app.py` measured by coverage;
  lane reports record collected/selected/deselected/passed/failed/skipped/error
  counts separately under ignored `artifacts/test-counts/`.

Optional external harness evidence interoperability under ADR-0010 is not a
rectification gap, requirement-status change, or R0-through-R9 work item. R1 and
R2 must remain producer-neutral so that a later importer cannot create a
competing identity/evidence family.

## Release Consequence

Morpheus is not source-complete and no v0.2 candidate should be frozen for
physical qualification. The deployed v0.1 read-only surface and its historical
candidate evidence remain valid for their exact artifacts; they are not evidence
for this development line.

Finish R0 through R9 in DEV and disposable environments, freeze a new clean
candidate, then request explicit authorization for each R10 host lane. Missing
public signing/notarization credentials never blocks the developer/source path.
No item in this review authorizes mutation or adoption of the external runtime.
