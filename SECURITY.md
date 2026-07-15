# Security Policy

## Current Status

Morpheus has no released version. Treat all code as development-only until the
release exit criteria in `docs/IMPLEMENTATION_PLAN.md` are satisfied.

## Reporting

Report suspected vulnerabilities privately to the repository owner. Do not
place credentials, environment files, conversation content, model prompts,
database files, or host inventory in an issue or chat transcript.

## Security Invariants

- Services bind to `127.0.0.1` by default.
- LAN exposure is explicit, authenticated, and covered by a threat model.
- The dashboard and API never receive the Docker socket.
- The runtime agent exposes allowlisted Morpheus operations only.
- The existing inference and Open WebUI services are external resources and
  cannot be mutated through Morpheus APIs.
- Secrets are generated locally, stored outside Git, redacted from logs, and
  never returned by configuration endpoints.
- Prompt and response bodies are not persisted unless the operator enables a
  documented retention policy.
- Dependencies and container images are reviewed, locked, and scanned before
  release.

## Supported Versions

No version is supported until the first stable release.
