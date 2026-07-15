# Morpheus Product Specification

Status: Draft for implementation

Specification version: 0.1

Target platform: Single-host Linux with Docker and NVIDIA GPU

Primary integration: Existing OpenAI-compatible vLLM endpoint

## 1. Purpose

Morpheus is an independent operational and feature layer for a local AI server
that already has a working inference engine and chat interface. Morpheus adds
visibility and optional capabilities without reinstalling the GPU stack,
selecting a replacement model, or taking ownership of existing services.

The initial deployment target is the current server:

- inference container: `history-coder`
- inference API on shared Docker network: `http://history-coder:8000/v1`
- host inference API: `http://127.0.0.1:8082/v1`
- served model: `qwen36-27b-nvfp4`
- chat interface: existing Open WebUI on host port `3000`
- external Docker network: `ai_default`

These values are defaults for the first deployment, not hard-coded domain
assumptions.

## 2. Product Principles

1. **External inference ownership.** Morpheus observes and consumes the current
   inference API. It does not install, stop, recreate, tune, or replace it.
2. **Independent implementation.** Morpheus has no runtime, build, or source
   dependency on ODS. Third-party services are selected from their upstream
   projects and integrated directly.
3. **Useful when partially deployed.** Core health and diagnostics work without
   any optional sidecar.
4. **Loopback by default.** New host ports are not exposed to the LAN unless an
   operator makes an authenticated, documented choice.
5. **Evidence over optimism.** Health means a behavioral probe passed, not only
   that a process or port exists.
6. **Reversible operation.** Every stateful operation defines rollback, and
   uninstall leaves external services and data untouched.
7. **Data minimization.** Prompts and responses are not retained by default.
8. **Test-first delivery.** Requirement tests are written before implementation
   and form the release evidence.

## 3. Users and Primary Workflows

### 3.1 Operator

The operator needs to:

- see whether inference and optional services are actually usable;
- identify the loaded model and its supported context;
- inspect GPU, memory, disk, request, and error signals;
- diagnose failures without disclosing secrets or conversation content;
- enable or disable Morpheus-owned capabilities safely;
- back up and restore Morpheus state;
- know that the existing AI service will not be changed.

### 3.2 Chat User

The chat user needs optional access through the existing Open WebUI to:

- private web search;
- local speech-to-text and text-to-speech;
- observable, reliable LLM requests;
- deep research workflows;
- image generation when GPU capacity is deliberately made available.

### 3.3 Developer

The developer needs:

- typed, documented APIs and adapters;
- deterministic local test fixtures;
- a clear boundary between domain logic and infrastructure;
- reproducible builds and dependency locks;
- no requirement to run tests against the production model.

## 4. Scope and Delivery Tiers

### 4.1 Foundation

- validated configuration;
- runtime discovery and health model;
- read-only diagnostics CLI;
- versioned API;
- runtime agent with a narrow allowlist;
- operational dashboard;
- backup, restore, and support bundle;
- security, logging, and release automation.

### 4.2 First Capability Set

- SearXNG search integration;
- CPU-first Whisper-compatible speech-to-text;
- CPU Kokoro-compatible text-to-speech;
- Morpheus request telemetry and usage dashboard.

### 4.3 Extended Capability Set

- n8n workflow service and curated templates;
- Perplexica deep research integration;
- optional LiteLLM-compatible gateway for routing and authentication;
- optional independent vector and embedding services when justified.

### 4.4 Coordinated GPU Capability

- ComfyUI integration;
- explicit GPU workload safety checks;
- an operator-confirmed transition between inference and image workloads;
- recovery to the previously verified inference state.

## 5. Explicit Non-Goals

The following are out of scope for the first stable release:

- hardware auto-detection for model selection;
- GPU driver, Docker Engine, or NVIDIA Container Toolkit installation;
- model download, quantization, conversion, or automatic replacement;
- management of `history-coder`, Open WebUI, or the `ai` Compose project;
- replacing Open WebUI with a Morpheus chat product;
- copying or wrapping the ODS installer, CLI, dashboard API, or host agent;
- public internet exposure or multi-tenant hosting;
- silent mutation of Open WebUI's database or persistent configuration;
- an autonomous agent with unrestricted shell or Docker access;
- claiming compatibility with platforms that have no validation evidence.

## 6. System Invariants

### INV-001 External Runtime Integrity

Install, start, stop, upgrade, failure recovery, and uninstall operations must
leave the external inference and Open WebUI containers, images, volumes, bind
mounts, networks, configuration, and restart counts unchanged.

### INV-002 Resource Ownership

Morpheus may mutate only resources labeled with the current Morpheus project
identity. Names alone are insufficient proof of ownership.

### INV-003 No Docker Socket in Web Services

The dashboard and API must never mount the Docker socket. Host inspection and
allowlisted lifecycle operations go through the authenticated runtime agent.

### INV-004 Safe Defaults

Missing configuration must fail closed. Default bindings are loopback, feature
flags are false until delivered, and destructive or GPU-exclusive actions
require explicit confirmation.

### INV-005 Secret and Content Privacy

Secrets, authorization headers, prompts, responses, uploaded documents, and
audio content must not appear in normal logs, metrics labels, support bundles,
or API error payloads.

### INV-006 Independent Operation

Morpheus must build, test, install, run, upgrade, and uninstall when the ODS
checkout is absent.

## 7. Functional Requirements

### 7.1 Configuration

**CFG-001 Typed configuration.** All configuration is loaded into a typed model
with documented defaults, validation, and source precedence.

**CFG-002 Secret separation.** Secret values are accepted through ignored local
environment files or secret-file references and are never included in public
configuration responses.

**CFG-003 Endpoint validation.** LLM URLs must use `http` or `https`, include the
OpenAI API base path exactly once, and reject credentials embedded in URLs.

**CFG-004 Startup report.** Startup reports effective non-secret settings,
feature decisions, and validation failures without dumping the environment.

Configuration exit criteria:

- malformed, ambiguous, and unsafe settings fail before services start;
- tests cover environment precedence, missing secrets, invalid ports, invalid
  URLs, IPv4, IPv6, Docker DNS names, and redaction;
- the checked-in example contains no functional credential;
- configuration schema and reference documentation are generated from the same
  source model.

### 7.2 Runtime Discovery and Health

**RUN-001 Inference discovery.** Morpheus queries `/v1/models` and represents all
served aliases, root model identity when provided, and maximum context.

**RUN-002 Behavioral health.** Health distinguishes unreachable, starting,
ready, degraded, incompatible, and unknown states.

**RUN-003 Metrics collection.** Morpheus parses vLLM Prometheus metrics through
a version-tolerant adapter and records availability of expected signals.

**RUN-004 Host telemetry.** The runtime agent reports allowlisted GPU, memory,
disk, process, and Morpheus service state using structured responses.

**RUN-005 Capability report.** The system reports which features are available,
disabled, unhealthy, or blocked by missing dependencies.

**RUN-006 Read-only doctor.** `morpheus doctor` performs configuration, network,
endpoint, storage, clock, image-pin, and service-contract checks without
changing state.

Runtime exit criteria:

- a fixture server covers ready, cold-start, partial JSON, timeout, HTTP error,
  schema drift, and multiple-model responses;
- a live read-only lane correctly identifies the current model and context;
- no runtime probe causes a completion request unless explicitly selected;
- doctor returns stable machine-readable JSON and meaningful process exit codes;
- failure of one probe cannot suppress results from independent probes.

### 7.3 Dashboard

**UI-001 Overview.** The first screen shows inference readiness, loaded model,
GPU memory and activity, request health, storage, and optional service status.

**UI-002 Diagnostics.** Operators can inspect check evidence, timestamps, safe
error summaries, and remediation steps.

**UI-003 Feature controls.** Controls exist only for Morpheus-owned services and
clearly distinguish configured, running, healthy, and usable states.

**UI-004 Honest partial state.** Missing runtime-agent or metrics access renders
a degraded state and never fabricates zero values.

**UI-005 Accessible operation.** Core flows work by keyboard, expose semantic
labels, meet WCAG 2.2 AA contrast, and do not rely on color alone.

Dashboard exit criteria:

- desktop and mobile Playwright flows cover healthy, degraded, empty, loading,
  unauthorized, and recovery states;
- screenshots show no overlap or clipped text at supported viewport sizes;
- the page remains usable when every API request is slow or one request fails;
- the dashboard cannot invoke operations on external resources;
- largest-contentful render on the local target is under two seconds after the
  API becomes available.

### 7.4 Search

**SRCH-001 Private metasearch.** Morpheus can deploy a pinned upstream SearXNG
service with JSON search enabled and persistent, Morpheus-owned configuration.

**SRCH-002 Open WebUI contract.** Morpheus documents and verifies the exact query
URL that the existing Open WebUI can use. Configuration through the Open WebUI
admin interface remains operator-controlled.

**SRCH-003 Safe network posture.** Search is reachable by Open WebUI on the
shared Docker network and is not host-exposed unless explicitly configured.

Search exit criteria:

- a real query returns valid JSON through the container network;
- health checks verify search behavior rather than only TCP connectivity;
- Open WebUI connectivity is proven without editing its database;
- rate-limit, timeout, and upstream-engine failure cases are visible;
- uninstall removes Morpheus search state only when the operator requests it.

### 7.5 Voice

**VOICE-001 Speech-to-text.** Morpheus provides an OpenAI-compatible transcription
endpoint using a pinned upstream service and a CPU-safe default model.

**VOICE-002 Text-to-speech.** Morpheus provides an OpenAI-compatible speech
endpoint using a pinned upstream Kokoro-compatible service.

**VOICE-003 Open WebUI contract.** The documented STT and TTS URLs, model names,
voices, and request formats work with the current Open WebUI.

**VOICE-004 Resource policy.** GPU acceleration is opt-in and rejected when it
would violate the configured GPU headroom policy.

Voice exit criteria:

- fixture audio is transcribed within a documented CPU latency budget;
- generated speech is valid, playable audio with correct content type;
- unsupported formats and oversized uploads fail with bounded, safe errors;
- no audio is retained after the request unless retention is explicitly enabled;
- Open WebUI integration passes microphone-upload and response-playback tests;
- vLLM remains healthy and its container identity is unchanged throughout the
  CPU voice test lane.

### 7.6 Request Telemetry

**TEL-001 OpenAI-compatible proxy.** Morpheus implements its own narrowly scoped
chat-completions proxy with non-buffering streaming behavior.

**TEL-002 Usage accounting.** The proxy records request timing, time to first
token, token counts, finish reason, model alias, outcome, and correlation ID.

**TEL-003 Privacy defaults.** Prompt and response bodies are neither persisted
nor included in metrics. Content retention is a separate explicit policy.

**TEL-004 Authentication.** Clients authenticate to the proxy, and the proxy
uses separately configured upstream credentials when required.

**TEL-005 Backpressure.** Client disconnects, slow consumers, upstream timeouts,
and malformed streaming frames are handled without leaking tasks or sockets.

Telemetry exit criteria:

- byte-level streaming tests prove chunks are forwarded before completion;
- usage agrees with upstream usage fields and marks estimates distinctly;
- no-content logging tests scan logs, database rows, and metrics output;
- load tests meet the recorded overhead budget: under 25 ms added median TTFT
  locally and under 2 percent throughput loss for representative responses;
- cancellation and timeout tests leave no active request or database leak;
- direct vLLM access remains available for rollback.

### 7.7 Workflows and Research

**FLOW-001 Workflow service.** Morpheus can deploy a pinned upstream n8n service
with Morpheus-owned state and authenticated loopback access.

**FLOW-002 Curated templates.** Templates use the configured Morpheus gateway or
external vLLM endpoint and contain no embedded credential or host-specific IP.

**RSCH-001 Deep research.** Morpheus can deploy a pinned Perplexica service wired
to SearXNG and the configured OpenAI-compatible model.

**RSCH-002 Model compatibility.** Research requests use the configured model ID
and preserve the server's no-thinking behavior.

Workflow and research exit criteria:

- clean deployment, upgrade, backup, restore, and uninstall are tested;
- a workflow can call the model and return a structured result;
- a research query returns cited results through SearXNG and vLLM;
- service failure does not degrade direct chat or core Morpheus health;
- imported templates are validated against a versioned schema.

### 7.8 Optional Gateway

**GATE-001 Stable API.** A gateway may expose one authenticated endpoint for the
current vLLM model and future providers.

**GATE-002 Alias control.** External model aliases map deterministically to
upstream model IDs and cannot silently change without configuration evidence.

**GATE-003 Bypass path.** The gateway is optional and a documented direct path
to vLLM remains available.

Gateway exit criteria:

- streaming, tools, structured output, usage, errors, and cancellation pass
  compatibility tests against direct vLLM behavior;
- authentication is enforced on every non-health route;
- removing the gateway requires only a client endpoint change;
- routing configuration is versioned, validated, and free of inline secrets.

### 7.9 Independent RAG

**RAG-001 Explicit need.** Qdrant or a separate embedding server is not enabled
by default because Open WebUI already maintains local vector state.

**RAG-002 Isolated ownership.** When enabled, vector and embedding data is owned
by Morpheus and does not read or mutate Open WebUI's database.

**RAG-003 Portable API.** Ingestion and retrieval use documented service APIs and
versioned collection metadata.

RAG exit criteria:

- an approved use case demonstrates why existing Open WebUI RAG is insufficient;
- deterministic fixtures prove ingest, retrieve, delete, and reindex behavior;
- backup and restore preserve collection integrity;
- model or embedding-version changes require explicit migration or reindex;
- no uploaded document content appears in logs or support bundles.

### 7.10 Image Generation

**IMG-001 Upstream integration.** Morpheus integrates upstream ComfyUI using its
documented API and Morpheus-owned models, input, output, and workflow paths.

**IMG-002 GPU safety interlock.** Start is blocked when configured free-memory,
temperature, process, or ownership checks fail.

**IMG-003 Explicit transition.** Any action that would stop or restart external
inference is outside normal Morpheus ownership and requires an operator-run,
separately authorized transition workflow.

**IMG-004 Recovery evidence.** The transition workflow records the verified
pre-state and proves that inference returned to the same image, model revision,
arguments, and healthy endpoint afterward.

Image exit criteria:

- ComfyUI creates a deterministic smoke-test image from a versioned workflow;
- Open WebUI can submit and retrieve an image through the documented API;
- an unsafe concurrent-start attempt fails before GPU allocation;
- interruption at every transition step has a tested recovery path;
- inference restoration matches the recorded pre-state and passes a completion
  smoke test;
- generated images and prompts follow explicit retention settings.

### 7.11 Backup, Restore, and Support

**OPS-001 Scoped backup.** Backups include Morpheus configuration, database,
service state, and metadata but exclude model caches and external service data.

**OPS-002 Atomic restore.** Restore validates format, checksum, free space, and
schema compatibility before replacing state.

**OPS-003 Support bundle.** Bundles include versions, health evidence, sanitized
configuration, and recent structured errors without secrets or user content.

Operational exit criteria:

- backup and restore round-trip tests compare logical state;
- corrupt, partial, incompatible, and malicious archives fail safely;
- path traversal and symlink escape tests pass;
- restore failure leaves the prior state usable;
- automated secret/content canaries are absent from support bundles;
- uninstall defaults to preserving Morpheus data and always preserves external
  runtime data.

## 8. Security Requirements

**SEC-001 Authentication.** State-changing and sensitive diagnostic APIs require
authentication. Health endpoints reveal minimal information.

**SEC-002 Authorization.** Every operation is authorized against resource type,
Morpheus ownership label, and allowed action.

**SEC-003 Request safety.** APIs enforce body limits, timeouts, content types,
schema validation, and bounded concurrency.

**SEC-004 Browser safety.** Sessions use secure signing, CSRF protection where
applicable, restrictive CORS, content security policy, and safe cookie defaults.

**SEC-005 Supply chain.** Dependencies are locked; release images are pinned by
digest, scanned, and accompanied by an SBOM.

**SEC-006 Filesystem safety.** Paths are canonicalized and constrained to owned
roots. Archives, uploads, and generated filenames cannot escape those roots.

**SEC-007 Network policy.** Sidecars communicate on explicit networks. Services
without browser-facing UIs do not publish host ports by default.

Security exit criteria:

- threat model covers browser, API, runtime agent, Docker, shared network,
  upstream model, uploads, backups, and optional LAN access;
- authorization tests prove external containers cannot be targeted;
- security headers, CORS, CSRF, rate limits, and session expiry are tested;
- dependency, container, secret, and static security scans are green;
- a clean support bundle passes automated secret and content canary scans;
- no critical or high vulnerability is accepted without a documented exception,
  compensating control, owner, and expiration date.

## 9. Reliability and Performance Requirements

**REL-001 Isolation.** Optional service failure cannot stop the core API,
dashboard, existing vLLM, or Open WebUI.

**REL-002 Bounded work.** Retries use exponential backoff with jitter and hard
deadlines. Queues and concurrency are bounded.

**REL-003 Idempotence.** Repeating install, start, stop, migrate, backup, and
restore-preflight operations yields a defined, tested result.

**REL-004 Time semantics.** Stored timestamps are UTC and monotonic clocks are
used for durations.

**PERF-001 Core overhead.** With telemetry disabled, Morpheus causes no request
path overhead for direct vLLM or Open WebUI traffic.

**PERF-002 Resource budget.** Core Morpheus services target less than 1 GiB
combined steady-state memory and less than 2 percent idle CPU on the target host.

**PERF-003 Dashboard polling.** Polling is consolidated, cancelable, and backs
off when the page is hidden or dependencies are unhealthy.

Reliability exit criteria:

- fault-injection tests cover unavailable DNS, connection refusal, timeout,
  malformed data, disk full, read-only filesystem, database lock, process death,
  and restart during migration;
- a 24-hour soak test shows no unbounded memory, task, connection, log, or
  database growth;
- idle and active resource budgets are measured and recorded;
- external runtime integrity checks pass before and after every destructive
  Morpheus test lane.

## 10. Release-Level Exit Criteria

A Morpheus release is eligible for stable use only when all requirements assigned
to that release have linked automated tests and the following are true:

1. A clean machine bootstrap uses documented, locked dependencies.
2. Unit, contract, integration, acceptance, browser, security, and packaging
   gates pass from a clean checkout.
3. The live read-only compatibility lane passes against the current vLLM service.
4. Install, upgrade, backup, restore, rollback, and uninstall are demonstrated.
5. External runtime identity and health are unchanged across those operations.
6. Default network exposure is verified from both host and LAN perspectives.
7. No secret, prompt, response, document, or audio canary appears in logs,
   metrics, database exports, or support bundles unexpectedly.
8. Performance and 24-hour soak budgets pass with recorded evidence.
9. Accessibility and responsive-layout checks pass on supported browsers.
10. Operator setup, troubleshooting, recovery, and security documentation is
    complete and has been followed by a person starting from a clean checkout.
11. Release artifacts include checksums, dependency locks, image digests, SBOM,
    migration version, and a signed validation report.
12. Known limitations and deferred requirements are explicit and contain no
    unsupported claim of readiness.

## 11. Requirement Traceability

Every implementation pull request must list the requirement IDs it affects.
Acceptance tests use requirement IDs in test names or metadata. The release
validation report is generated from the mapping:

```text
requirement -> test evidence -> build artifact -> release decision
```

A requirement without evidence is not complete. A test without a requirement
or defect reference is reviewed as unowned scope.
