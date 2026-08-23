# Validation Lab

This directory contains versioned, secret-free inputs for the isolated
Morpheus release-validation lab. It does not contain a Morpheus installation or
credentials.

The v0.2 development line is currently under architecture rectification. Use
this lab for explicitly scoped disposable R1-R9 work, but do not freeze a
qualification candidate or run a physical lane until the entry gate in
[`docs/RECTIFICATION_PLAN.md`](../docs/RECTIFICATION_PLAN.md) is green.

The VM baseline is defined by
[`vm/ubuntu-26.04-amd64.json`](vm/ubuntu-26.04-amd64.json). Its cloud image URL
and SHA-256 are pinned to the official Ubuntu 26.04 release build dated
2026-07-13. The guest has libvirt NAT only, no GPU, no host share, and no host
Docker socket. Cloud-init is attached as a read-only virtio block device because
the Ubuntu cloud-image kernel did not read the generic machine's IDE CD-ROM.

`vm/cloud-init/user-data.yaml.in` contains exactly one
`__SSH_PUBLIC_KEY__` placeholder. Render it only into an ignored local cache
using the dedicated validation public key; never add a private key or rendered
user-data to Git. The project-pinned `uv` version matches CI. Other specialized
release tools remain containerized and will be pinned by digest under TOOL-001.

The sealed baseline must contain only the declared operating-system
prerequisites. Clone it before installing Morpheus or running a test. See the
[release validation plan](../docs/RELEASE_VALIDATION_PLAN.md) for LAB-001 and
the dependency-ordered execution waves.

From the repository root, `validation/vm/provision.sh` downloads and verifies
the pinned image, creates a dedicated SSH key under `~/.ssh`, renders cloud-init
under `~/.cache/morpheus-validation`, creates libvirt-managed volumes, and
starts the base guest. It refuses to replace an existing domain or guest disk.
The downloaded source image and trusted libvirt cloud-image volume can be reused
after a failed guest build; remove named lab resources deliberately rather than
adding automatic destructive cleanup.

After the base has been verified, run its installed template-seal helper, which
cleans cloud-init, machine ID, and SSH identity before powering off. Detach and
delete its seed, then mark `vda` read-only in its domain XML. Create scenario guests only with
`validation/vm/clone.sh morpheus-validation-<scenario>`. The helper refuses to
clone a running or unsealed base, force-copies the disk, clears read-only only on
the clone, verifies the storage paths differ, refuses replacement, and attaches
a scenario-specific NoCloud seed. Concurrent clones regenerate distinct
hostnames, machine IDs, cloud-init instance IDs, and SSH host keys without
changing the sealed base.

`validation/docker-context/verify.sh` uses Docker itself to prove ignored dirty
developer state produces the same immutable context layer. The deterministic
OpenAI-compatible success, streaming, metrics, and fault fixtures live under
`validation/fixtures/`; their Compose network is internal-only and their probe
proves protected names and public egress are unavailable.

## Evidence Runner

After `uv sync --extra dev --frozen`, wrap an evidence-producing command with
the installed `morpheus-evidence` entry point. It writes only below the ignored
`artifacts/release-validation/` tree, captures redacted stdout/stderr, records a
structured command result, imports only privacy-clean declared artifacts, and
atomically finalizes a checksummed manifest. For example:

```console
morpheus-evidence \
  --task CONT-002 \
  --requirement RUN-001 \
  --requirement RUN-002 \
  --environment VM \
  --reviewer release-operator \
  --tool docker=29.1.3 \
  -- docker compose -f deploy/compose.yaml config
```

Use `--authorization-ref` for every `HOST-RO` or `HOST-MAINT` run. Privacy
canaries may be supplied as a JSON object through `--canary-file`; that file
must be a regular file with no group or other permissions. The runner injects
each value only into the child environment as
`MORPHEUS_EVIDENCE_CANARY_<CLASS>`, replaces canaries in text/JSON output, and
rejects opaque files or nested ZIP members that contain a raw value. Only
`sha256:` canary identifiers are recorded in the manifest.

## Live Read-Only vLLM Validation

The live lane has no target fallback. Declare the exact current vLLM routes
and allowlist their host explicitly before running it:

```console
export MORPHEUS_LIVE_ALLOWED_HOSTS=127.0.0.1
export MORPHEUS_LIVE_VLLM_URL=http://127.0.0.1:8000/v1
export MORPHEUS_LIVE_VLLM_METRICS_URL=http://127.0.0.1:8000/metrics
export MORPHEUS_LIVE_TIMEOUT_SECONDS=5
make test-live-readonly
```

If the endpoint requires a key, supply it only through
`MORPHEUS_LIVE_VLLM_API_KEY`; it is never included in the structured report.
The lane accepts only exact `GET /v1/models` and `GET /metrics` requests,
disables redirects and transport retries, and rejects mutation or completion
flags. Wrap release runs with `morpheus-evidence`, `--environment HOST-RO`, and
an explicit authorization reference. The emitted report contains no endpoint,
host, credential, request content, response content, or metric values.

## Disposable Telemetry Compatibility

`smoke/telemetry.py` compares direct and proxied non-streaming and streaming
bytes, usage, authentication, normalized upstream failures, timeouts, client
cancellation, capacity recovery, and direct bypass. The OpenAI fixture network
must remain `internal: true`; do not publish the fixture merely to run the
direct leg. Execute the probe inside the disposable telemetry container, where
the proxy is reached on container loopback and the direct endpoint comes from
the already validated `MORPHEUS_LLM_BASE_URL`:

```console
docker exec -i DISPOSABLE_TELEMETRY_CONTAINER \
  python - --container-mode < validation/smoke/telemetry.py
```

`smoke/telemetry_state.py` has `inspect-backup`, `seed-expired`, and
`verify-restart` actions. Stream it over stdin as well so the read-only
container filesystem remains unchanged. It validates the metadata-only schema,
required outcomes, raw database and backup privacy canaries, logical backup
equivalence, recent-state persistence, and startup removal of the explicitly
expired fixture record. These probes are only for a uniquely named disposable
project and Morpheus-owned volume; never run them against an externally owned
service or data path.

## Containerized Release Tools

[`tools/images.lock.json`](tools/images.lock.json) is the source of truth for
the linux/amd64 Node, Playwright, Gitleaks, Trivy, Syft, and k6 images. It records
both each registry index and exact platform-child digest, upstream source,
license, version, and purpose. Accessibility runs in the pinned Playwright image
with `@axe-core/playwright` locked by exact npm version and integrity. Trivy is
used separately for vulnerability/misconfiguration and license policy; Syft
produces CycloneDX and SPDX SBOMs.

These tools are intentionally containerized. A validation host or guest needs
Docker Engine with Buildx and enough image/payload storage; it does not need
host installations of Node, browsers, Gitleaks, Trivy, Syft, or k6. Pull and run
the lock's digest-only `reference`, never a tag copied from documentation.

## Browser Development Gate

Run the internal-only browser rehearsal with:

```console
BROWSER_ARTIFACT_ROOT="$PWD/artifacts/browser-dev" make browser-gate
```

The runner verifies the local Playwright image identity against the tool lock,
uses a non-root read-only container with networking disabled, builds and serves
the production dashboard inside that container, and runs deterministic
Chromium, Firefox, WebKit, and mobile Chromium projects. Route interception
supplies synthetic control-API responses; it never contacts the host control
API, inference runtime, or Open WebUI. Failure traces, screenshots, and video
remain under the selected ignored artifact root. A closed post-run scan rejects
plain or zipped evidence containing the synthetic credential canary.

This DEV gate does not replace BROW-006 against the exact disposable candidate.
Candidate validation must additionally exercise real CSP, CORS, cookie, CSRF,
framing, and request-ID behavior through the candidate's dashboard/API boundary.

## Load, Resource, and Soak Profiles

[`load/workload.json`](load/workload.json) is the versioned workload contract.
It fixes the CPU-only fixture, direct and telemetry paths, stream mix, payload
shape, synthetic inference delay, VUs, warm-up, measurement duration, sampling,
graceful stop, and abort thresholds. `dev` is a source rehearsal,
`qualification` is the ten-minute comparison profile, and `soak` is exactly 24
hours after a two-minute warm-up. The k6 client cannot accept an arbitrary URL;
it selects only the fixture or telemetry service on a Docker network that the
runner verifies is internal and labeled for the exact disposable project.
Each k6 container carries the exact project and one-run labels. The runner's
exit trap verifies those labels before stopping an interrupted container, so a
failed or canceled workload cannot continue in the background.

Run the short isolated source rehearsal with:

```console
LOAD_ARTIFACT_ROOT="$PWD/artifacts/load-dev" make load-dev
```

The rehearsal refuses existing project resources, builds a four-service
fixture/API/dashboard/telemetry stack with no host ports, runs direct and
proxied traffic using separate mode-600 synthetic key files, compares median
wait and request throughput, and samples labeled API/dashboard memory, PIDs,
and Docker CPU normalized by the daemon's logical CPU count. Its exit trap
removes only the exact disposable project's containers, images, volume,
network, and temporary key files.

DEV output is not release evidence. Qualification and soak must use the exact
candidate in the clean VM and retain start/end logical state, periodic resource
series, bounded log/database growth, health, fault, and external-integrity
checks under the evidence runner. Never point these profiles at the external
vLLM; LIVE-PERF-001 requires a separate explicit state-changing authorization.

After all shorter exact-candidate lanes are green and the evidence runner has
started the candidate stack, invoke the soak wrapper with explicit paths and
the exact-duration confirmation:

```console
export CANDIDATE_MANIFEST=/absolute/path/to/candidate-manifest.json
export LOAD_PROJECT_ID=morpheus-release-lab
export LOAD_NETWORK=morpheus-release-lab_internal
export LOAD_API_KEY_FILE=/absolute/path/to/mode-600-synthetic-proxy-key
export LOAD_ARTIFACT_ROOT="$PWD/artifacts/release-validation/SOAK-002"
export SOAK_CONFIRM_DURATION=24h
validation/load/soak.sh
```

The wrapper never starts, stops, or rebuilds containers. It verifies the
candidate artifact set, requires the running labeled API/dashboard images to
match that candidate's commit and version, samples the full two-minute warm-up
plus 24-hour measurement interval, rejects absolute memory-budget and declared
memory/PID-growth violations, and runs only the proxied periodic workload. If
either load generation or resource monitoring exits early, the supervisor
terminates its peer and fails the soak instead of waiting out or leaking the
remaining process. The
surrounding evidence task remains responsible for declared fault injection,
logical database/log growth, health history, start/end state, and protected
external-integrity snapshots.

## Release Supply-Chain Gate

SEC-005 uses a four-step workflow so public database download is separated
from the offline candidate scan and the human license decision. First populate
an ignored, checksummed Trivy cache while network access is allowed:

```console
export TRIVY_CACHE_OUTPUT="$PWD/artifacts/security-release/trivy-cache"
validation/security/populate-cache.sh
```

Then point the scanner at one already verified candidate. The scan phase
refuses output outside `artifacts/`, verifies the candidate and scanner image
digests, rechecks the cache inventory, stages only tracked/non-ignored worktree
files, runs the secret and Trivy gates with networking disabled, and generates
CycloneDX JSON and SPDX JSON for every declared candidate artifact:

```console
export CANDIDATE_MANIFEST=/absolute/path/to/candidate-manifest.json
export SECURITY_OUTPUT_ROOT="$PWD/artifacts/security-release/reports"
export TRIVY_CACHE_DIR="$TRIVY_CACHE_OUTPUT"
validation/security/run.sh scan
```

Review every generated license report, copy
`license-review.template.json` to a mode-600 ignored file, replace the pending
fields, and record any exception with an owner, rationale, and future expiry.
No automatic license classification substitutes for this review. Finalization
binds the approval to the exact report digests and rejects secrets, forbidden
licenses, unresolved high/critical findings, stale or altered inputs, missing
scan scopes, or incomplete SBOM coverage:

```console
export LICENSE_REVIEW_FILE=/absolute/path/to/completed-license-review.json
validation/security/run.sh finalize
make release-gate
```

A DEV scan is useful for finding implementation defects, but it does not
constitute candidate evidence. Candidate evidence must come from the exact
clean VM-built candidate and be wrapped by the evidence runner; scanner reports,
SBOMs, license review, database metadata, and the verified supply-chain
manifest remain ignored under `artifacts/`.

## Candidate Artifact Set

[`candidate/artifact-set.json`](candidate/artifact-set.json) defines the ten
required outputs from one clean full Git object ID and its commit timestamp:
Python sdist and wheel, backend and dashboard OCI layouts, an offline
host-native runtime-agent bundle, Compose/config,
migrations, requirements evidence, `SHA256SUMS`, and a self-contained rollback
bundle. [`candidate/manifest.schema.json`](candidate/manifest.schema.json)
defines the produced manifest. `morpheus.ops.candidate.verify_candidate`
rejects missing or extra artifacts, mixed commits, unsafe paths, media-type or
size drift, checksum mismatches, and incomplete `SHA256SUMS` coverage.

`candidate/build.sh` supplies deterministic, offline subcommands for the
Compose/config, migration, requirements, checksum, and rollback bundles. It
requires `CANDIDATE_OUTPUT_ROOT`, `CANDIDATE_VERSION`, `SOURCE_DATE_EPOCH`, and
`SOURCE_COMMIT`; archives are sorted, timestamp-normalized, numeric-owner tar
streams compressed with timestamp-free gzip.

Python and OCI producers use an explicit two-step cache protocol. Run
`candidate/populate-cache.sh CACHE_EVIDENCE_DIRECTORY` once with networking
enabled. Then run
`vm/offline-egress.sh candidate/rebuild-offline.sh CACHE_MANIFEST OUTPUT` in a
disposable validation guest. The wrapper requires working egress before the
test, installs a dedicated nftables table that drops guest and container
egress while preserving the established SSH session, proves egress is blocked,
and always removes only that table on exit. The rebuild refuses a dirty or
different source commit and exports the Python and OCI artifacts solely from
the populated, hash-inventoried wheelhouse and npm content cache. Only the two
digest-pinned base images remain in the local Docker store. Candidate image
builds use the dedicated offline Dockerfiles, `--network=none`, and
`--no-cache`; they verify the wheelhouse, run npm in offline mode, normalize
generated filesystem timestamps to the commit, and attach OCI identity and
health metadata. Each OCI archive also carries the deterministic
`morpheus/backend:<version>-<commit>` or
`morpheus/dashboard:<version>-<commit>` name used by `docker load`.

Run `candidate/compare-rebuilds.sh FIRST SECOND RESULT_JSON` on rebuilds from
two independent VM clones. It verifies each checksum inventory, requires the
source identity to match, and byte-compares all four artifacts. The candidate
is reproducible only when the generated result has `status: pass`; there is no
allowance for unexplained OCI manifest drift.

For container smoke tests, combine `deploy/compose.yaml` with
`candidate/compose.yaml`, set `MORPHEUS_BACKEND_IMAGE` and
`MORPHEUS_DASHBOARD_IMAGE` to the loaded candidate tags, and use
`docker compose --env-file .env up --no-build`. Selecting the root environment
file explicitly is required because the first Compose file is below `deploy/`.
This ensures startup tests consume the exported candidate instead of silently
rebuilding a different image.
