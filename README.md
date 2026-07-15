# Morpheus

Morpheus is an independent control plane and optional service layer for an
existing OpenAI-compatible local inference server. It is designed to add
health visibility, operational tooling, search, voice, telemetry, workflows,
research, and carefully coordinated media services without replacing or
reconfiguring the working inference runtime.

## Status

Morpheus is in specification and repository-bootstrap stage. No production
services are implemented yet.

The current external runtime is treated as an integration dependency:

- vLLM service: `history-coder`
- internal API: `http://history-coder:8000/v1`
- host API: `http://127.0.0.1:8082/v1`
- shared Docker network: `ai_default`
- user interface: the existing Open WebUI service

Morpheus must remain usable without an ODS checkout and must never require ODS
at runtime. ODS is research input only.

## Documentation

- [Product specification](docs/PRODUCT_SPECIFICATION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [TDD implementation plan](docs/IMPLEMENTATION_PLAN.md)
- [Existing asset inventory](docs/inventory.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)

## Planned Layout

```text
src/morpheus/          Python domain, adapters, API, agent, and CLI
web/                   TypeScript dashboard
deploy/                Morpheus-owned Compose and service configuration
tests/                 Unit, contract, integration, acceptance, and live tests
docs/                  Specifications, architecture, ADRs, and runbooks
artifacts/              Ignored generated reports and benchmark captures
```

## Repository Rules

- Build features test-first.
- Keep domain logic independent of Docker, vLLM, and HTTP libraries.
- Treat the active inference service and Open WebUI data as externally owned.
- Bind new services to loopback unless LAN exposure is explicitly configured.
- Never commit credentials, prompts, conversations, model data, or runtime
  databases.
- Pin production container dependencies by immutable digest after validation.

No installation or runtime command should be used until the relevant phase in
the implementation plan has met its exit criteria.
