# Morpheus Release Validation Plan

Status: In progress

Updated: 2026-07-15

This document turns the release-level exit criteria into an executable,
dependency-ordered checklist. A green development gate is necessary but does
not make Morpheus eligible for stable use. Every task below must produce
reviewable evidence or an explicit, approved deferral.

## 1. Non-Negotiable Boundaries

- The active `history-coder` vLLM service and Open WebUI are externally owned.
- Ordinary CI, VM, browser, fault, load, and soak tests use disposable fakes or
  Morpheus-owned services.
- Live tests are opt-in and read-only unless the user explicitly authorizes a
  named mutation in the current request.
- No live test restarts, recreates, stops, reconfigures, or writes to the
  external inference or Open WebUI deployment.
- GPU-exclusive and external-state tests require a separate maintenance window,
  pre-state capture, confirmation, rollback, and post-state comparison.
- Secrets, prompts, responses, documents, audio, model data, databases, and raw
  host inventories never enter Git or ordinary CI artifacts.

## 2. Priority, Environment, and Evidence Model

Priorities are execution order, not estimates:

| Priority | Meaning |
|---|---|
| P0 | Lab, traceability, or evidence blocker required by later work |
| P1 | Clean bootstrap, build, core startup, and early security gate |
| P2 | Install, upgrade, backup, rollback, uninstall, and integrity |
| P3 | Live read-only, optional-service, and browser compatibility |
| P4 | Fault, performance, resource, and 24-hour soak validation |
| P5 | Final supply-chain evidence, documentation, and release decision |

Execution environments:

| Code | Environment | Permitted state |
|---|---|---|
| DEV | Local checkout or CI | Repository and disposable test state only |
| VM | Disposable `morpheus-validation` guest | Any declared lab mutation |
| HOST-RO | ubuntu-1 against external services | Read-only observations only |
| HOST-MAINT | ubuntu-1 maintenance window | Only the explicitly authorized operation |

Every evidence-producing run uses an identifier such as
`20260715T180000Z-<commit>` and writes only to the ignored directory
`artifacts/release-validation/<run-id>/`. The run manifest records:

- commit and candidate artifact checksums;
- task IDs, requirement IDs, environment, start/end UTC, and tool versions;
- pass, fail, blocked, or deferred status with a safe summary;
- redacted logs and structured results;
- pre-state and post-state digests where integrity is relevant;
- reviewer and explicit authorization reference for live or stateful work.

## 3. Validation Lab Prerequisites

### 3.1 ubuntu-1 Host

Current verified state:

- [x] Ubuntu 26.04 LTS on x86-64 with AMD-V and IOMMU enabled.
- [x] KVM, QEMU, libvirt, `virt-install`, OVMF, SWTPM, and cloud-image tools.
- [x] `operator` has direct `libvirt` and `docker` group access.
- [x] Libvirt `default` NAT network is active and persistent on
  `192.168.122.0/24`; it does not overlap the LAN or Docker networks.
- [x] Libvirt `default` storage pool is active, persistent, empty, and has about
  1.5 TiB available under `/var/lib/libvirt/images`.
- [x] A transient guest exercised libvirt, enforcing AppArmor, QEMU/KVM, and a
  virtio NIC successfully, then left no VM or disk behind.
- [x] Docker Engine, Compose, Git, Make, `uv`, curl, jq, OpenSSL, SSH, and rsync.
- [x] NVIDIA driver and Container Toolkit for later host-only observation.
- [x] Host NTP is enabled and synchronized; hardware clock remains in UTC.
- [ ] Record a redacted host baseline and external-resource identity snapshot.

`/mnt/data` is mounted read-only and is outside the validation lab. VM disks use
the standard libvirt pool on the system NVMe.

### 3.2 Disposable Guest Baseline

Create one reproducible Ubuntu 26.04 cloud-image guest with:

- 12 vCPUs, 32 GiB RAM, and a 160 GiB sparse qcow2 disk;
- UEFI, virtio disk/network, QEMU guest agent, and serial console;
- libvirt NAT only, no LAN bridge, port forward, shared host directory, GPU, or
  Docker socket from ubuntu-1;
- a dedicated SSH key and an unprivileged `operator` user with sudo;
- Docker Engine and Compose, Git, Make, curl, jq, rsync, OpenSSH, CA
  certificates, pipx, and a project-pinned `uv`;
- automatic security updates disabled during a single reproducibility run but
  applied and recorded when the baseline image is refreshed;
- cloud-init completion, package versions, disk, memory, time sync, DNS, Docker,
  and outbound HTTPS verified before sealing the baseline;
- no Morpheus checkout, image, volume, secret, or test result in the sealed
  baseline.

Record the official cloud-image URL, SHA-256, release date, package manifest,
cloud-init input digest, and resulting baseline disk digest. Preserve the base
volume as read-only and clone it for every clean-install scenario.

ubuntu-1 status on 2026-07-15: complete. The powered-off, non-autostarting
`morpheus-validation-base` domain has a read-only 160 GiB disk definition and
no seed attached. The checksum-verified Ubuntu release image, secret-free
cloud-init inputs, package inventory, sealed disk digest, and successful
independent-clone boot are recorded in the ignored local LAB-001 evidence. No
Morpheus or external-service state is present in the baseline.

### 3.3 Test Tooling Policy

Specialized tools run from version-and-digest-pinned containers rather than
being installed globally:

- Node for dashboard formatting, typing, unit tests, and production build;
- Playwright with a version exactly matching `@playwright/test`;
- an accessibility engine integrated into Playwright;
- Trivy or equivalent for application and image vulnerability scanning;
- Syft or equivalent for SPDX and CycloneDX SBOM generation;
- Gitleaks or equivalent for repository and artifact secret scanning;
- k6 or a purpose-built checked-in client for load and soak traffic.

Tool selection, version, image digest, license, update owner, and invocation are
committed before the tool can produce release evidence. Scanners never receive
production credentials or private content.

### 3.4 Lab-Only Configuration

The VM must provide:

- a disposable external Docker network with a fixture OpenAI-compatible server;
- deterministic `/v1/models`, chat, streaming, metrics, slow, malformed, and
  unavailable fixtures;
- generated lab-only API, agent, session, upstream, and workflow keys;
- canary prompt, response, document, audio, and secret values that are safe to
  destroy and are never used outside the VM;
- a second network perspective: ubuntu-1 probes the guest's libvirt address to
  prove loopback-only publications are unreachable externally;
- separate volumes for baseline state, upgrade state, backup output, and
  disposable optional-service data.

## 4. P0 — Lab, Traceability, and Evidence Blockers

- [x] **LAB-001 — Seal the clean VM baseline.** Complete section 3.2, shut down
  cleanly, preserve the base volume, and prove a clone boots independently.
  Environment: VM. Evidence: image and cloud-init digests, package inventory,
  guest-agent status, and clone smoke result.
- [ ] **LAB-002 — Add a clean Docker build context.** Commit `.dockerignore`
  rules excluding Git state, virtual environments, caches, coverage, build
  output, artifacts, databases, secrets, and frontend dependencies. Prove clean
  and dirty developer trees produce identical build inputs. Environment: DEV.
- [ ] **LAB-003 — Build the fixture external stack.** Implement deterministic
  OpenAI, metrics, slow/error, and streaming fixtures plus a disposable external
  network. It must never resolve or route to ubuntu-1's external AI services.
  Environment: VM.
- [ ] **LAB-004 — Give concurrent scenario clones unique identity.** Regenerate
  hostname, machine ID, cloud-init instance identity, and SSH host keys without
  changing the sealed base. Prove two clones can run together without identity
  or known-host collisions. Until this passes, the runner must reject concurrent
  clones and execute scenarios serially. Environment: VM.
- [ ] **EVID-001 — Implement the evidence runner.** Create run directories,
  structured manifests, redaction, checksums, tool inventories, and explicit
  pass/fail/blocked states. Environment: DEV/VM.
- [ ] **EVID-002 — Prove evidence privacy.** Seed every canary class and scan all
  logs, metrics, database exports, support bundles, screenshots, traces, and
  reports. Only deliberately hashed canary identifiers may remain. Requirements:
  CFG-002, TEL-003, OPS-003, SEC-005.
- [ ] **TRACE-001 — Expand requirement metadata.** For every entry in
  `requirements.json`, record owning tests, risk, required environment, live or
  hardware evidence, first satisfying version, and real status. CI must reject
  `validated` without linked green evidence.
- [ ] **TRACE-002 — Perform an implementation gap review.** Reconcile the
  current code against every product requirement. Existing component tests do
  not by themselves establish completion. Record missing product behavior as
  implementation tasks before scheduling validation.
- [ ] **TOOL-001 — Pin release-validation tools.** Record Node, Playwright,
  accessibility, secret-scan, vulnerability-scan, SBOM, license, and load-tool
  images by immutable digest and license.
- [ ] **ART-001 — Define the candidate artifact set.** Versioned Python sdist and
  wheel, backend and dashboard OCI images, Compose/config bundle, migrations,
  requirements evidence, checksums, and rollback inputs must come from one
  commit and one reproducible build.

P0 exit gate: a fresh VM clone can run fixtures and the evidence runner without
accessing external services; every later task has requirements, dependencies,
environment, safety classification, and evidence shape.

## 5. P1 — Clean Bootstrap, Core Containers, and Early Security

- [ ] **CLEAN-001 — Clean-checkout bootstrap.** Clone the candidate into a fresh
  VM clone, follow only committed documentation, install locked dependencies,
  and run backend and frontend gates. No developer cache or host bind mount is
  allowed. Requirements: REL-004 and release criterion 1.
- [ ] **CLEAN-002 — Offline rebuild from populated caches.** After one declared
  dependency-fetch step, disconnect outbound networking and reproduce the
  Python artifacts and application images from pinned inputs.
- [ ] **BUILD-001 — Reproducible candidate build.** Build twice from separate VM
  clones with normalized metadata. Compare application payloads and explain any
  unavoidable image-manifest differences.
- [ ] **CONT-001 — No-cache image build.** Build backend and dashboard images
  from the clean context, inspect their layers, users, entry points, health
  checks, labels, capabilities, and effective dependency versions.
- [ ] **CONT-002 — Core startup smoke.** Start the fixture external service,
  core API, dashboard, and telemetry profile from committed configuration.
  Wait for behavioral health, exercise authenticated and unauthenticated routes,
  and verify model discovery and streaming. Requirements: RUN-001, RUN-002,
  UI-001, SEC-001, TEL-001, TEL-004.
- [ ] **CONT-003 — Runtime hardening smoke.** Prove read-only roots, dropped
  capabilities, `no-new-privileges`, bounded tmpfs, non-root users, resource
  limits, restart behavior, and absence of the Docker socket.
- [ ] **NET-001 — Default exposure test.** From inside the VM, prove services
  work through loopback. From ubuntu-1, prove those ports are unreachable on the
  guest's libvirt address. Enumerate all listening sockets and container port
  publications. Requirements: SEC-007 and release criterion 6.
- [ ] **SEC-EARLY-001 — Early supply-chain gate.** Run dependency audits, secret
  scanning, static analysis, image vulnerability scanning, and license review
  before lifecycle or soak work. High or critical findings block progression.
- [ ] **CORE-001 — Wire complete read-only operations.** Before release
  validation, ensure the runtime agent, metrics, full doctor checks, dashboard
  evidence, and capability health are integrated rather than represented as
  unavailable placeholders. Requirements: RUN-003 through RUN-006, UI-001
  through UI-004.

P1 exit gate: one immutable candidate starts from a clean checkout in the VM,
passes the full non-live gate, exposes only loopback ports, and has no unresolved
high or critical early security finding.

## 6. P2 — Install, Upgrade, Recovery, Uninstall, and Integrity

- [ ] **LIFE-001 — Implement lifecycle commands.** Provide documented,
  idempotent install, validate, start, stop, backup, restore, upgrade, rollback,
  uninstall-preserve, and uninstall-purge operations. Every operation targets
  only labeled Morpheus resources and emits safe structured evidence.
- [ ] **LIFE-002 — Freeze a deployable upgrade baseline.** A genuine upgrade
  requires two deployable versions. Preserve the first accepted baseline
  artifacts, database schema, configuration schema, image digests, and fixture
  data before validating a later candidate.
- [ ] **LIFE-003 — Fresh installation.** Install the baseline and candidate
  independently on fresh VM clones, reboot each guest, and prove health,
  ownership labels, permissions, paths, volumes, and idempotent reinstall.
- [ ] **LIFE-004 — Backup and restore.** Seed representative Morpheus-owned core
  and optional state, create a backup, restore into a fresh clone, and compare
  logical state. Inject corrupt, partial, incompatible, path-escape, symlink,
  read-only-filesystem, and disk-full cases. Requirements: OPS-001, OPS-002,
  SEC-006.
- [ ] **LIFE-005 — Successful upgrade.** Upgrade the preserved baseline to the
  exact candidate, verify configuration and database migration, retained state,
  service health, image digests, and repeatability.
- [ ] **LIFE-006 — Interrupted upgrade and rollback.** Inject failure before and
  after each migration and replacement boundary. Roll back to exact baseline
  artifacts and compare logical state and health.
- [ ] **LIFE-007 — Uninstall preservation.** Repeated default uninstall removes
  only Morpheus runtime resources while preserving Morpheus data and every
  external fixture resource. Reinstall must recover preserved state.
- [ ] **LIFE-008 — Explicit purge.** With a named confirmation and lab-only
  authorization, purge only Morpheus-owned data. Forged labels and protected
  external names must still be rejected.
- [ ] **INTEG-001 — External integrity harness.** Capture stable identity,
  image/digest, command, network, mount identity, models contract, and health
  before and after every lifecycle operation. Prove the harness contains no
  secret values. Requirements: INV-001, INV-002, REL-003.

P2 exit gate: fresh install, upgrade, backup, restore, rollback, uninstall, and
purge pass repeatedly in VM clones; external fixture identity is unchanged; a
real older baseline exists for future upgrade tests.

## 7. P3 — Live Read-Only, Optional Services, and Browsers

### 7.1 ubuntu-1 Live Read-Only Lane

- [ ] **LIVE-001 — Implement hard live guards.** `tests/live` must require
  `MORPHEUS_LIVE_TESTS=1`, reject mutation by default, use allowlisted hosts and
  routes, set strict timeouts, and never fall back from fixtures implicitly.
- [ ] **LIVE-002 — Capture protected pre-state.** Record redacted external
  identity and health without retrieving environment values, private data, or
  Docker secrets. Environment: HOST-RO.
- [ ] **LIVE-003 — Validate vLLM discovery and health.** Confirm `/v1/models`,
  every alias/root/context field, behavioral health categories, and direct-path
  availability. No completion request is made. Requirements: RUN-001, RUN-002.
- [ ] **LIVE-004 — Validate version-tolerant metrics.** Parse the current metrics
  endpoint, report present and missing expected signals honestly, and retain no
  request content. Requirement: RUN-003.
- [ ] **LIVE-005 — Validate Open WebUI reachability and contract assumptions.**
  Use public/minimal routes only; do not change configuration, database, chats,
  files, or credentials.
- [ ] **LIVE-006 — Compare protected post-state.** External identity, images,
  commands, mounts, networks, model inventory, and health must match the
  pre-state exactly except for documented volatile counters.

Any completion, load, browser-login, chat, microphone, configuration, or restart
test is outside this lane and requires a separate authorization.

### 7.2 Optional-Service Compatibility in the VM

- [ ] **OPT-SEARCH-001 — SearXNG.** Pull the locked digest, start it CPU-only,
  execute a real lab query through the container network, verify safe results,
  timeouts/rate limits, failure isolation, backup, and removal. Requirements:
  SRCH-001 through SRCH-003.
- [ ] **OPT-VOICE-001 — Speech-to-text.** Transcribe versioned fixture audio,
  verify format/size rejection, CPU latency, temporary-file cleanup, no
  retention, restart, backup, and removal. Requirements: VOICE-001, VOICE-004.
- [ ] **OPT-VOICE-002 — Text-to-speech.** Generate and decode playable audio for
  each supported format, validate content types and limits, and prove CPU-only
  isolation. Requirements: VOICE-002, VOICE-004.
- [ ] **OPT-VOICE-003 — OpenAI/Open WebUI voice contracts.** Validate documented
  URLs, schemas, model/voice values, authentication, upload, playback, and safe
  errors against the fixture UI before any external Open WebUI test.
- [ ] **OPT-TEL-001 — Telemetry proxy.** Compare direct and proxied streaming,
  non-streaming, usage, error, cancellation, authentication, restart, retention,
  backup, bypass, and privacy behavior. Requirements: TEL-001 through TEL-005.
- [ ] **OPT-FLOW-001 — n8n.** Import only schema-validated credential-free
  templates, call the fixture model, back up/restore workflows, inject outages,
  and remove the service independently. Requirements: FLOW-001, FLOW-002.
- [ ] **OPT-RSCH-001 — Perplexica.** Run a cited research query through fixture
  search and model services, validate configured model compatibility, isolate
  failures, back up state, and remove independently. Requirements: RSCH-001,
  RSCH-002.
- [ ] **OPT-ISOLATION-001 — Cross-profile failure matrix.** Stop, corrupt,
  exhaust, restart, and remove each optional profile independently. Core API,
  dashboard, direct inference fixture, and unrelated optional state remain
  healthy. Requirement: REL-001.
- [ ] **OPT-RAG-001 — Apply the accepted decision.** Update RAG requirement
  status and evidence to deferred unless a measured unmet use case reopens the
  decision. Do not deploy unused vector or embedding services.
- [ ] **OPT-GPU-001 — Dedicated GPU lane, deferred to HOST-MAINT.** ComfyUI and
  inference-to-image transition tests cannot be represented by the CPU-only VM.
  They remain blocked until explicit maintenance authorization, complete
  recovery automation, and all pure/fake failure edges pass. Requirements:
  IMG-001 through IMG-004 and REL-003.

### 7.3 Browser, Accessibility, and Responsive Layout

- [ ] **BROW-001 — Pin the browser runner.** Add Playwright configuration,
  version-matched pinned browser image, deterministic web server lifecycle,
  trace/screenshot retention rules, and a serious/critical accessibility gate.
- [ ] **BROW-002 — Core desktop/mobile flows.** Cover login, logout, refresh,
  healthy, starting, degraded, unreachable, incompatible, disabled, blocked,
  empty, and stale evidence states at supported desktop and mobile viewports.
- [ ] **BROW-003 — Accessibility.** Verify keyboard-only operation, focus order,
  landmarks, headings, names, descriptions, contrast, reduced motion, status
  semantics, and automated scans with no serious or critical findings.
- [ ] **BROW-004 — Slow and partial failure.** Delay, fail, cancel, and reorder
  independent API calls. Prove the page remains usable, polling is consolidated
  and cancelable, and sign-out/session expiry are safe.
- [ ] **BROW-005 — Responsive visual evidence.** Capture reviewed screenshots at
  supported sizes and assert no overlap, clipped text, hidden focus, horizontal
  overflow, or color-only state.
- [ ] **BROW-006 — Browser security.** Test CSP, CORS, storage lifetime, bearer
  handling, CSRF non-applicability, framing, request IDs, and the absence of
  credentials from traces, screenshots, URLs, and console output.

P3 exit gate: guarded live read-only checks preserve ubuntu-1's external state;
every CPU optional profile passes in the VM; browser and accessibility gates are
green; GPU work remains explicitly blocked or separately approved.

## 8. P4 — Fault, Performance, Resource, and Soak Validation

- [ ] **FAULT-001 — Dependency fault matrix.** Cover DNS failure, refusal,
  timeout, malformed response, partial stream, clock skew, disk full, read-only
  storage, restart loops, corrupt state, and client cancellation. One failed
  probe cannot hide independent results.
- [ ] **LOAD-001 — Define reproducible workloads.** Version request mixes,
  concurrency, payload/token shapes, warm-up, duration, fixture behavior,
  hardware allocation, sampling, success thresholds, and abort limits.
- [ ] **LOAD-002 — Direct-path baseline.** In the VM, compare fixture inference
  directly with core Morpheus present but telemetry disabled. Requirement:
  PERF-001.
- [ ] **LOAD-003 — Telemetry overhead.** Compare direct and proxied traffic;
  median added TTFT must be under 25 ms and throughput loss under 2 percent for
  the declared representative workload. Requirement: PERF-001.
- [ ] **LOAD-004 — Backpressure and leak test.** Exercise slow consumers,
  disconnects, cancellation, timeouts, oversized frames, and bounded queues.
  Active tasks, sockets, and connections return to baseline.
- [ ] **PERF-UI-001 — Dashboard budget.** Measure largest-contentful render under
  two seconds locally, consolidated polling, cancellation, and backoff under
  slow/failing APIs. Requirement: PERF-003.
- [ ] **RES-001 — Resource budget.** Measure per-service CPU, RSS, file
  descriptors, connections, disk growth, and logs while idle and active. Core
  Morpheus services target less than 1 GiB idle memory. Requirement: PERF-002.
- [ ] **SOAK-001 — Short qualification soak.** Run two hours first; fail on
  unbounded growth, recurring errors, lost health, or unrecovered tasks.
- [ ] **SOAK-002 — Required 24-hour soak.** Run the exact candidate with declared
  periodic workload and faults for 24 hours. Preserve time-series summaries and
  start/end logical state, not private request bodies.
- [ ] **LIVE-PERF-001 — Representative external performance, separately
  authorized.** Any real completion or sustained load against ubuntu-1 vLLM is
  outside HOST-RO and requires explicit workload, limits, abort criteria, timing,
  pre-state, and post-state approval.

P4 exit gate: fault recovery is deterministic, budgets pass, and the 24-hour VM
soak shows no unbounded resource, task, connection, log, or database growth.

## 9. P5 — Supply Chain, Final Evidence, and Release Decision

- [ ] **SUPPLY-001 — Generate SBOMs.** Produce SPDX and CycloneDX documents for
  Python artifacts, dashboard dependencies, each application image, and the
  deployment bundle using the pinned tool.
- [ ] **SUPPLY-002 — Final vulnerability scan.** Scan locks, artifacts, filesystems,
  and OCI images. Record database version/time. No unresolved critical or high
  finding proceeds without a documented owner, control, and expiry.
- [ ] **SUPPLY-003 — License inventory.** Record direct/transitive application,
  frontend, image, and optional-service licenses and review compatibility with
  distribution intent.
- [ ] **SUPPLY-004 — Secret and content scan.** Scan Git history, checkout,
  artifacts, images, SBOMs, reports, screenshots, traces, logs, databases,
  backups, and support bundles for credentials and every canary class.
- [ ] **SUPPLY-005 — Immutable release manifest.** Record checksums, OCI digests,
  source commit, dependency locks, image locks, schema versions, SBOM digests,
  tool versions, and rollback artifacts.
- [ ] **SUPPLY-006 — Sign and verify.** Choose a documented signing mechanism and
  protected key location; sign the release manifest and validation report, then
  verify from a fresh VM clone. No signing key enters the repository or VM base.
- [ ] **DOC-001 — Complete operator runbooks.** Installation, configuration,
  startup, diagnostics, backup, restore, upgrade, rollback, uninstall,
  troubleshooting, security, recovery, and limitations must match tested
  behavior exactly.
- [ ] **DOC-002 — Independent walkthrough.** A person other than the primary
  implementation author follows the runbooks from a fresh VM clone and records
  deviations without undocumented assistance.
- [ ] **REL-REPORT-001 — Generate the final report.** Map each requirement to
  test evidence and artifacts; include failures, deferrals, limitations,
  environment, authorization, performance, soak, supply-chain, and integrity
  results.
- [ ] **REL-DECIDE-001 — Explicit release decision.** Stable approval occurs only
  when all release-level criteria pass or an allowed deferral is explicit and
  does not support a false readiness claim.

## 10. Recommended Execution Waves

1. **Lab wave:** LAB-001 through ART-001.
2. **Core wave:** CLEAN-001 through CORE-001 and early security.
3. **Lifecycle wave:** LIFE-001 through INTEG-001.
4. **Compatibility wave:** LIVE, CPU optional-service, and browser tasks.
5. **Qualification wave:** fault, load, resource, and soak tasks.
6. **Release wave:** final supply chain, runbooks, report, and decision.

Do not schedule the 24-hour soak until the candidate artifact set is frozen and
all shorter lanes are green. Do not schedule host GPU work merely because the VM
lanes pass. Do not call an upgrade validated until two real deployable versions
and exact rollback artifacts exist.
