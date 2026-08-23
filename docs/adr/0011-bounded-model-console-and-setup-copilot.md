# ADR-0011: Bounded Model Console and Setup Copilot

Status: Accepted

Date: 2026-08-22

## Context

Morpheus selects, configures, stages, and operates inference, but the accepted
v0.2 scope previously required the operations workspace to stop short of chat.
That leaves an avoidable break in the primary workflow: after selecting or
starting a model, the operator must leave Morpheus to verify interactively that
the exact endpoint and model behave as expected. It also leaves setup guidance
split between static forms, diagnostics, and runbooks.

A full chat product would duplicate Open WebUI, introduce conversation-library
and tool-ecosystem scope, and distract from the focused inference appliance. A
setup assistant that can mutate the host or silently select a provider would
also bypass Morpheus's canonical plan, ownership, consent, and authorization
boundaries.

## Decision

Morpheus adds two bounded conversational surfaces in dependency order.

1. The **model console** is an operational playground for an explicitly selected
   OpenAI-compatible inference target. It lets the operator submit, stream,
   cancel, and inspect a small interactive conversation while Morpheus displays
   the canonical target, ownership mode, requested and reported model, and the
   managed deployment-plan identity when one exists. It may display structured
   or tool-call output, but it does not execute model-requested tools.
2. The optional **setup copilot** explains machine evidence, catalog choices,
   recommendations, configuration previews, diagnostics, and runbooks through
   the same provider and advisory boundaries as AI-assisted diagnosis. It may
   produce a typed proposed check or plan preview, but it cannot call lifecycle,
   runtime-agent, shell, filesystem, Docker, secret, installation, promotion, or
   deletion capabilities.

The model console can target a Morpheus-managed deployment or an explicitly
selected external-observed endpoint. No completion is sent by discovery,
health, page load, or background polling. Submitting to an external-observed
target is an explicit user-requested workload and never changes its ownership.

The setup copilot provider is disabled by default. When enabled, it may use an
explicitly selected local OpenAI-compatible target or a configured external API.
Before evidence leaves the host, Morpheus shows the provider, destination,
model, retention implications, timeout, cost limits, and consent state. Setup
and ordinary diagnostics remain completely usable when no provider is
configured. Bundling or automatically downloading a small helper model is
deferred until a separate catalog, license, packaging, storage, and resource-
contention decision is accepted.

Conversation content is memory-only by default. Prompts and responses are not
written to application logs, metrics, events, support bundles, or operational
history. A future conversation-retention feature requires its own explicit,
off-by-default specification and privacy review.

The general-purpose chat experience remains the responsibility of Open WebUI or
another operator-chosen client. Morpheus's two surfaces are labeled distinctly:
the model console talks **to the selected model**, while the setup copilot asks
**Morpheus about setup and evidence**.

## Consequences

- The operator can validate model identity, streaming, cancellation, latency,
  and basic response behavior without leaving the setup workflow.
- Both surfaces must bind every request to the canonical target/provider
  identity fixed by rectification R1; they cannot create another model,
  deployment, or provider identity family.
- The model console belongs to the operations-workspace delivery after the
  durable managed application boundary exists. The setup copilot follows the
  diagnostic evidence and provider work and cannot delay those prerequisites.
- Existing inference and diagnosis adapters may be reused behind typed ports,
  but neither surface becomes a broad multi-provider gateway or control plane.
- UI and acceptance tests must distinguish managed and external-observed
  targets, unavailable providers, local versus external destinations, content
  privacy, cancellation, model mismatch, and advisory-only proposals.
- Open WebUI remains externally owned and unchanged. Morpheus does not read,
  migrate, or replace its conversation history.

## Alternatives Considered

### Continue relying exclusively on Open WebUI

Rejected because it separates model setup from the simplest end-to-end
verification and cannot provide Morpheus's canonical plan and evidence context.

### Build a complete Morpheus chat application

Rejected because persistent histories, personas, document libraries, plugins,
tool execution, sharing, and broad provider routing are a separate product and
would duplicate mature chat clients.

### Bundle a tiny setup model immediately

Deferred because model licensing, artifact acquisition, package size, CPU/RAM
cost, accelerator contention, update policy, and output quality require evidence
and product decisions of their own. Provider abstraction supplies the useful
workflow without committing to a bundled artifact.

### Give the copilot direct lifecycle tools

Rejected because model output is untrusted advisory input. All state changes
must re-enter the ordinary typed plan, policy, preflight, confirmation, audit,
and recovery path.
