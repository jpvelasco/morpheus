# Morpheus

Morpheus is a focused local developer-inference appliance. The v0.2 plan covers
host discovery, evidence-ranked model and engine selection, managed installation
and serving, durable benchmark comparisons, and a modern operations workspace
for metrics, logs, analytics, settings, diagnosis, and recovery. The stable
target is a Tauri desktop plus independent backend on Ubuntu, Windows, and Apple
Silicon macOS, with browser and SSH-tunneled access retained.

The deployed v0.1 foundation remains an independent read-only control plane for
an existing OpenAI-compatible runtime. v0.2 adds a separately owned managed mode
without weakening that external-runtime boundary.

## Status

Morpheus is an **operator control plane** for a host that already runs
OpenAI-compatible inference (on Batwing: `qwopus-coder` + Open WebUI). It is
intentionally **not** a full appliance installer and does not manage models or
the external GPU stack.

That paragraph describes the currently deployed v0.1 behavior. The approved
v0.2 product plan will add a managed-appliance path for Batwing and Batmobile
and qualified Windows and Apple Silicon macOS hosts, but no v0.2 runtime
implementation or live migration has started.

For day-to-day operator use on Batwing, install the frozen candidate with the
Batwing path and stop feature work there:

- [Batwing operator runbook](docs/runbooks/BATWING_OPERATOR.md)
- Installer: `deploy/batwing/install.sh`

Optional sidecars (search, voice, workflows, research, RAG, image generation)
are outside the focused v0.2 critical path. Morpheus is not attempting to match
ODS feature breadth.

The current external runtime is treated as an integration dependency:

- vLLM service: `qwopus-coder`
- internal API: `http://qwopus-coder:8000/v1`
- host API: `http://127.0.0.1:8082/v1`
- shared Docker network: `ai_default`
- user interface: the existing Open WebUI service

Morpheus must remain usable without an ODS checkout and must never require ODS
at runtime. ODS is research input only.

## Documentation

- [Batwing operator runbook](docs/runbooks/BATWING_OPERATOR.md)
- [Product specification](docs/PRODUCT_SPECIFICATION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [TDD implementation plan](docs/IMPLEMENTATION_PLAN.md)
- [Dual-mode appliance decision](docs/adr/0005-dual-mode-focused-inference-appliance.md)
- [Evidence-ranked selection decision](docs/adr/0006-evidence-ranked-model-engine-selection.md)
- [Tauri desktop and independent backend decision](docs/adr/0007-tauri-desktop-and-independent-backend.md)
- [Tiered cross-platform runtime decision](docs/adr/0008-tiered-cross-platform-runtime-support.md)
- [Release validation plan](docs/RELEASE_VALIDATION_PLAN.md)
- [Lifecycle operations](docs/LIFECYCLE.md)
- [Existing asset inventory](docs/inventory.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)

## Repository Layout

```text
src/morpheus/          Python domain, adapters, API, agent, and CLI
web/                   TypeScript dashboard
desktop/               Planned Tauri desktop shell and native packaging
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

The dashboard gate uses the digest-pinned Node image rather than a host Node
installation:

```bash
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp/home \
  -v "$PWD/web:/work" -w /work \
  docker.io/library/node@sha256:99351363debf40f3495cb7fc657a777334c3b21143e594dbfcc7de187439633c \
  sh -lc 'npm ci --ignore-scripts && npm run format-check && npm run typecheck && npm test && npm run build'
```

That runs formatting, strict type checking, tests with coverage, and a
production build. Neither gate contacts or mutates the external inference or
Open WebUI services.

The browser rehearsal uses the digest-pinned Playwright image with networking
disabled and retains its report and reviewed screenshots below ignored
`artifacts/`:

```bash
make browser-gate
```

It exercises the production dashboard build across Chromium, Firefox, WebKit,
and a mobile Chromium viewport, runs the accessibility gate, and rejects
retained evidence containing the synthetic credential canary. Candidate-level
browser security still runs against the disposable candidate stack.

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
