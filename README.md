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

The deployed v0.1 system is an **operator control plane** for a host that already
runs OpenAI-compatible inference (on ubuntu-1: `coder-model` + Open WebUI). It
does not manage that external runtime or GPU stack.

The repository also contains substantial v0.2 component implementation, but a
post-run audit found that the components do not yet form the intended coherent
managed appliance. The active source milestone is the
[architecture rectification plan](docs/RECTIFICATION_PLAN.md), not physical
qualification or release. The current requirement posture is 59 implemented,
26 planned, 12 deferred, and 0 validated.

For day-to-day operator use on ubuntu-1, install the frozen candidate with the
ubuntu-1 path and stop feature work there:

- [ubuntu-1 operator runbook](docs/runbooks/UBUNTU_OPERATOR.md)
- Installer: `deploy/ubuntu-1/install.sh`

Optional search/Open WebUI integration, voice integration, research, independent
RAG, and image generation remain deferred outside the focused v0.2 critical
path. Existing safe scaffolds do not make those capabilities complete. The
managed workflow named by OUI-006 is core product orchestration and is planned
for rectification; it is distinct from the optional n8n sidecar.

The current external runtime is treated as an integration dependency:

- vLLM service: `coder-model`
- internal API: `http://coder-model:8000/v1`
- host API: `http://127.0.0.1:8082/v1`
- shared Docker network: `ai_default`
- user interface: the existing Open WebUI service

Morpheus must remain usable without an ODS checkout and must never require ODS
at runtime. ODS is research input only.

## Documentation

- [Documentation index](docs/README.md)
- [Current release state](docs/RELEASE_STATE.md)
- [Active architecture rectification plan](docs/RECTIFICATION_PLAN.md)
- [ubuntu-1 operator runbook](docs/runbooks/UBUNTU_OPERATOR.md)
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
desktop/               Tauri desktop scaffold and development packaging
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
runtime operations require the corresponding source gate, retained evidence,
and explicit operator authorization. Component scaffolds must not be used to
infer permission or readiness.
