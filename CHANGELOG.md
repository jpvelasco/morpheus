# Changelog

All notable Morpheus changes will be documented in this file.

The format follows Keep a Changelog principles. Versioning begins when the
first implementation artifact is released.

## Unreleased

### Rectification

- Re-audited the completed v0.2 component run at source `9b4cda0` against the
  accepted specification, architecture, ADRs, and phase exit gates. All eight
  August 15 findings remain open; additional deferred-scope, desktop/package,
  diagnosis, and target-support overclaims are documented in the active
  architecture rectification plan.
- Reconciled the requirement ledger from the unsupported `97 implemented`
  claim to 59 implemented, 26 planned, 12 deferred, and 0 validated. Existing
  partial components and tests are preserved as implementation progress.
- Made `docs/RELEASE_STATE.md` the sole current-state ledger, added an
  agent-executable R0-R10 rectification order, and classified the original
  long-horizon prompt and dated audit as historical inputs.

### Added

- Phase 11 contract foundation: exactly two inference ownership modes
  (`external_observed`, `morpheus_managed`), workflow-scoped adoption-candidate
  transfer records that are never identities or lifecycle targets, and a public
  lifecycle identity guard.
- Immutable planning records (machine, model, engine, workload, deployment
  plan, campaign, comparison, diagnosis, recommendation) with a canonical
  versioned envelope codec and strict schema-version rules.
- Five separate lifecycle state machines (acquisition/staging, benchmark
  campaign, promotion, rollback, adoption) implementing the architecture
  transition tables, terminal-state immutability, and audit results for
  undefined edges.
- Component scaffolds for the focused operations workspace, Tauri shell,
  package trust/bootstrap planning, bounded diagnostic providers, access
  profiles, and evidence-bounded support reports. Their incomplete product
  composition is tracked by the planned rectification requirements.
- Preparatory search, voice, research, RAG, and image policy/contract modules.
  The affected optional product requirements remain deferred.
- v0.2 focused developer-inference appliance specification and phased plan for
  Ubuntu, Windows, and Apple Silicon macOS, retaining ubuntu-1 and ubuntu-2 as
  named Linux qualification machines.
- Tauri 2 desktop and separately versioned per-user backend service plan.
- Tiered runtime plan with native llama.cpp across stable targets and an
  additional vLLM tier on qualified Linux NVIDIA hosts.
- Dual observed/managed runtime ownership architecture.
- Planned host discovery, evidence-ranked selection, managed model/engine
  lifecycle, benchmark history, focused operations UI, AI-assisted diagnosis,
  and secure access requirements.
- Independent project and Git repository foundation.
- Product specification with requirement and release exit criteria.
- Ports-and-adapters architecture and security boundaries.
- Test-driven implementation and validation plan.
- Repository, contribution, security, and agent operating standards.

### Changed

- Defined the independent specialization boundary between Morpheus inference
  deployment optimization and external developer-harness qualification tools
  such as Tonos. ADR-0010 permits only a later optional sanitized evidence
  exchange and opaque correlation value; it adds no runtime dependency, remote
  control, fleet scope, or active rectification work.
- Restored Windows parity for the local validation lanes with bounded fixes
  that leave POSIX behavior unchanged: platform-correct path-escape checks,
  process-tree spawn/kill helpers, directory-fsync guards, and platform-aware
  test fixtures and bash-executing lane guards.
- Audited the v0.2 implementation handoff: fixed the two-mode ownership and
  adoption boundary, separated lifecycle state machines, ordered backend and
  desktop packaging, bounded the compatibility endpoint, and made physical
  target evidence distinct from source implementation gates.
- Added a real Ubuntu CPU managed-inference walking skeleton, mandatory
  evidence-driven self-replan, smaller long-horizon delivery subphases, and a
  dev-first package policy that leaves public signing/notarization as optional
  final distribution hardening.
- Recorded open-source licensing as an explicit non-blocking publication decision
  because current package metadata remains proprietary with no license granted.
