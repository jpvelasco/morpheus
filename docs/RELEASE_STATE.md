# Morpheus Release State

This is the durable resume ledger for the current release effort. Update it at
the start and end of each material milestone, and commit it with the related
source change or evidence-plan update. It contains no secrets, credentials,
private request data, host addresses, or unredacted evidence.

## Current Position

- **Validated baseline candidate:** `ae3a98d74b055672c37ae608805e21804d4e609b`
  (`security: bound API request work`). Its build evidence remains valid only
  for that source revision.
- **Current release development line:** post-baseline source changes will be
  frozen into a new candidate only after the pre-soak implementation queue is
  complete.
- **Implementation inventory:** 37 implemented, 18 planned, 3 deferred; see
  [`requirements.json`](../requirements.json) and the
  [implementation gap review](IMPLEMENTATION_GAP_REVIEW.md).
- **Release posture:** not yet release-ready. A passing candidate does not
  replace lifecycle, browser, load, fault, supply-chain, or soak evidence.
- **GPU posture:** GPU/image-generation work is deliberately excluded from the
  pre-soak core-release lane. It requires a later, separately authorized
  host-maintenance release candidate.

## Completed Current-Candidate Evidence

| Milestone | Result | Notes |
|---|---|---|
| Python quality gate | Pass | 311 tests, 90.28% coverage; format, lint, type checking, Bandit, and offline package build passed. |
| Dashboard quality gate | Pass | Pinned offline Node image: formatting, type check, 31 tests, and production build passed. |
| Reproducible candidate build | Pass | Two independent disposable VM builds used blocked outbound networking and produced five byte-identical artifacts: Python sdist/wheel, agent bundle, backend OCI image, and dashboard OCI image. |

Release evidence is intentionally ignored from Git. Store it only under the
configured `artifacts/release-validation/` location or a disposable validation
workspace; refer to the candidate commit and task ID in its redacted manifest.

## Last Completed Source Milestones

| Commit | Milestone |
|---|---|
| `ae3a98d` | Request body limits, content/schema checks, timeouts, rate limits, and bounded concurrency across exposed APIs. |
| `ffe5f0d` | Signed browser-session decision record and validation-plan correction. |
| `4d20d86` | Browser API-key removal; signed, expiring cookie sessions with CSRF-protected logout. |
| Current development line | RUN-005 now derives optional-capability state from live, Morpheus-owned runtime-agent container health evidence. |

## Active Milestone

**IMP-SEC-002-01 — action-aware authorization.** Add authorization that joins
the requested resource type, Morpheus ownership label, protected identity, and
an explicit operation allowlist.

## Pre-Soak Queue

1. Remaining P0 implementation: SEC-002, SEC-005, SEC-006, REL-002, OPS-002,
   and REL-003.
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
