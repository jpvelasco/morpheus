# Validation Lab

This directory contains versioned, secret-free inputs for the isolated
Morpheus release-validation lab. It does not contain a Morpheus installation or
credentials.

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
