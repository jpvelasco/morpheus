# Morpheus Implementation Gap Review

Snapshot: 2026-07-15
Candidate version: 0.1.0
Source of truth: [`requirements.json`](../requirements.json)

## Status Semantics

- `implemented` means the requirement's product behavior exists and has an
  owning component test. It does not mean the release-level evidence is green.
- `validated` requires a passing evidence manifest that names the requirement.
- `planned` means an identified product behavior is absent or materially
  incomplete. Every planned requirement has an `IMP-*` task below.
- `deferred` means the product decision intentionally excludes the capability
  until its documented trigger is met.

The review compared all 58 requirements in the product specification against
the Python services, dashboard, Compose definitions, configuration, operator
documentation, and current tests. After IMP-PERF-002-01, the result is 44
implemented, 11 planned, 3 deferred, and 0 validated. Existing tests therefore establish useful code
coverage without overstating production-release completion.

## Complete Disposition

- Implemented: CFG-001 through CFG-004; RUN-001 through RUN-006;
  UI-001, UI-002, UI-004, UI-005; SRCH-001, SRCH-003; VOICE-001, VOICE-002;
  TEL-001 through TEL-005; FLOW-001, FLOW-002; GATE-002, GATE-003; OPS-001
  through OPS-003; SEC-001 through SEC-007; REL-001 through REL-004; PERF-001
  through PERF-003.
- Planned: UI-003; SRCH-002; VOICE-003, VOICE-004; RSCH-001, RSCH-002;
  GATE-001; IMG-001 through IMG-004.
- Deferred: RAG-001 through RAG-003 under ADR-0004. Reopen only after a
  measured retrieval gap, privacy constraints, relevance judgments, and a
  reindex plan exist.
- Validated: none. A requirement advances only when its linked ignored evidence
  manifest is present, says `pass`, and names that requirement.

## Prioritized Implementation Backlog

The order below is dependency-based. Foundation and safety gaps precede the
validation lane that needs them; optional capabilities remain later; GPU work
remains isolated to an explicitly authorized maintenance window.

| Priority | Task | Requirement | Environment | Completion criterion |
|---|---|---|---|---|
| P3 | IMP-UI-003-01 | UI-003 | VM | Add controls only for Morpheus-owned services, with configured/running/healthy/usable states, confirmation, authorization, and no external targets. |
| P3 | IMP-SRCH-002-01 | SRCH-002 | VM, HOST-RO | Document the exact Open WebUI search URL/format and verify connectivity from a disposable peer without editing Open WebUI state. |
| P3 | IMP-VOICE-003-01 | VOICE-003 | VM, HOST-RO | Publish current Open WebUI STT/TTS URLs, model/voice names and request formats, then add upload/playback compatibility tests. |
| P3 | IMP-VOICE-004-01 | VOICE-004 | VM, HOST-MAINT | Define an opt-in GPU voice profile and make startup consult fresh headroom, temperature, ownership, and foreign-process evidence before allocation. |
| P3 | IMP-RSCH-001-01 | RSCH-001 | VM | Replace hard-coded research endpoint/model inputs with validated configuration and complete the pinned Perplexica/SearXNG/model deployment contract. |
| P3 | IMP-RSCH-002-01 | RSCH-002 | VM, HOST-RO | Preserve the configured served-model identity and no-thinking behavior through research requests, with a direct-vs-research contract test. |
| P3 | IMP-GATE-001-01 | GATE-001 | VM | Build the optional authenticated gateway endpoint and validate streaming, tools, structured output, usage, errors, and cancellation parity. |
| P4/HOST-MAINT | IMP-IMG-001-01 | IMG-001 | VM, HOST-MAINT | Add a pinned ComfyUI deployment with Morpheus-owned model/input/output/workflow paths and a deterministic API smoke workflow. |
| P4/HOST-MAINT | IMP-IMG-002-01 | IMG-002 | HOST-MAINT | Connect the GPU policy to real startup so stale, hot, low-memory, foreign-process, or ownership failures stop before allocation. |
| P4/HOST-MAINT | IMP-IMG-003-01 | IMG-003 | HOST-MAINT | Implement a separate operator-run transition workflow with explicit authorization, exact confirmation, durable checkpoints, and no normal control-plane path to external inference mutation. |
| P4/HOST-MAINT | IMP-IMG-004-01 | IMG-004 | HOST-MAINT | Capture pre-state image/model revision/arguments/endpoint identity and require identical restored state plus health and completion evidence before success. |

Completed after the snapshot: **IMP-SEC-005-01** added the digest-pinned,
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
external-resource integrity can proceed before optional research, gateway,
voice-GPU, or image-generation implementation.
