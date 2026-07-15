## Requirement

<!-- List PRODUCT_SPECIFICATION.md requirement IDs and linked issue/decision. -->

## Change

<!-- State the user-visible behavior and the ownership boundary affected. -->

## TDD Evidence

<!-- Identify the test that failed first and why it failed. -->

- Failing test before implementation:
- Unit tests:
- Contract tests:
- Integration or acceptance tests:
- Live or hardware lane, when required:

## Safety

- [ ] External inference and Open WebUI resources are not mutated.
- [ ] Morpheus resource ownership is enforced.
- [ ] No secret, prompt, response, document, audio, or generated runtime data is committed.
- [ ] Network exposure remains loopback or internal by default.
- [ ] Rollback behavior is documented and tested for stateful changes.

## Validation

<!-- Include exact commands and outcomes. Explain every skipped lane. -->

## Documentation and Decisions

- [ ] User/operator documentation is current.
- [ ] Public contracts and migrations are documented.
- [ ] An ADR was added or superseded when an architecture decision changed.
