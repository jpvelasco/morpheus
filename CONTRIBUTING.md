# Contributing to Morpheus

## Development Contract

Morpheus is built with test-driven development. Every behavior change begins
with a failing test that describes the externally observable requirement.
Production code is then written to make that test pass, followed by refactoring
under a green suite.

Do not merge skipped tests, placeholder assertions, disabled quality gates, or
tests that only restate implementation details.

The active source work order is `docs/RECTIFICATION_PLAN.md`. During
rectification, `implemented` is reserved for complete behavior at the stable
product boundary; a component parser, fake executor, route shape, or UI state is
not enough. Shared identity and plan contracts land before parallel consumers.

## Change Process

1. Reference a requirement ID from `docs/PRODUCT_SPECIFICATION.md`.
2. Add or update the acceptance or contract test.
3. Confirm that the new test fails for the expected reason.
4. Add the smallest coherent implementation that satisfies the requirement.
5. Refactor while keeping the full relevant suite green.
6. Run static analysis, security checks, and the appropriate integration lane.
7. Update documentation and an ADR when contracts or architecture change.
8. Update `requirements.json`, `docs/IMPLEMENTATION_GAP_REVIEW.md`, and
   `docs/RELEASE_STATE.md` together when status changes.

## Required Standards

- Python code is typed and passes strict static analysis.
- TypeScript code uses strict mode and contains no unchecked `any` at external
  boundaries.
- Domain code performs no direct filesystem, network, subprocess, Docker, or
  database access.
- External data is validated at the boundary.
- Errors are structured, actionable, and safe to display.
- Logs contain request IDs but exclude secrets, prompts, responses, and raw
  environment values by default.
- Persistent formats are versioned and migrated transactionally.
- Container images used in release manifests are pinned by digest.

## External Harness Evidence

Changes involving Tonos or another developer-harness qualification producer
must follow ADR-0010. Keep producer-specific DTOs at the import boundary, map
them into the canonical Morpheus evidence family, and use static sanitized
golden fixtures rather than a source/package/runtime dependency. An optional
external correlation value is untrusted search metadata and must never enter
authorization, ownership, or canonical identity decisions.

## Safety Boundary

Normal tests must not call or mutate the production `coder-model` or
`open-webui` services. Live tests are opt-in, clearly labeled, read-only by
default, and require an explicit environment guard before any stateful action.

Morpheus lifecycle commands may operate only on resources bearing the
Morpheus project label. They must reject external containers, volumes, and
networks even when a caller supplies their names.

## Definition of Done

A change is done only when its requirement-level tests pass, affected contracts
remain compatible, documentation is current, rollback behavior is defined, and
no new warning is introduced in lint, type, test, security, or build output.
