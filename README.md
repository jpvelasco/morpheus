# Morpheus

Morpheus is an independent control plane and optional service layer for an
existing OpenAI-compatible local inference server. It is designed to add
health visibility, operational tooling, search, voice, telemetry, workflows,
research, and carefully coordinated media services without replacing or
reconfiguring the working inference runtime.

## Status

Morpheus is an unreleased development implementation. The repository contains
the typed Python control plane, read-only runtime agent and CLI, operational
dashboard, telemetry proxy, optional service adapters, deployment definitions,
and non-live automated validation. It is not eligible for stable use until the
release-level exit criteria are satisfied, including explicitly authorized live
compatibility, recovery, soak, accessibility, and clean-machine evidence.

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
- [Release validation plan](docs/RELEASE_VALIDATION_PLAN.md)
- [Existing asset inventory](docs/inventory.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)

## Repository Layout

```text
src/morpheus/          Python domain, adapters, API, agent, and CLI
web/                   TypeScript dashboard
deploy/                Morpheus-owned Compose and service configuration
tests/                 Unit, contract, integration, acceptance, and live tests
docs/                  Specifications, architecture, ADRs, and runbooks
validation/            Secret-free release-lab manifests and VM inputs
artifacts/              Ignored generated reports and benchmark captures
```

## Development Validation

The required non-live backend gate uses the locked Python environment:

```bash
make bootstrap
make gate
```

The dashboard gate runs from `web/` with `npm ci --ignore-scripts`, followed by
formatting, strict type checking, tests with coverage, and a production build.
CI executes that sequence in the digest-pinned Node image recorded in the
quality workflow. Neither gate contacts or mutates the external inference or
Open WebUI services.

## Repository Rules

- Build features test-first.
- Keep domain logic independent of Docker, vLLM, and HTTP libraries.
- Treat the active inference service and Open WebUI data as externally owned.
- Bind new services to loopback unless LAN exposure is explicitly configured.
- Never commit credentials, prompts, conversations, model data, or runtime
  databases.
- Pin production container dependencies by immutable digest after validation.

External-runtime tests remain opt-in and read-only. Installation and stateful
runtime operations require the corresponding phase evidence and explicit
operator authorization.
