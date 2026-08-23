# Optional Tonos Interoperability

Status: Accepted boundary; deferred implementation outside active rectification

Date: 2026-08-22

Normative decision: [ADR-0010](adr/0010-optional-external-harness-qualification-evidence.md)

## Specialization

Morpheus and Tonos address adjacent but different optimization problems:

| Concern | Morpheus | Tonos |
|---|---|---|
| Subject | inference deployment | developer-facing harness experience |
| Primary tuple | machine + model + quantization + engine + settings | harness + client config + provider/model observation + task suite |
| Owns | deployment plans, server lifecycle, server metrics, recommendation | isolated harness trials, task/evaluator evidence, client timing |
| Does not own | external developer-harness configuration or orchestration | provider engine, model files, GPU/service lifecycle, promotion |
| Standalone gate | canonical direct benchmark suite | provider-neutral fixture and real harness/provider adapters |

Morpheus finds and tunes a deployment that fits hardware and workload policy.
Tonos tests what a developer harness actually does when pointed at a served
endpoint. Either can be used without the other.

## Valid Topologies

```text
Morpheus -> Morpheus canonical direct benchmarks
Tonos -> LM Studio or another provider, without Morpheus
Tonos client host -> Morpheus-managed endpoint on inference host
Tonos and Morpheus on one host with separate processes and ownership
```

Morpheus remains a single-appliance control plane and normally runs beside the
deployment it manages. This document does not authorize management of a remote
fleet or an externally owned inference engine.

## Measurement Boundary

Morpheus records server-side deployment identity, queueing, TTFT, decode,
cache/resource behavior, process health, failures, and lifecycle transitions.
Tonos records harness setup, end-to-end wall time, client-visible events, tool
behavior, repository edits, verification, recovery, and task correctness.

Neither source overwrites the other. Provider-reported metrics in a Tonos result
remain attributed provider observations until Morpheus maps and validates them.
Clock skew, buffering, transport, retries, and harness preprocessing are
explicit limitations when comparing the two timelines.

## Optional Correlation Value

If an operator wants to inspect the two evidence streams together, both may
record the same opaque correlation value. The value is:

- optional and disabled by default;
- bounded, non-secret, and treated as untrusted input;
- supplied/generated outside either required workflow;
- search metadata only;
- never an API key, session, request, user, machine, model, deployment-plan,
  operation, campaign, or ownership identity;
- never proof that records cover the same interval or share a clock;
- never required for a trial, campaign, recommendation, promotion, or release.

No carrier is fixed yet. A later implementation must version and test any
header/metadata mapping, refuse prompt injection as a carrier, and preserve
normal behavior when an endpoint cannot propagate the value.

## Optional Evidence Import

The preferred boundary is a sanitized immutable bundle created by the harness
lab and explicitly imported by the operator. It is not a runtime dependency or
automatic callback. A bundle may provide:

- producer/schema/export-redactor versions and source digest;
- harness identity and effective configuration;
- provider profile and served-model observation;
- task suite, fixture, and evaluator identities;
- terminal state, sample counts, dispersion, client timing, objective outcomes,
  limitations, and redaction report;
- optional external deployment/evidence references and correlation metadata.

Morpheus must reject secret values, raw prompts/responses/reasoning, unrestricted
tool arguments, repository content, engine-control instructions, path escapes,
unknown future schemas, and oversized inputs. Imported source bytes are retained
only if they satisfy Morpheus content-minimization policy; otherwise Morpheus
retains a digest, sanitized mapping, and explicit omission record.

Mapping happens only after rectification R1 has fixed canonical identity types.
R2 may then consume mapped task outcomes as attributed evidence for workload
metrics such as coding correctness, tool use, and agentic behavior. Machine,
model, engine, deployment, suite, freshness, and comparability checks still
govern recommendation eligibility.

## Deferred Implementation Handoff

Agents may begin this optional lane only after:

1. Morpheus R1 and R2 are green;
2. the producer independently passes its standalone harness/provider/evidence
   gates;
3. both repositories have static sanitized golden bundles and schema fixtures;
4. an explicit implementation request authorizes the work.

The first tests must prove independence: Morpheus runs with no Tonos checkout or
service, the producer runs with no Morpheus checkout or service, missing
correlation values are harmless, and parsing a bundle cannot execute or mutate
anything. A shared runtime library, direct control API, automatic orchestration,
or fleet controller requires a new ADR.
