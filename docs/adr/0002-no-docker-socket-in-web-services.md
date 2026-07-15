# ADR-0002: No Docker Socket in Web Services

Status: Accepted

Date: 2026-07-15

## Context

The dashboard needs host and service information and may eventually control
Morpheus-owned sidecars. Mounting `/var/run/docker.sock` into a network-facing
API effectively grants host-level control and makes resource ownership checks
easy to bypass after a web compromise.

## Decision

The dashboard and control API will not receive the Docker socket. Host inspection
and lifecycle operations use a separate loopback runtime agent with mutual
authentication, an explicit operation allowlist, fixed paths, ownership labels,
and protected external-resource checks.

The initial agent is read-only. Stateful operations are added individually only
after authorization, idempotence, rollback, and external-integrity tests exist.

## Consequences

- A compromised web service does not automatically gain arbitrary Docker access.
- The agent protocol and credential lifecycle become security-critical contracts.
- Development has one additional process and test boundary.
- Host operations can be audited and constrained independently of browser APIs.

## Alternatives Considered

### Mount the Docker socket read-only

Rejected because a read-only filesystem mount does not make the Docker API
read-only, and Docker control is effectively host control.

### Run the complete API as a privileged host process

Rejected because it combines browser parsing, application dependencies, and
host control in one trust boundary.

### Provide no lifecycle controls

Viable for the earliest milestone, but insufficient for the planned optional
service experience. The staged read-only agent preserves that initial safety.
