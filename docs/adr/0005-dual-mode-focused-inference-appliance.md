# ADR-0005: Dual-Mode Focused Inference Appliance

Status: Accepted

Date: 2026-08-11

## Context

Morpheus v0.1 deliberately stopped at a read-only status plane around ubuntu-1's
externally owned vLLM and Open WebUI services. That boundary protected a working
server, but it cannot satisfy the reopened product goal: run Morpheus on ubuntu-1
or ubuntu-2, discover the machine, choose an appropriate developer model and
engine, install and benchmark it, serve inference, and operate it through a
focused web application.

Replacing the v0.1 boundary outright would make ordinary observation capable of
mutating a working external stack. Treating all runtimes as external would make
the new management workflow impossible.

## Decision

Morpheus has two explicit inference ownership modes:

- **Observe mode** preserves the v0.1 contract. Existing inference remains
  externally owned and is available only to read-only discovery, health,
  metrics, and separately authorized benchmark requests.
- **Managed mode** permits Morpheus to own a separate model store, engine
  artifacts, generated configuration, services, endpoints, benchmark state,
  and lifecycle records below fixed owned roots and labels.

Ownership mode is a typed part of every runtime identity and operation. Resource
names, endpoint reachability, or successful discovery never transfer ownership.
A distinct adoption workflow may migrate an existing runtime only after exact
pre-state capture, plan review, explicit confirmation, and tested rollback.

Morpheus v0.2 is a focused developer-inference appliance. Search, voice,
research, workflow, RAG, and image-generation expansion is not on its critical
path. Existing v0.1 primitives remain supported but do not displace model,
engine, benchmark, operations, and diagnosis milestones.

## Consequences

- The deployed ubuntu-1 status plane remains safe and useful during v0.2 work.
- Managed installation and lifecycle can be designed without granting control
  over all discovered Docker or inference resources.
- API, CLI, persistence, dashboard, audit, agent, and lifecycle contracts must
  distinguish observed and managed identities.
- Model storage and inference engines become first-class Morpheus-owned
  resources with quotas, manifests, rollback, and cleanup policy.
- ubuntu-1's current coder remains external until a later adoption or replacement
  action is separately authorized.
- Broad optional-service work is deferred behind the focused v0.2 release.

## Alternatives Considered

### Convert every discovered runtime into a managed runtime

Rejected because discovery is not proof of ownership and would violate the
existing external-runtime integrity invariant.

### Keep Morpheus read-only and maintain deployment scripts elsewhere

Rejected because model/engine selection, benchmark evidence, lifecycle, and
operations would remain fragmented instead of forming one coherent product.

### Build a broad ODS-like suite

Rejected because the reopened need is a high-quality developer inference
appliance, not maximum feature breadth.
