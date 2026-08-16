# Qualification Runbook (HOST-003, PLAT-004)

Morpheus v0.2 qualifies exactly the targets in the frozen matrix
(`core/targets.py`): batwing and batmobile (Linux x86-64, NVIDIA CUDA,
vLLM tier), one Windows 11 x86-64 host (native `llama.cpp`), and one
Apple Silicon macOS host (native `llama.cpp`). Everything else is
reported honestly as unvalidated; no support claim exists outside this
registry.

## Reading the support report

`GET /api/v1/support` returns:

- `dimensions`: machine-level evidence-bounded claims (proven only with
  retained PASS evidence; every proven claim carries `run_id:digest`);
- `targets`: the frozen matrix with per-target declared claims. Every
  claim maps to an exact artifact (`evidence_run` or `benchmark_run`),
  machine, lane (`HOST-RO` or `HOST-MAINT`), and rollback path;
- `validated`: a target is validated only when every declared claim is
  proven;
- `advertised`: only evidence-proven machine claims; never a target that
  lacks its physical qualification evidence.

## Qualifying a target

1. Run the HOST-RO discovery and smoke lanes on the physical machine and
   finalize PASS evidence runs under `data_dir/diagnostics` with
   `environment: HOST-RO` (or HOST-MAINT for lifecycle, recovery, and
   benchmark lanes) and `machine_profile.machine_id` set to the target.
2. Complete benchmark campaigns for the declared engine tier so the
   engine and benchmark claims have `benchmark_run` evidence.
3. Re-check `GET /api/v1/support`: the target flips to `validated` only
   when every declared claim carries evidence.

A DEV or VM run never qualifies a physical target, and no claim may be
flipped by hand: the report derives everything from retained evidence.

## Rollback paths

Each declared claim names its recovery path: package rollback for install
and OS/architecture claims, lifecycle rollback for accelerator and engine
claims, settings rollback for access claims, bootstrap rollback for
recovery claims, and a benchmark rerun for benchmark claims. Evidence that
cannot point at its rollback path is never advertised.