# Morpheus Product Specification

Status: Draft v0.2 product direction; v0.1 remains the deployed read-only baseline

Specification version: 0.2

Stable v0.2 targets: Ubuntu 26.04 LTS x86-64, Windows 11 x86-64, and
macOS 14 or later on Apple Silicon, discovered and validated individually

Primary use case: Focused local developer-inference appliance

## 1. Purpose

Morpheus is an independent appliance for selecting, installing, benchmarking,
serving, and operating serious local developer-focused AI inference. It discovers
the current machine, filters model and engine combinations by hard compatibility
constraints, ranks viable candidates against an operator-selected workload,
and preserves the evidence behind every recommendation.

Morpheus supports two explicit operating modes. **Observe mode** retains the
v0.1 behavior: an existing OpenAI-compatible runtime remains externally owned
and Morpheus only inspects it. **Managed mode** allows Morpheus to own a separate
inference engine, model artifacts, generated configuration, service lifecycle,
benchmark history, and rollback state. An external runtime never becomes managed
implicitly; adoption requires a separately confirmed migration with a captured
pre-state and recovery plan.

The initial deployment target is the current server:

- inference container: `history-coder`
- inference API on shared Docker network: `http://history-coder:8000/v1`
- host inference API: `http://127.0.0.1:8082/v1`
- served model: `qwen36-27b-nvfp4`
- chat interface: existing Open WebUI on host port `3000`
- external Docker network: `ai_default`

These values describe the deployed v0.1 baseline. They are not hard-coded v0.2
assumptions. ubuntu-1 and ubuntu-2 remain named Linux validation machines. A
stable v0.2 release additionally requires a qualified Windows 11 x86-64 host and
an Apple Silicon macOS host, each with checksummed machine, install,
engine, benchmark, lifecycle, access, and recovery evidence.

## 2. Product Principles

1. **Explicit inference ownership.** Morpheus never mutates an observed external
   runtime. It may install and control only a separately identified
   Morpheus-owned managed runtime or a runtime transferred through an approved
   adoption workflow.
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
9. **Workload-specific recommendations.** “Best” is defined by declared developer
   priorities and measured evidence, not popularity, parameter count, or an
   unsupported universal ranking.
10. **Plan, approve, apply.** Downloads, configuration changes, promotions, and
    removals are previewed and confirmed. Every applied plan is attributable and
    reversible when its contract says it is.
11. **Focused product scope.** Morpheus prioritizes developer inference selection,
    operation, benchmarking, and diagnosis over a broad catalog of unrelated AI
    applications.
12. **Portable experience, native execution.** Morpheus presents the same typed
    workflows and evidence model across supported systems while selecting native
    host, service, telemetry, model-format, and engine adapters from measured
    platform capabilities.

## 3. Users and Primary Workflows

### 3.1 Operator

The operator needs to:

- discover the machine's CPU, memory, accelerators, storage, and runtime support;
- receive ranked model, quantization, engine, context, and concurrency plans;
- understand why a candidate fits, what it optimizes, and the confidence of the
  supporting evidence;
- stage, benchmark, promote, operate, upgrade, and roll back Morpheus-owned
  inference safely;
- see whether inference and optional services are actually usable;
- identify the loaded model and its supported context;
- inspect GPU, memory, disk, request, and error signals;
- diagnose failures without disclosing secrets or conversation content;
- enable or disable Morpheus-owned capabilities safely;
- back up and restore Morpheus state;
- know that the existing AI service will not be changed.

For the primary developer-inference workflow, the operator can favor coding,
tool use, agentic reliability, long-context work, interactive latency,
throughput, concurrency, memory headroom, or a documented weighted combination.

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

### 4.2 Focused Developer-Inference Appliance

- portable host and accelerator discovery for declared target platforms;
- versioned model and engine catalogs with compatibility and provenance;
- explainable workload-specific recommendation and capacity planning;
- Morpheus-owned model and engine installation with staged promotion and rollback;
- repeatable benchmark campaigns with durable history and comparison;
- live inference metrics, redacted logs, analytics, settings, and lifecycle UI;
- configurable local or API-assisted diagnosis constrained to sanitized evidence;
- loopback and SSH-tunnel operation by default, with separately approved secure
  network access.

### 4.3 Legacy Optional Capability Set

- SearXNG search integration;
- CPU-first Whisper-compatible speech-to-text;
- CPU Kokoro-compatible text-to-speech;
- Morpheus request telemetry and usage dashboard.

### 4.4 Legacy Extended Capability Set

- n8n workflow service and curated templates;
- Perplexica deep research integration;
- optional LiteLLM-compatible gateway for routing and authentication;
- optional independent vector and embedding services when justified.

### 4.5 Legacy Coordinated GPU Capability

- ComfyUI integration;
- explicit GPU workload safety checks;
- an operator-confirmed transition between inference and image workloads;
- recovery to the previously verified inference state.

## 5. Explicit Non-Goals

The following are out of scope for the focused v0.2 release:

- GPU driver, Docker Engine, or NVIDIA Container Toolkit installation;
- training, fine-tuning, or automatic quantization/conversion pipelines;
- silent model download, promotion, replacement, or deletion;
- implicit management of `history-coder`, Open WebUI, or the `ai` Compose project;
- replacing Open WebUI with a Morpheus chat product;
- becoming a broad AI application suite equivalent to ODS;
- prioritizing search, voice, research, workflow, RAG, or image-generation
  expansion ahead of the focused inference-appliance milestones;
- copying or wrapping the ODS installer, CLI, dashboard API, or host agent;
- public internet exposure, hosted multi-tenancy, or a fleet-wide control plane;
- silent mutation of Open WebUI's database or persistent configuration;
- an autonomous agent with unrestricted shell or Docker access;
- claiming compatibility with platforms that have no validation evidence.

## 6. System Invariants

### INV-001 External Runtime Integrity

Install, start, stop, upgrade, failure recovery, and uninstall operations must
leave the external inference and Open WebUI containers, images, volumes, bind
mounts, networks, configuration, and restart counts unchanged.

This invariant applies to observe mode and throughout any managed-runtime
staging operation. A separately authorized adoption workflow may change an
external runtime only after it has captured the exact pre-state, displayed the
ownership transfer, obtained confirmation, and established a tested rollback.

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

### INV-007 Managed Runtime Isolation

Managed inference resources use Morpheus-owned roots, labels, manifests,
credentials, ports, and lifecycle state. Resource names alone never establish
ownership, and observe-mode targets cannot appear in an ordinary managed action.

### INV-008 Recommendation Integrity

Every recommendation records its catalog versions, machine profile, hard
constraints, workload weights, estimates, benchmark evidence, confidence, and
known unknowns. Unsupported or stale evidence lowers confidence or blocks the
claim; it never becomes an optimistic default.

### INV-009 Reversible Promotion

Installing an artifact is distinct from promoting it to serve traffic. Promotion
requires preflight, an immutable deployment plan, health and benchmark gates,
explicit confirmation, a preserved last-known-good plan, and bounded rollback.

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

### 7.8 Bounded Compatibility Layer

**GATE-001 Stable API.** When enabled, the bounded Morpheus compatibility layer
exposes one authenticated endpoint for the selected managed runtime. This
requirement does not introduce LiteLLM, automatic provider routing, or a broad
multi-provider control plane.

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

### 7.12 Host Discovery and Compatibility

**HOST-001 Machine profile.** Morpheus produces a versioned, privacy-reviewed
profile of CPU architecture and features, system memory, accelerator vendor and
capabilities, accelerator memory and topology, storage capacity, operating
system, container/runtime prerequisites, and relevant driver/API versions.

**HOST-002 Compatibility profile.** Discovery normalizes vendor-specific facts
into typed capabilities used by model and engine constraints. Missing access is
reported as unknown evidence and never treated as absent hardware or zero
capacity.

**HOST-003 Target validation.** ubuntu-1, ubuntu-2, one Windows 11 x86-64 host,
and one Apple Silicon macOS host each have reproducible discovery and smoke
evidence. Additional platform combinations are described as unvalidated until
their own hardware, engine, install, benchmark, lifecycle, and recovery lanes
pass.

Host discovery exit criteria:

- repeated discovery on unchanged hardware produces the same stable identity
  fields while separating volatile utilization data;
- discovery uses an allowlisted read-only agent surface and retrieves no host
  secret values;
- fixtures cover NVIDIA, non-NVIDIA, CPU-only, multi-device, partial access, and
  unsupported environments;
- machine profiles can be safely exported with benchmark results for comparison.

### 7.13 Model, Engine, and Configuration Recommendation

**SEL-001 Versioned catalogs.** Morpheus maintains independently refreshable
model and engine catalogs containing immutable source identity, license,
architecture, modalities, formats, quantizations, context claims, engine
support, feature compatibility, artifact sizes, and validation freshness.

**SEL-002 Hard compatibility.** Recommendation first rejects combinations that
cannot fit declared accelerator/RAM/storage budgets, lack engine or hardware
support, violate licensing or trust policy, or cannot supply required context,
tool, structured-output, or reasoning behavior.

**SEL-003 Developer workload profile.** The operator selects or customizes a
versioned workload that weights coding correctness, tool use, agentic behavior,
long-context coherence, time to first token, decode throughput, concurrency,
stability, memory headroom, and power/resource cost.

**SEL-004 Explainable ranking.** Viable model, quantization, engine, context,
concurrency, and launch-configuration plans are ranked with per-factor scores,
hard constraints, evidence provenance, confidence, tradeoffs, and the reason a
higher-profile candidate was excluded.

**SEL-005 Operator authority.** Recommendations never download, install,
promote, or remove a model automatically. Operators can adjust constraints and
weights, preview the resulting plan, and deliberately choose a lower-ranked
candidate without falsifying the recorded recommendation.

Recommendation exit criteria:

- deterministic fixtures cover ubuntu-1-like, ubuntu-2-like, CPU-only,
  insufficient-storage, unsupported-format, stale-catalog, and ambiguous cases;
- resource estimates declare safety margins and are calibrated against measured
  startup and benchmark observations;
- catalog updates cannot silently change an installed plan or historical score;
- identical machine, catalog, policy, and workload inputs produce identical
  rankings.

### 7.14 Managed Inference Runtime

**RUNM-001 Dual operating modes.** Every inference target is explicitly
external-observed or Morpheus-managed. API, CLI, UI, audit, and agent requests
carry that ownership mode and reject ambiguous or cross-mode actions. An
adoption candidate is a workflow-scoped transfer record, not a third ownership
mode or an ordinary lifecycle target.

**RUNM-002 Engine adapters.** Managed engines implement a typed contract for
capability detection, immutable configuration rendering, preflight, start,
health, metrics, logs, graceful stop, and cleanup. Native
`llama.cpp`/`llama-server` is the common stable engine path; a separate vLLM tier
is stable on qualified Linux NVIDIA targets. Other engines and platform paths
remain optional, experimental, or unsupported until their complete evidence
lane passes.

**RUNM-003 Verified installation plan.** Model and engine acquisition uses
immutable revisions, checksums or signed manifests, license/trust policy,
declared disk impact, resumable staging, and owned cache roots. GPU drivers and
host container prerequisites remain operator-managed.

**RUNM-004 Stage, benchmark, and promote.** New combinations are staged away
from the active endpoint, validated for startup and API behavior, benchmarked
under declared limits, and promoted only after their acceptance gates and an
operator confirmation pass.

**RUNM-005 Rollback and adoption.** Morpheus preserves a last-known-good managed
deployment and can roll back failed configuration, engine, or model changes. A
separate adoption workflow can migrate an existing external runtime only with
exact pre-state capture, explicit ownership transfer, and tested restoration.

**RUNM-006 Exclusive-resource safety.** GPU-exclusive campaigns and runtime
transitions use fresh capacity and foreign-process evidence, declared workload
limits, abort criteria, durable checkpoints, and recovery. Morpheus never starts
two incompatible full-GPU runtimes merely to compare them.

Managed-runtime exit criteria:

- ordinary management can target only exact Morpheus-owned manifests and roots;
- interruption is tested at download, staging, engine startup, health,
  benchmark, promotion, and rollback boundaries;
- the active endpoint exposes its exact model, engine, revision, configuration,
  context, and ownership state;
- every advertised stable OS/architecture/accelerator/engine tier passes install,
  restart, upgrade, rollback, uninstall, storage-pressure, and recovery
  validation on physical target hardware.

### 7.15 Benchmark Campaigns and History

**BENCH-001 Developer benchmark suite.** Morpheus runs versioned speed,
time-to-first-token, coding, tool-use, structured-output, agentic, long-context,
concurrency, stability, and resource workloads appropriate to the selected
developer profile.

**BENCH-002 Complete provenance.** Every campaign records stable machine
identity, model source and revision, artifact digest, quantization, engine image
or build, launch configuration, context, concurrency, benchmark revision,
workload parameters, warm-up, timestamps, errors, and environmental caveats.

**BENCH-003 Durable result store.** Raw observations, normalized summaries, and
comparisons are stored with versioned schemas and retention/export policy. The
existing `history-tool-tests` JSONL history can be imported without rewriting or
misrepresenting its original evidence.

**BENCH-004 Comparison and regression.** Operators can compare campaigns across
model, engine, configuration, software version, benchmark revision, and machine.
The UI distinguishes comparable results, normalized estimates, and invalid
apples-to-oranges comparisons and reports run variation rather than a single
unqualified percentage.

**BENCH-005 Safe execution.** Campaigns declare duration, request shape,
concurrency, resource envelope, stop conditions, and ownership target. Real load
against an observed external runtime remains separately authorized and cannot be
started through a routine dashboard refresh or diagnostic action.

Benchmark exit criteria:

- the canonical suite can reproduce the current history coding, tools, speed, and
  long-context comparisons with a documented import mapping;
- results survive restart, backup, restore, schema migration, and export;
- incomplete, interrupted, cache-contaminated, or configuration-mismatched runs
  remain visible but cannot become recommendation evidence silently;
- repeated campaigns publish sample counts, dispersion, and regression
  thresholds alongside medians or other selected statistics.

### 7.16 Focused Operations Workspace

**OUI-001 Operational navigation.** The authenticated operations application,
delivered through the desktop shell or loopback browser surface, provides clear
workspaces for Overview, Hardware, Models, Engines, Runtime, Benchmarks,
Analytics, Logs and Events, Diagnostics, Settings, and Recovery without becoming
a replacement chat interface.

**OUI-002 Live and historical metrics.** Operators can inspect accelerator
memory, utilization, temperature and power when available; host memory and
storage; request concurrency and queueing; KV-cache use; token rates; TTFT;
throughput; errors; restarts; and bounded historical trends with explicit units,
timestamps, gaps, and freshness.

**OUI-003 Redacted logs and events.** Morpheus collects or streams only approved
service and engine log sources, normalizes severity and correlation fields,
applies redaction before persistence or display, supports bounded search and
filtering, and links relevant events to deployments, campaigns, and diagnoses.

**OUI-004 Analytics and comparisons.** Dashboard views expose benchmark history,
before/after software and configuration comparisons, model/engine scorecards,
usage and reliability summaries, regressions, and recommendation evidence.

**OUI-005 Validated settings.** Operators edit typed public settings through
schema-generated forms with source, default, impact, validation, secret-file
separation, plan preview, diff, restart requirement, and rollback information.

**OUI-006 Managed workflows.** Model acquisition, engine installation,
configuration, benchmark, promotion, rollback, and removal are multi-step,
authenticated workflows with preflight, progress, cancellation behavior,
confirmation, audit evidence, and precise recovery instructions.

Operations-workspace exit criteria:

- pages remain honest and usable during partial agent, metrics, log, database,
  catalog, and engine failures;
- charts and colors have textual equivalents, keyboard flows, accessible
  semantics, responsive layouts, and bounded rendering/data-query budgets;
- no browser route accepts arbitrary paths, commands, model URLs, engine flags,
  or external resource names;
- high-impact actions are visually and technically separated from observation.

### 7.17 AI-Assisted Diagnosis

**AID-001 Diagnostic evidence package.** Morpheus builds a bounded, redacted
package from structured health, machine profile, deployment manifest, metrics,
events, selected log excerpts, benchmark regressions, and known runbooks without
including prompts, responses, secrets, or unrestricted host data.

**AID-002 Configurable provider.** Diagnosis can be disabled, use an explicitly
selected local model, or use a configured external API. Provider capabilities,
data destination, retention implications, timeout, cost limits, and consent are
shown before evidence leaves the host.

**AID-003 Explainable findings.** Responses separate observations, inferences,
confidence, missing evidence, likely causes, and proposed checks and cite the
local evidence items or runbooks supporting each material conclusion.

**AID-004 Advisory boundary.** The diagnostic model receives no arbitrary shell,
Docker, file, secret, install, promotion, or deletion tool. Proposed actions are
converted into ordinary typed Morpheus plans that require independent policy,
preflight, and operator authorization.

AI-diagnosis exit criteria:

- adversarial logs and model output cannot inject an executable operation;
- privacy canaries are absent from local and remote provider requests;
- provider failure never blocks ordinary diagnostics or runtime operation;
- deterministic fixtures evaluate evidence grounding, uncertainty, and unsafe
  recommendation rejection before any live provider is enabled.

### 7.18 Secure Access and Target Portability

**ACCESS-001 Local and SSH access.** Loopback binding with authenticated browser
sessions and documented SSH tunneling remains the default on every target.

**ACCESS-002 Optional network access.** Direct LAN or remote browser access is a
separate profile requiring TLS, explicit interface policy, trusted identity or
strong local credentials, origin controls, rate limits, session revocation, and
host/LAN exposure tests.

**ACCESS-003 Evidence-bounded support.** A target is advertised as supported only
for the exact operating system, architecture, accelerator, engine, install,
benchmark, lifecycle, access, and recovery combinations covered by retained
evidence. ubuntu-1 and ubuntu-2 prove named Linux paths only; Windows and macOS
support require their own physical evidence.

Secure-access exit criteria:

- loopback surfaces are unreachable from a peer without an SSH tunnel;
- tunnel teardown and session revocation terminate access predictably;
- optional TLS mode passes certificate, cookie, CSRF, CORS, origin, proxy-header,
  and brute-force/rate-limit tests;
- support reports never claim broader hardware or engine compatibility than the
  attached target evidence.

### 7.19 Cross-Platform Backend and Desktop

**PLAT-001 Normalized platform capabilities.** The machine profile identifies
operating-system family and version, architecture, accelerator and compute API,
native process and service facilities, engine prerequisites, and evidence
freshness. Every capability value is `known`, `unavailable`,
`permission_denied`, or `unsupported`; missing evidence is never represented as
zero or false compatibility.

**PLAT-002 Native host adapters.** Host inspection, filesystem ownership,
durable replacement, secret protection, process-tree supervision, service
lifecycle, and hardware telemetry are implemented behind typed ports with
separate Linux, Windows, and macOS adapters. Docker Compose is a Linux runtime
adapter, not the portable host abstraction.

**PLAT-003 Independent backend service.** The backend is a separately versioned,
target-native package registered as a per-user background service by default.
Closing the desktop application does not stop the backend or managed inference.
Backend install, repair, upgrade, rollback, and removal are checksummed,
health-gated, ownership-bounded, and independently testable. Public signing and
Apple notarization are optional distribution-hardening lanes; unsigned packages
are labeled developer/source-qualified and cannot update unattended.

**PLAT-004 Evidence-bounded engine tiers.** Stable v0.2 provides a qualified
native `llama.cpp` managed path on Ubuntu x86-64, Windows x86-64, and Apple
Silicon macOS, plus a qualified vLLM tier on Linux NVIDIA. Ollama is optional;
Windows vLLM through WSL2 and Apple vLLM-Metal/MLX begin as experimental. Intel
Macs and other unqualified combinations are reported honestly without a stable
support claim.

**DESK-001 Tauri desktop shell.** Tauri 2 packages the existing strict
TypeScript/React workspace for Windows, Linux, and macOS. It communicates only
through the versioned Control API, exposes no general shell or filesystem
capability to the webview, and shares feature behavior with the loopback browser
application.

**DESK-002 Backend compatibility and bootstrap.** Desktop startup performs an
authenticated `GET /api/v1/system/compatibility` handshake. The desktop supplies
its semantic version in `X-Morpheus-Desktop-Version`; the response contains API
and backend versions, supported desktop version range, OS and architecture,
enabled adapter identities and tiers, supported operations, and compatibility
status. A missing or incompatible local backend produces a package-trust-aware
install/repair/update plan and requires confirmation; it never silently replaces
a running service. Unsigned developer packages require local checksum
verification and cannot use unattended bootstrap or update.

**DESK-003 Local and remote parity.** The desktop can connect to its local
backend or a backend reached through an operator-established SSH tunnel. The
same API authorization, ownership checks, workflows, progress, cancellation,
and recovery semantics apply to desktop, browser, CLI, and remote-tunneled use.

Cross-platform exit criteria:

- target-native backend and desktop artifacts are built on native CI runners,
  checksummed, version-inventoried, and accompanied by an SBOM; package manifests
  distinguish developer/source-qualified from optional signed-distribution-
  qualified artifacts;
- Ubuntu uses a per-user systemd service, Windows uses per-user background
  registration, and macOS uses a LaunchAgent; elevated always-on system service
  mode is deferred;
- Windows junction/reparse-point, POSIX symlink, ACL/mode, locked-file,
  process-tree cancellation, sleep/resume, interrupted-update, and low-disk
  cases fail safely and preserve the last-known-good deployment;
- desktop close/reopen, backend restart, machine reboot, desktop/backend version
  mismatch, browser fallback, and SSH-tunneled reconnection pass on every stable
  target;
- stable release evidence covers Ubuntu 26.04 x86-64, Windows 11 x86-64, and
  macOS 14 or later on Apple Silicon with at least one native managed engine.

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
2. Unit, contract, integration, acceptance, browser, desktop, security, and
   target-native packaging gates pass from a clean checkout.
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
    migration version, and a checksummed validation report. Public artifact and
    report signing is an optional signed-distribution qualification.
12. Known limitations and deferred requirements are explicit and contain no
    unsupported claim of readiness.
13. Physical qualification passes on Ubuntu 26.04 x86-64, Windows 11 x86-64,
    and macOS 14 or later on Apple Silicon with at least one stable native
    managed-inference path on each.

## 11. Requirement Traceability

Every implementation pull request must list the functional requirement IDs and
cross-cutting `INV-*` constraints it affects. `requirements.json` tracks status,
tasks, and evidence for functional requirements; invariants are mandatory
acceptance constraints traced through the functional requirements they protect
rather than separate status rows. Acceptance tests use functional, invariant,
or explicitly declared delivery-milestone IDs such as `VSLICE-001` in test names
or metadata. Delivery milestones exercise integration order but never substitute
for functional-requirement completion. The release validation report is
generated from the mapping:

```text
requirement -> test evidence -> build artifact -> release decision
```

A functional requirement without an owning test cannot be `implemented`; one
without all required retained passing evidence cannot be `validated`. A test
without a functional requirement, invariant, delivery milestone, or defect
reference is reviewed as unowned scope.
