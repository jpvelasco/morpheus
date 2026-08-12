# ADR-0006: Evidence-Ranked Model and Engine Selection

Status: Accepted

Date: 2026-08-11

## Context

The “best” local model depends on hardware, quantization, engine support,
context, concurrency, workload, software versions, and operator priorities.
Parameter count, model popularity, a single tokens-per-second number, or an
unversioned compatibility list cannot select a serious developer inference
stack safely.

Morpheus already has typed health and telemetry foundations, and the separate
`history-tool-tests` directory contains useful historical coding, tool-use,
speed, and long-context results. Those results are valuable evidence but do not
yet share a complete machine/model/engine/configuration provenance schema.

## Decision

Selection is a deterministic two-stage process:

1. Apply hard compatibility, capacity, license, trust, required-feature, and
   safety constraints to model, quantization, engine, and configuration tuples.
2. Rank only viable tuples using a versioned developer workload profile and
   evidence whose provenance and comparability are explicit.

Every recommendation includes the machine profile, catalog versions, workload
weights, estimates, measurements, confidence, stale or missing evidence,
tradeoffs, and exclusion reasons. Catalog changes never alter historical
recommendations or installed manifests retroactively.

Benchmark campaigns store immutable raw observations and normalized summaries.
Comparisons classify results as directly comparable, normalized/estimated, or
invalid. Imported history history retains its original files and limitations.
Measured target-host results may calibrate future estimates only after their
configuration and benchmark provenance pass validation.

Recommendation is advisory. Download, install, benchmark, promotion, rollback,
and removal remain separate authenticated plans requiring policy and operator
approval.

## Consequences

- The product can explain why a smaller or differently quantized model is a
  better fit for a particular developer workload.
- Recommendation logic remains testable without downloading models or using a
  live GPU.
- Catalog maintenance and evidence freshness become explicit operational work.
- Benchmark schemas must capture more provenance than the current JSONL rows.
- UI scorecards must show uncertainty and comparability, not just leaderboard
  ordering.
- An AI diagnostic provider cannot override deterministic selection or lifecycle
  policy.

## Alternatives Considered

### Choose the largest model predicted to fit VRAM

Rejected because it ignores engine compatibility, context KV-cache cost,
quality, latency, concurrency, stability, storage, and workload fit.

### Rank only by public leaderboards

Rejected because public scores do not establish compatibility or performance on
the target machine and often omit the exact quantization and engine path.

### Let an LLM choose and install the stack directly

Rejected because model output is not an ownership, compatibility, safety, or
authorization boundary.
