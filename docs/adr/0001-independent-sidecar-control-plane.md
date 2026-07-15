# ADR-0001: Independent Sidecar Control Plane

Status: Accepted

Date: 2026-07-15

## Context

The host already runs a tuned, healthy vLLM service and Open WebUI deployment.
ODS provides useful product ideas but assumes ownership of inference, model
selection, core services, installation phases, and host-level helpers.

## Decision

Morpheus will be implemented independently as a control plane and set of
optional sidecars. Existing inference and Open WebUI are external dependencies.
ODS source, runtime files, services, and installer behavior will not be imported
or required.

Morpheus may use third-party upstream services also used by ODS, but it will
select, configure, pin, test, and maintain those dependencies directly.

## Consequences

- Morpheus remains small enough to match this host and its actual workflow.
- Existing inference continues without a migration event.
- Dashboard and lifecycle code must be written for vLLM and Morpheus ownership.
- Useful ODS behavior must be understood and specified rather than copied.
- Morpheus bears responsibility for its own security, tests, upgrades, and docs.

## Alternatives Considered

### Install ODS and replace the current stack

Rejected because it introduces port, GPU, data, and host-management conflicts
before the working setup has a reason to be replaced.

### Fork ODS

Rejected because removing ODS inference ownership and generated configuration
would create a long-lived downstream patch across high-risk internals.

### Reference ODS Compose fragments at runtime

Rejected because upstream repository changes could alter Morpheus behavior and
would violate independent build and rollback requirements.
