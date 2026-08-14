# Morpheus Implementation Gap Review

Original v0.1 snapshot: 2026-07-15
v0.2 scope reopening: 2026-08-11
Planning version: 0.2.0
Source of truth: [`requirements.json`](../requirements.json)

## Status Semantics

- `implemented` means the requirement's product behavior exists and has an
  owning component test. It does not mean the release-level evidence is green.
- `validated` requires a passing evidence manifest that names the requirement.
- `planned` means an identified product behavior is absent or materially
  incomplete. Every planned requirement has an `IMP-*` task below.
- `deferred` means the product decision intentionally excludes the capability
  until its documented trigger is met.

The original review compared 58 v0.1 requirements against the Python services,
dashboard, Compose definitions, configuration, operator documentation, and
tests. It found 44 implemented, 11 planned, 3 deferred, and 0 validated.

The reopened v0.2 specification contains 97 requirements: 44 existing
requirements remain implemented, 41 are planned, 12 are deferred, and 0 are
formally validated. The new planned requirements define host discovery,
model/engine selection, managed inference, benchmark history, the focused
operations workspace, Tauri desktop, cross-platform backend, AI-assisted
diagnosis, and secure target access. Existing tests therefore establish a useful
v0.1 foundation without claiming that the v0.2 appliance exists.

The 97 status rows are functional requirements. INV-001 through INV-009 are
mandatory cross-cutting constraints mapped to the functional requirements they
protect; they do not receive independent status rows or inflate these counts.

## Complete Disposition

- Implemented: CFG-001 through CFG-004; RUN-001 through RUN-006;
  UI-001, UI-002, UI-004, UI-005; SRCH-001, SRCH-003; VOICE-001, VOICE-002;
  TEL-001 through TEL-005; FLOW-001, FLOW-002; GATE-002, GATE-003; OPS-001
  through OPS-003; SEC-001 through SEC-007; REL-001 through REL-004; PERF-001
  through PERF-003; RUNM-001.
- Planned: UI-003; GATE-001; HOST-001 through HOST-003; SEL-001 through
  SEL-005; RUNM-002 through RUNM-006; BENCH-001 through BENCH-005; OUI-001
  through OUI-006; PLAT-001 through PLAT-004; DESK-001 through DESK-003;
  AID-001 through AID-004; ACCESS-001 through ACCESS-003.
- Deferred: SRCH-002; VOICE-003, VOICE-004; RSCH-001, RSCH-002; RAG-001
  through RAG-003; IMG-001 through IMG-004. These are outside the focused v0.2
  critical path. Existing implemented optional-service primitives are retained,
  but feature-suite expansion is not an active product priority.
- Validated: none. A requirement advances only when its linked ignored evidence
  manifest is present, says `pass`, and names that requirement.

## v0.2 Prioritized Implementation Backlog

The order below is dependency-based and follows the v0.2 implementation plan.
The running v0.1 ubuntu-1 status plane remains observe-only throughout ordinary
development.

| Order | Phase | Requirements | Outcome |
|---:|---:|---|---|
| 1 | 11 | RUNM-001 | Exactly two observed/managed ownership modes, workflow-scoped adoption records, and immutable v0.2 contracts without changing deployed behavior. |
| 2 | 11.5 | VSLICE-001 delivery gate; no status row | Real disposable Ubuntu CPU discovery-to-rollback walking skeleton, self-assessment, and bounded evidence-driven replan. |
| 3 | 12 | HOST-001, HOST-002, SEL-001, PLAT-001, PLAT-002 | Read-only normalized host profiles, native OS capability contracts, and versioned catalogs. |
| 4 | 13 | BENCH-001 through BENCH-005 | Durable benchmark provenance, history import, safe campaigns, comparisons, and regression records. |
| 5 | 14 | SEL-002 through SEL-005 | Deterministic compatibility filtering and explainable developer-workload ranking. |
| 6 | 15 | RUNM-002 through RUNM-006, PLAT-003, GATE-001 | Target-native backend packaging, a bounded stable managed endpoint, and verified model/engine installation, serving, rollback, and recovery. |
| 7 | 16 | UI-003, OUI-001 through OUI-006, DESK-001, DESK-002 | Tauri and browser operations UI with backend compatibility/bootstrap. |
| 8 | 17 | AID-001 through AID-004, ACCESS-001, ACCESS-002, DESK-003 | Bounded diagnosis and local/SSH-tunneled desktop/browser access. |
| 9 | 18 | HOST-003, PLAT-004, ACCESS-003 | Ubuntu, Windows, and Apple Silicon macOS physical developer/source qualification and explicit tier claims. |
| 10 | optional | no functional status row | Windows/Apple/Linux signing, notarization, and trusted unattended-update qualification only when external credentials exist. |

Completed after the snapshot: **IMP-RUNM-001-01** introduced exactly two
inference ownership modes (`external_observed`, `morpheus_managed`) with
workflow-scoped adoption-candidate transfer records that are not identities or
lifecycle targets, exact managed-target binding to one immutable deployment
plan and owned root, a public lifecycle identity guard, nine immutable
planning-record contracts (machine, model, engine, workload, deployment plan,
campaign, comparison, diagnosis, recommendation) with a canonical versioned
envelope codec, and the five separate state machines (acquisition/staging,
campaign, promotion, rollback, adoption) with the architecture transition
tables, terminal-state immutability, and audit results for undefined edges.
Observe-mode v0.1 behavior is unchanged and its regression lanes stay green.
Host-role evidence remains a later, separately authorized validation step.

**IMP-SEC-005-01** added the digest-pinned,
offline candidate scan and two-format per-artifact SBOM gate, closed evidence
verification, vulnerability-database inventory, redacted Git/worktree/artifact
secret scans, filesystem and OCI vulnerability/misconfiguration scans, and a
digest-bound human license review. Exact-candidate SUPPLY evidence remains a
validation task rather than an implementation claim.

**IMP-REL-003-01** added the disabled-by-default, signed runtime-agent
lifecycle endpoint and separate operator CLI. Fixed release manifests drive
no-build/no-pull Compose operations; ownership checks, atomic state, repeated
operation outcomes, automatic upgrade backups, recovery, rollback,
preserve-by-default uninstall, exact lab-only purge confirmation, and selected
protected-runtime identity comparison have unit and contract coverage. VM
lifecycle and external-integrity demonstrations remain release-validation
tasks rather than source implementation claims.

**IMP-PERF-002-01** added a read-only observer for exact ownership-labeled
containers, structured Docker stats parsing, logical-CPU normalization to
whole-host percent, combined memory/CPU budget decisions, and closed JSON
evidence writers. The versioned pinned-k6 workload declares fixed direct and
telemetry targets, stream mix, latency shape, concurrency, warm-up, duration,
abort limits, and DEV, qualification, and 24-hour profiles. Exact-candidate VM
and target-host evidence remains required before PERF-001 or PERF-002 can be
marked validated.

## Release-Validation Consequence

Validation tasks that exercise missing behavior are blocked by the matching
`IMP-*` task, not failed as if the behavior existed. Independent lanes may run
as soon as their own prerequisites are met. In particular, clean build/install,
core container startup, read-only runtime discovery, evidence privacy, and
external-resource integrity can proceed before optional research,
multi-provider gateway breadth, voice-GPU, or image-generation implementation.

For v0.2, Phase 11 contracts are the next source milestone. Existing v0.1
optional-service validation is not a prerequisite. Target-host mutation remains
blocked until the managed-runtime contracts, disposable lifecycle lanes, exact
resource bounds, rollback, and separate HOST-MAINT authorization are present.
After Phase 11, VSLICE-001 is the mandatory integration/replan gate before
horizontal Phase 12 work fans out. Missing public signing identities or
notarization credentials never block the developer/source implementation path.
