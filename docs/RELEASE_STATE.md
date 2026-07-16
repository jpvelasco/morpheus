# Morpheus Release State

This is the durable resume ledger for the current release effort. Update it at
the start and end of each material milestone, and commit it with the related
source change or evidence-plan update. It contains no secrets, credentials,
private request data, host addresses, or unredacted evidence.

## Current Position

- **Validated baseline candidate:** `ae3a98d74b055672c37ae608805e21804d4e609b`
  (`security: bound API request work`). Its build evidence remains valid only
  for that source revision.
- **Current handoff commit:** `e0cd976f6bf8479ab60de9a8b798daa03b86847b`
  (`feat: harden restore preflight and rollback`; 2026-07-15). The worktree
  was clean when this ledger was refreshed.
- **Current release development line:** post-baseline source changes will be
  frozen into a new candidate only after the pre-soak implementation queue is
  complete.
- **Implementation inventory:** 41 implemented, 14 planned, 3 deferred; see
  [`requirements.json`](../requirements.json) and the
  [implementation gap review](IMPLEMENTATION_GAP_REVIEW.md).
- **Release posture:** not yet release-ready. A passing candidate does not
  replace lifecycle, browser, load, fault, supply-chain, or soak evidence.
- **GPU posture:** GPU/image-generation work is deliberately excluded from the
  pre-soak core-release lane. It requires a later, separately authorized
  host-maintenance release candidate.

## Handoff and Resume

An agent starting from the repository should read this file first, then
[`IMPLEMENTATION_GAP_REVIEW.md`](IMPLEMENTATION_GAP_REVIEW.md),
[`requirements.json`](../requirements.json), and
[`validation/README.md`](../validation/README.md). Those files define the
remaining requirements, priority, environment boundaries, evidence policy,
and next task; no chat transcript is required to select the next source task.

The next source task is **IMP-SEC-005-01**. Implement the documented pinned
tooling so every release artifact and OCI image gets an SBOM and the lock,
secret, static, dependency, filesystem, and container scans are release
blocking. Keep evidence redacted and ignored; do not put credentials, host
addresses, or request data in Git.

After SEC-005, implement **IMP-REL-003-01** as described in the P0 table in
the gap review. Then create a new candidate from the exact resulting commit;
the older baseline evidence must not be relabelled as evidence for that new
candidate.

Normal validation must never restart, reconfigure, or otherwise mutate the
external inference or Open WebUI services. Use disposable stacks/VMs for all
mutating tests. Do not enable persistent user-service linger. GPU allocation,
voice-GPU, and image-generation work are excluded until separately authorized
host-maintenance work begins.

## Completed Current-Candidate Evidence

| Milestone | Result | Notes |
|---|---|---|
| Python quality gate | Pass | 311 tests, 90.28% coverage; format, lint, type checking, Bandit, and offline package build passed. |
| Dashboard quality gate | Pass | Pinned offline Node image: formatting, type check, 31 tests, and production build passed. |
| Reproducible candidate build | Pass | Two independent disposable VM builds used blocked outbound networking and produced five byte-identical artifacts: Python sdist/wheel, agent bundle, backend OCI image, and dashboard OCI image. |

## Current-Line Checkpoint (Not a Frozen Release Candidate)

At handoff commit `e0cd976`, the Python quality gate passed with 345 tests and
90.52% coverage; formatting, lint, type checking, Bandit, pip-audit, and the
offline package build also passed. This confirms source health at that point,
but it is not release evidence: SEC-005 and REL-003 remain, no candidate has
been frozen, and all candidate-specific startup/lifecycle/browser/load/soak
evidence must be produced again after the freeze.

Release evidence is intentionally ignored from Git. Store it only under the
configured `artifacts/release-validation/` location or a disposable validation
workspace; refer to the candidate commit and task ID in its redacted manifest.

## Last Completed Source Milestones

| Commit | Milestone |
|---|---|
| `ae3a98d` | Request body limits, content/schema checks, timeouts, rate limits, and bounded concurrency across exposed APIs. |
| `ffe5f0d` | Signed browser-session decision record and validation-plan correction. |
| `4d20d86` | Browser API-key removal; signed, expiring cookie sessions with CSRF-protected logout. |
| `ed29681` | RUN-005 now derives optional-capability state from live, Morpheus-owned runtime-agent container health evidence. |
| `ff02687` | SEC-002 now authorizes only explicit read-only resource actions on owned, non-protected identities. |
| `a740dee` | SEC-006 now resolves configured data, persistence, archives, generated output, evidence, and restore staging through owned-path boundaries. |
| `4c6342c` | REL-002 now applies bounded retry/backoff/deadline recovery to idempotent inference discovery. |
| `e0cd976` | OPS-002 now preflights schema/free space and performs durable rollback-capable restore swaps. |

## Active Milestone

**IMP-SEC-005-01 — supply chain.** Generate SBOMs for every artifact/image and
make lock, secret, static, dependency, filesystem, and container vulnerability
scans release-blocking.

## Pre-Soak Queue

1. Remaining P0 implementation: SEC-005 and REL-003.
2. Rebuild and validate the exact frozen candidate: current-container startup,
   hardening, loopback exposure, security/SBOM evidence, installation, runtime
   agent, and external-runtime integrity.
3. Lifecycle, browser/accessibility, optional CPU-service, fault, load, and
   resource validation.
4. Two-hour qualification soak; freeze the release candidate; then run the
   required 24-hour soak.

Do not add source changes after the candidate is frozen for soak. Any such
change creates a new candidate and requires affected validation to be repeated.

## Operating Constraints

- Never restart, reconfigure, or mutate external inference/Open WebUI services
  during normal validation.
- Use only disposable candidate stacks and validation VMs for mutation.
- Do not enable persistent user-service linger as a workaround for agent tests.
- Keep GPU allocation and image-generation transitions out of the core-release
  lane until explicit host-maintenance authorization is granted.
