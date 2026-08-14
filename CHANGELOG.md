# Changelog

All notable Morpheus changes will be documented in this file.

The format follows Keep a Changelog principles. Versioning begins when the
first implementation artifact is released.

## Unreleased

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
