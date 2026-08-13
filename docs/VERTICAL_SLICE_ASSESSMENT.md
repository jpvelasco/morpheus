# Vertical Slice Assessment — VSLICE-001 (Phase 11.5)

- Date: 2026-08-13
- Branch: `agent/phase-11-5-walking-skeleton`
- Host: Batmobile — Windows 11 Pro, Docker Desktop 29.6.2, AMD Ryzen 7 2700X, CPU-only (GPU explicitly out of scope for 11.5)
- Driver: `validation/vslice/run_real_slice.py` (`uv run --python 3.12 python -m validation.vslice.run_real_slice [--fresh]`)
- Harness: `validation/vslice/harness.py` (pure domain) + `validation/vslice/docker_environment.py` (Docker adapter)

## Result

**Decision: GO.** The disposable real slice completed a full acquire → campaign → promote A →
campaign → promote B → rollback → restore cycle end-to-end with clean state before/after,
twice (fresh run and checkpoint-resume run). No blockers for Phase 12 implementation.

| Run | acquisition_a | campaign_a | promotion_a | campaign_b | promotion_b | rollback | health_after | orphans | external |
|---|---|---|---|---|---|---|---|---|---|
| fresh (`--fresh`) | staged | succeeded | active | succeeded | active | completed | True | 0 | unchanged |
| resume (no flag) | staged (resumed) | succeeded (resumed) | active (resumed) | succeeded (resumed) | active (resumed) | completed (resumed) | True | 0 | unchanged |

The resume run re-enters the flow from durable checkpoints, skips re-download and
re-benchmark, and reproduces the same terminal records without side effects.

## Measurements (fresh run, plan A)

- Model: SmolLM2-135M-Instruct, Q4_K_M, GGUF (Apache-2.0)
- Engine: llama-server b10400 (Ubuntu x64 CPU build), threads=2, ctx 2048, batch default
- Prompt: "Explain TCP in one sentence." (max_tokens 24)
- **TTFT: 0.797 s**
- **Throughput: 20.08 tokens/s**

CPU-only performance is well within the walking-skeleton gate (limits were 120 s / 1000 tps).

## Artifact identities

| Artifact | Source / pin | Digest (SHA-256) |
|---|---|---|
| Model GGUF | `bartowski/SmolLM2-135M-Instruct-GGUF` commit `f0a2b81d63eb57be0e90e82e327e03a7fc66a7dc`, file `SmolLM2-135M-Instruct-Q4_K_M.gguf` | `2e8040ceae7815abe0dcb3540b9995eaa1fa0d2ca9e797d0a635ae4433c68c2d` |
| Engine | llama.cpp release `b10400`, `llama-b10400-bin-ubuntu-x64.tar.gz` | `ce3aadaadcc443f46d0d9eaa5c688d4370e25b90bd7e6e903cabcaa72dd2a584` |
| Runtime image | `morpheus/vslice-runtime@sha256:64a2f90ec51d971f13b1fdb0f735e18bc78c4b40cfe17b404041224e33a101b8` (built from `validation/vslice/runtime.Dockerfile`) | image ID `sha256:64a2f90e...` |
| Base image | `ubuntu:24.04` | `sha256:561618e2c15bf2397621dd04f96926663a3b5616c189cf7e38db7e82f5c538ea` |

Engine digest is recorded in `artifacts/vslice-cache/artifacts.json` (gitignored) and
re-verified on every run; the model digest is a compile-time pin in
`validation/vslice/docker_environment.py`. The runtime image is the pinned Ubuntu base
plus `libgomp1` only.

## Reproducibility

- All artifacts are pinned by URL + digest; downloads land only under the gitignored
  `artifacts/vslice-cache/` and are reused on subsequent runs (verified: resume run did
  not re-download).
- One command reproduces the slice: `uv run --python 3.12 python -m validation.vslice.run_real_slice --fresh`.
- The runtime image rebuild is deterministic from the committed Dockerfile against the
  digest-pinned base (apt adds only `libgomp1`, which is required by the release binaries).
- The offline acceptance lane (`tests/acceptance/test_vslice_walking_skeleton.py`, 14
  tests) exercises the identical harness against `FakeVSliceEnvironment` with zero Docker
  involvement, so CI never needs a daemon.

## Contract findings

1. **Config rendering must emit engine-native flags.** The first pass rendered
   `--context_length`; llama.cpp accepts `--ctx-size`. `render_command` now maps the
   bounded setting names (`context_length`, `threads`, `batch_size`) to
   `--ctx-size` / `--threads` / `--batch-size` and still rejects any unknown setting at
   plan construction.
2. **Machine-state chains held exactly.** Every transition used the Phase 11 state
   machines; terminal states blocked all further transitions; checkpoints are canonical
   JSON that round-trip exactly (codec tamper tests added).
3. **Ports and exposure.** The container binds `0.0.0.0` internally, but the only host
   exposure is `-p 127.0.0.1:<port>:<port>` with `--cap-drop ALL`, `--read-only`,
   `no-new-privileges`, and a bounded `/tmp` tmpfs; the ready probe, chat, and metrics
   all stay on host loopback. External-state snapshots (`docker ps -aq` hash) matched
   before and after both runs.

## Failures and recovery friction

1. **Engine bundle layout assumption.** The b10400 release ships a small `llama-server`
   launcher plus sibling shared libraries under `llama-b10400/`, not `build/bin/`.
   Recovery: extract the whole bundle; the environment mounts it read-only at
   `/opt/morpheus-cache/engine/llama-b10400/`.
2. **Executable path inside the container.** Docker rejects bare `llama-server` as argv[0]
   ("executable file not found in $PATH"); the environment rewrites argv[0] to the
   absolute mounted path.
3. **Missing runtime library.** `libgomp.so.1` is absent from stock `ubuntu:24.04`.
   Recovery: committed `runtime.Dockerfile` (base + `libgomp1`), image pinned by digest.
4. **Container loopback binding.** llama-server bound to `127.0.0.1` inside the container
   is unreachable through Docker's port publish (DNAT targets the container IP).
   Recovery: bind `0.0.0.0` inside the disposable container; the host boundary remains
   loopback-only.
5. **Stale checkpoints poisoned reruns.** Failed attempts left terminal
   (`aborted`/`rejected`) checkpoints that short-circuit later runs. Recovery: `--fresh`
   clears the checkpoint dir; the fixture lane covers resume semantics separately.
6. **Docker Desktop removal of a "Created" container** occasionally needs a retry;
   `stop_server` now retries `docker rm -f` and verifies absence.
7. **No bash required anywhere.** Everything (download, verify, extract, run, health,
   chat, cleanup) is native Python + the Docker CLI on the Windows host; WSL was never
   used.

## Proposed changes (small, non-blocking)

1. Keep `--fresh` as the documented first-run/reset path; add a `--reset-checkpoints`
   alias in the driver help if the driver grows a CLI surface.
2. Consider making the model/engine mount layout a plan-owned concern later (a
   `cache_layout` field) instead of the current hardcoded `/opt/morpheus-cache`; no change
   needed now — the walking skeleton deliberately keeps it fixed.
3. Record the runtime image digest into `artifacts.json` on build so future rebuilds
   prove immutability without re-inspection.

## Risks

- Docker Desktop bind-mount exec/permissions differ across hosts; the pinned image +
  read-only mount plus the fixture lane (which needs no Docker) bounds this risk.
- CPU-only throughput (~20 tok/s on a 135M model, 2 threads) is sufficient for the
  skeleton but is a reminder that Phase 12+ benchmark gating needs representative CPU
  expectations.
- The full non-live gate has shown occasional timing flakes on a loaded host (fixture
  server + hypothesis tests); rerun the gate before phase transitions if the host is busy.

## Gate status

- Real slice: **PASS** (fresh + resume).
- Offline acceptance lane: 14/14 green (committed in `07a7fcf`).
- Full non-live gate: 630 passed, 8 skipped, 1 deselected; coverage 90.05%.
- Phase 11 requirements manifest (RUNM-001): implemented; Phase 11 gate unaffected by
  this assessment.