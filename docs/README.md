# Morpheus Documentation

This index separates authoritative product intent, active work, release
qualification, operations, and historical context. For current work, start with
the release state and rectification plan; do not infer status from a dated audit
or old implementation prompt.

## Start Here

1. [Release state](RELEASE_STATE.md) — the sole authoritative current-state and
   resume ledger.
2. [Architecture rectification plan](RECTIFICATION_PLAN.md) — the active,
   agent-executable source work order and gates.
3. [Requirement manifest](../requirements.json) — functional status,
   implementation task IDs, and evidence obligations.

## Normative Product and Architecture

- [Product specification](PRODUCT_SPECIFICATION.md) — scope, invariants,
  requirements, non-goals, and release exit criteria.
- [Architecture](ARCHITECTURE.md) — accepted ownership boundaries, components,
  identity/data flows, security model, and deployment shape.
- [TDD implementation plan](IMPLEMENTATION_PLAN.md) — original phase ordering,
  quality gates, and exit criteria. It remains normative; the rectification plan
  is the current recovery path back to those gates.
- [Architecture decisions](adr/) — accepted decisions. Changes require a new or
  superseding ADR rather than silent edits to implementation intent.
- [Optional Tonos interoperability](TONOS_INTEROPERABILITY.md) — specialization,
  measurement boundary, optional correlation semantics, and deferred sanitized
  evidence exchange. It creates no dependency or current work item.

## Current Audit and Delivery Control

- [Implementation gap review](IMPLEMENTATION_GAP_REVIEW.md) — current
  requirement disposition and prioritized gap summary.
- [Implementation audit, 2026-08-15](IMPLEMENTATION_AUDIT_2026-08-15.md) — dated
  detailed evidence for AUD-001 through AUD-008; historical snapshot with a
  current disposition link.
- [Release validation plan](RELEASE_VALIDATION_PLAN.md) — clean build, VM,
  browser, lifecycle, security, performance, soak, and physical evidence tasks.

## Operator and Release Runbooks

- [Ubuntu operator runbook](runbooks/UBUNTU_OPERATOR.md) — deployed v0.1
  installation and daily operation.
- [Access runbook](runbooks/ACCESS.md) — loopback, SSH tunnel, and optional
  network-profile operation.
- [Qualification runbook](runbooks/QUALIFICATION.md) — evidence-bounded target
  qualification procedure; not authorization to run a host lane.
- [Lifecycle operations](LIFECYCLE.md) — fixed release layout and the existing
  guarded Compose lifecycle command contract.
- [Validation workspace guide](../validation/README.md) — evidence runner,
  disposable VM, browser, load, and security tooling.

## Historical and Reference Material

- [Vertical-slice assessment](VERTICAL_SLICE_ASSESSMENT.md) — Phase 11.5
  historical evidence and its bounded replan decision. The audit later found
  that subsequent phases forked its canonical contracts.
- [Original implementation bootstrap](OPENCODE_IMPLEMENTATION_BOOTSTRAP.md) —
  archived long-horizon prompt. It is superseded for execution by the
  rectification plan.
- [History identity migration](HISTORY_REWRITE.md) — Git SHA continuity and
  legacy deployed-candidate provenance.
- [Inventory](inventory.md) — pre-project assets and research inputs; normative
  documents take precedence where terminology is older.
- [Release changelog](../CHANGELOG.md) — notable source changes, not proof of
  requirement completion or release readiness.

## Architecture Decision Records

ADRs live in `docs/adr/` and use `NNNN-short-decision-name.md`. Every accepted
record contains context, decision, consequences, alternatives, and a date.
Changing an accepted ownership, platform, distribution, or scope decision
requires a superseding record and corresponding specification/test updates.
ADR-0010 keeps external developer-harness qualification independent while
allowing a later optional evidence-import boundary.
