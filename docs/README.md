# Morpheus Documentation

## Product and Delivery

- [Product specification](PRODUCT_SPECIFICATION.md): scope, requirements,
  features, non-goals, and product-level acceptance criteria.
- [Architecture](ARCHITECTURE.md): ownership boundaries, components, data
  flows, security model, and deployment shape.
- [Implementation plan](IMPLEMENTATION_PLAN.md): test-driven build sequence,
  quality gates, and phase exit criteria.
- [Release validation plan](RELEASE_VALIDATION_PLAN.md): prioritized host and VM
  prerequisites, executable validation tasks, evidence, and release gates.
- [Release state](RELEASE_STATE.md): durable current-candidate ledger, completed
  milestones, active work, and resume constraints.
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
