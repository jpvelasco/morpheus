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
documentation, and current tests. The result is 36 implemented, 19 planned,
3 deferred, and 0 validated. Existing tests therefore establish useful code
coverage without overstating production-release completion.

## Complete Disposition

- Implemented: CFG-001 through CFG-004; RUN-001 through RUN-004; RUN-006;
  UI-001, UI-002, UI-004, UI-005; SRCH-001, SRCH-003; VOICE-001, VOICE-002;
  TEL-001 through TEL-005; FLOW-001, FLOW-002; GATE-002, GATE-003; OPS-001,
  OPS-003; SEC-001, SEC-003, SEC-004, SEC-007; REL-001, REL-004; PERF-001,
  PERF-003.
- Planned: RUN-005; UI-003; SRCH-002; VOICE-003,
  VOICE-004; RSCH-001, RSCH-002; GATE-001; IMG-001 through IMG-004; OPS-002;
  SEC-002, SEC-005, SEC-006; REL-002, REL-003; PERF-002.
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
| P0 | IMP-RUN-005-01 | RUN-005 | DEV, VM | Derive capability state from configuration plus real dependency health; never label a configured but unreachable feature `available`. |
| P0 | IMP-SEC-002-01 | SEC-002 | DEV, VM | Add action-aware authorization that combines resource type, ownership label, protected identity, and an explicit operation allowlist. |
| P0 | IMP-SEC-006-01 | SEC-006 | DEV, VM | Centralize owned-root path resolution and apply it to configured data paths, archives, uploads, generated output, and restore staging. |
| P0 | IMP-REL-002-01 | REL-002 | DEV, VM | Add bounded queues/concurrency and a reusable retry policy with exponential backoff, jitter, hard attempt limits, and monotonic deadlines. |
| P0 | IMP-OPS-002-01 | OPS-002 | DEV, VM | Add free-space and schema-compatibility preflight, durable staging, fsync boundaries, rollback-on-failure, and incompatible/partial archive cases to restore. |
| P0 | IMP-REL-003-01 | REL-003 | VM | Implement idempotent install, validate, start, stop, migrate, backup, restore-preflight, upgrade, rollback, and uninstall operations for owned resources. |
| P0/P5 | IMP-SEC-005-01 | SEC-005 | DEV, VM | Generate SBOMs for every artifact/image and make lock, secret, static, dependency, filesystem, and container vulnerability scans release-blocking. |
| P3 | IMP-UI-003-01 | UI-003 | VM | Add controls only for Morpheus-owned services, with configured/running/healthy/usable states, confirmation, authorization, and no external targets. |
| P3 | IMP-SRCH-002-01 | SRCH-002 | VM, HOST-RO | Document the exact Open WebUI search URL/format and verify connectivity from a disposable peer without editing Open WebUI state. |
| P3 | IMP-VOICE-003-01 | VOICE-003 | VM, HOST-RO | Publish current Open WebUI STT/TTS URLs, model/voice names and request formats, then add upload/playback compatibility tests. |
| P3 | IMP-VOICE-004-01 | VOICE-004 | VM, HOST-MAINT | Define an opt-in GPU voice profile and make startup consult fresh headroom, temperature, ownership, and foreign-process evidence before allocation. |
| P3 | IMP-RSCH-001-01 | RSCH-001 | VM | Replace hard-coded research endpoint/model inputs with validated configuration and complete the pinned Perplexica/SearXNG/model deployment contract. |
| P3 | IMP-RSCH-002-01 | RSCH-002 | VM, HOST-RO | Preserve the configured served-model identity and no-thinking behavior through research requests, with a direct-vs-research contract test. |
| P3 | IMP-GATE-001-01 | GATE-001 | VM | Build the optional authenticated gateway endpoint and validate streaming, tools, structured output, usage, errors, and cancellation parity. |
| P4 | IMP-PERF-002-01 | PERF-002 | VM, HOST-RO | Add reproducible idle/steady-state CPU and memory measurement with the combined 1 GiB and 2 percent release thresholds. |
| P4/HOST-MAINT | IMP-IMG-001-01 | IMG-001 | VM, HOST-MAINT | Add a pinned ComfyUI deployment with Morpheus-owned model/input/output/workflow paths and a deterministic API smoke workflow. |
| P4/HOST-MAINT | IMP-IMG-002-01 | IMG-002 | HOST-MAINT | Connect the GPU policy to real startup so stale, hot, low-memory, foreign-process, or ownership failures stop before allocation. |
| P4/HOST-MAINT | IMP-IMG-003-01 | IMG-003 | HOST-MAINT | Implement a separate operator-run transition workflow with explicit authorization, exact confirmation, durable checkpoints, and no normal control-plane path to external inference mutation. |
| P4/HOST-MAINT | IMP-IMG-004-01 | IMG-004 | HOST-MAINT | Capture pre-state image/model revision/arguments/endpoint identity and require identical restored state plus health and completion evidence before success. |

## Release-Validation Consequence

Validation tasks that exercise missing behavior are blocked by the matching
`IMP-*` task, not failed as if the behavior existed. Independent lanes may run
as soon as their own prerequisites are met. In particular, clean build/install,
core container startup, read-only runtime discovery, evidence privacy, and
external-resource integrity can proceed before optional research, gateway,
voice-GPU, or image-generation implementation.
