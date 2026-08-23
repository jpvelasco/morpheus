# ADR-0010: Optional External Harness Qualification Evidence

Status: Accepted

Date: 2026-08-22

## Context

Morpheus selects and operates model, quantization, engine, configuration, and
hardware tuples. Its canonical benchmark suite must independently cover direct
API behavior, performance, resources, and bounded developer-quality canaries.

A separate project such as Tonos may evaluate a different layer: how a
developer-facing harness such as Codex, Grok CLI, Zero, or OpenClaude behaves
against a served endpoint. That evidence includes harness setup and orchestration
time, tool use, repository edits, verification, recovery, and end-to-end task
correctness. It can complement server-side evidence, but it is not inference
lifecycle authority and need not be available for Morpheus to work.

Direct source/runtime coupling would make Morpheus depend on external harness
release cycles and could turn a useful qualification lab into an implicit
control path. Having Morpheus remotely manage inference hosts would also expand
the accepted single-appliance architecture into a fleet controller.

## Decision

Morpheus and external harness qualification tools remain independent.

- Morpheus owns canonical machine, model, engine, deployment-plan, campaign,
  server-observation, recommendation, and lifecycle records.
- An external harness lab owns harness/configuration/task/evaluator identities
  and client-observed trial results.
- Morpheus retains a small canonical direct benchmark suite and never requires
  an external harness lab for selection, operation, qualification, or release.
- Morpheus does not import, vendor, symlink, package, start, configure, or call a
  Tonos checkout or service.
- Optional interoperability uses a sanitized immutable evidence bundle and
  static golden contract fixtures, not a shared runtime library or control API.
- Imported harness evidence is attributed to its producer and classified as
  measured, foreign-machine, stale, partial, estimated, or incomparable before
  it can influence a recommendation. Parsing alone never grants eligibility.

An operator may attach an opaque optional correlation value to independently
collected client and server evidence. The value is bounded, non-secret,
untrusted metadata. It is not authentication, authorization, identity,
ownership proof, request equivalence, or evidence of clock synchronization.
Absence has no effect on either product. A carrier/version requires a later
implementation decision; correlation metadata must never be inserted into model
prompts merely to propagate it.

Morpheus normally runs on the machine whose deployment it manages. A harness
lab may run on the same machine or connect over a local/LAN/remote provider
endpoint. This relationship does not add remote fleet management.

Implementation is deferred until rectification R1 freezes canonical identities,
R2 composes retained benchmark evidence into recommendations, and the external
producer has a stable standalone sanitized export contract.

## Consequences

- Morpheus remains independently useful and testable.
- Rich real-harness correctness/tool/agentic outcomes can later augment, but not
  replace, direct server measurements and Morpheus policy.
- Client wall time and server timing remain separate observations, making
  harness overhead, transport, queueing, and clock limitations visible.
- Cross-project evolution is constrained to versioned exchange semantics and
  golden fixtures.
- A new deployment configuration requires a new Morpheus plan/evidence identity;
  old harness outcomes cannot silently transfer to it.
- Automatic cross-project orchestration, shared libraries, and fleet control
  require a new ADR and are not implied by this decision.

## Alternatives Considered

### Merge harness qualification into Morpheus

Rejected because harness configuration, repository-task execution, and harness
release compatibility are a distinct product concern and would broaden the
focused inference appliance.

### Make Tonos the Morpheus benchmark runner

Rejected because Morpheus must remain operational and independently
qualifiable without another repository or service.

### Let Tonos tune and control inference engines

Rejected because it confuses client qualification with deployment ownership and
duplicates Morpheus lifecycle, safety, and hardware-optimization responsibilities.

### Add a shared runtime package now

Rejected because a static versioned evidence contract is sufficient and creates
less release, language, and availability coupling.
