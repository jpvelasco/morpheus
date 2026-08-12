# Morpheus Documentation

## Product and Delivery

- [Product specification](PRODUCT_SPECIFICATION.md): scope, requirements,
  features, non-goals, and product-level acceptance criteria.
- [Architecture](ARCHITECTURE.md): ownership boundaries, components, data
  flows, security model, and deployment shape.
- [Implementation plan](IMPLEMENTATION_PLAN.md): test-driven build sequence,
  quality gates, v0.1 history, and v0.2 focused-appliance phases.
- [Dual-mode appliance decision](adr/0005-dual-mode-focused-inference-appliance.md):
  observed versus managed inference ownership and focused scope.
- [Evidence-ranked selection decision](adr/0006-evidence-ranked-model-engine-selection.md):
  compatibility filtering, workload ranking, provenance, and operator authority.
- [Tauri desktop and independent backend decision](adr/0007-tauri-desktop-and-independent-backend.md):
  shared React desktop/browser UI, backend service lifecycle, and version handshake.
- [Tiered cross-platform runtime decision](adr/0008-tiered-cross-platform-runtime-support.md):
  stable three-OS targets, native engine baseline, and evidence-bounded tiers.
- [Release validation plan](RELEASE_VALIDATION_PLAN.md): prioritized host and VM
  prerequisites, executable validation tasks, evidence, and release gates.
- [Release state](RELEASE_STATE.md): durable current-candidate ledger, completed
  milestones, active work, and resume constraints.
- [History identity migration](HISTORY_REWRITE.md): pre-publication email
  rewrite, SHA continuity, and legacy deployed-candidate provenance.
- [Lifecycle operations](LIFECYCLE.md): fixed release layout, authenticated
  commands, repeat semantics, recovery, uninstall, and lab-only purge.
- [Inventory](inventory.md): existing local assets and candidate inputs.

## Decision Records

Architecture decisions belong in `docs/adr/` and use the format:

```text
NNNN-short-decision-name.md
```

Every accepted record contains context, decision, consequences, alternatives,
and a date. Changes to an accepted decision require a superseding record.
