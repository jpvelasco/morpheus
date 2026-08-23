# AGENTS.md

## Where We Left Off (2026-08-22)

The GitHub implementation run is complete at source
`9b4cda09d4b064f160902b9dd25387cf3129cdb3`, but the v0.2 product is **not**
source-complete or release-ready. A post-run audit reproduced the integration,
identity, observability, process-supervision, traceability, and documentation
findings recorded on 2026-08-15 and found additional scope, desktop, diagnosis,
and target-support overclaims.

The active source milestone is the
[`v0.2 architecture rectification plan`](docs/RECTIFICATION_PLAN.md). Its work
packages R0 through R9 must realign the implementation before Phase 18 physical
qualification. The first implementation package is R0, followed by the
dependency-critical R1 canonical identity and deployment-plan consolidation.
Do not resume the old Phase 11-to-18 implementation prompt or jump directly to
physical qualification.

`requirements.json` is reconciled to 59 implemented, 26 planned, 12 deferred,
and 0 validated requirements. Component scaffolds and their tests remain useful,
but they do not establish complete product behavior. In particular:

- managed operation routes still use a deliberately non-mutating DEV executor;
- recommendation bypasses retained catalogs and benchmark evidence;
- duplicate semantic plan/identity families prevent one end-to-end identity chain;
- metrics are collected on page requests and events have no production producers;
- native engine shutdown bypasses process-tree supervision;
- desktop/native package and local diagnosis paths remain incomplete;
- optional search/voice/research/RAG/image requirements remain deferred.

Read these files in order before rectification work:

1. `docs/RELEASE_STATE.md` — authoritative current state and handoff;
2. `docs/RECTIFICATION_PLAN.md` — active execution order and gates;
3. `requirements.json` — current functional status and task IDs;
4. `docs/PRODUCT_SPECIFICATION.md` and `docs/ARCHITECTURE.md` — accepted intent;
5. `docs/IMPLEMENTATION_PLAN.md` — original phase dependencies and exit criteria;
6. `docs/IMPLEMENTATION_AUDIT_2026-08-15.md` — historical finding detail.

The deployed v0.1 Morpheus remains a **read-only operator surface** next to the
existing inference stack. It answers whether inference is up, which model is
served, GPU/disk state through the agent, and basic diagnostics. It is not chat,
model management, or vLLM control. Source plans and scaffolds must not be
presented as deployed behavior.

### Continuation and Authorization

The user's authorization to prepare this rectification plan does not authorize
implementation, live-host operations, external-service/cache mutation, release
publication, or signing-credential access. When implementation is explicitly
authorized, agents may continue across green DEV and disposable-lab packages in
the dependency order defined by `RECTIFICATION_PLAN.md` without asking at every
package boundary. HOST-RO and HOST-MAINT lanes always require explicit current
authorization.

Windows public signing and Apple signing/notarization remain optional final
distribution-hardening lanes. Missing credentials must not delay source,
packaging, DEV/VM, or physical product work. Unsigned development artifacts stay
checksummed and explicitly confirmed, and unattended update remains disabled.

The repository declares `Proprietary - no license granted`. Public visibility
does not grant an open-source license. Do not change licensing metadata, add a
license, or claim Morpheus is open source until the user explicitly chooses the
license and publication policy.

### Live Install (ubuntu-1)

| Item | Value |
|---|---|
| Runtime root | `/home/operator/morpheus-runtime` |
| Dashboard | `http://127.0.0.1:7401/` (loopback only; use SSH tunnel off-box) |
| API | `http://127.0.0.1:7400/` |
| Env / API key | `/home/operator/morpheus-runtime/morpheus.env` (mode `0600`) |
| Host agent | `/home/operator/morpheus-runtime/agent/current`, socket under `run/` |
| Install path | `deploy/ubuntu-1/install.sh` and `docs/runbooks/UBUNTU_OPERATOR.md` |
| Candidate | rewritten source `fa5fe3ca2e393d6d20c1afa89dff2452650bf180`; deployed artifacts retain legacy build ID `aa7174aff3194ffeb1ca455d53005f242abe6d82` |

The agent socket directory must be mode `0750` so the API container can reach
`agent.sock`. If GPU or storage appears unavailable, verify the directory mode
and confirm the agent PID is alive.

Daily CLI after sourcing the environment or using the agent venv:

```bash
/home/operator/morpheus-runtime/agent/current/bin/morpheus status
/home/operator/morpheus-runtime/agent/current/bin/morpheus models
/home/operator/morpheus-runtime/agent/current/bin/morpheus doctor
```

## Project Boundary

Morpheus is an independent project. Do not import, vendor, symlink, or depend on
ODS source code. ODS may be consulted for ideas and upstream project names, but
Morpheus implementations and contracts must be written for this system.

The active `coder-model` vLLM service, existing Open WebUI container, their
Compose project, model caches, and persistent data are externally owned. Never
restart, recreate, stop, reconfigure, or write to them unless the user gives an
explicit state-changing instruction in the current request.

In v0.2 terms, that stack is `external_observed`. Future managed inference must
use separate Morpheus-owned roots, labels, manifests, and endpoints. Do not
adopt the existing stack merely because it is discoverable or appears in a
recommendation.

## Engineering Rules

- Follow `docs/PRODUCT_SPECIFICATION.md`, `docs/ARCHITECTURE.md`,
  `docs/IMPLEMENTATION_PLAN.md`, and the active `docs/RECTIFICATION_PLAN.md`.
- Prefer `docs/runbooks/UBUNTU_OPERATOR.md` for host operator install/use.
- Use TDD: failing requirement test, minimal implementation, refactor.
- Keep core domain logic pure and dependency-free.
- Put external behavior behind typed adapter protocols.
- Use structured parsers for JSON, YAML, metrics, and Compose data.
- Do not expose secrets or retrieve secret values for diagnostics.
- Do not weaken tests, security controls, status semantics, or type checks to
  make a build pass.
- Do not add a competing identity, plan, lifecycle, or evidence representation;
  map boundary DTOs explicitly to the canonical domain family.
- Add concise comments only for non-obvious decisions.
- Keep generated output under ignored `artifacts/`.

## Validation

Run the smallest relevant test lane while iterating, then the complete required
gate for the affected rectification package. Acceptance tests must exercise the
real public/application composition boundary; component test volume does not
substitute for specified behavior.

Live-system tests are opt-in and read-only unless the user explicitly authorizes
mutation. Do not pull formal release checklist items such as the 24-hour soak,
full browser matrix, multi-host rebuilds, optional sidecars, public signing, or
notarization ahead of their declared gate.
