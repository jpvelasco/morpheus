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

After the base has been verified, shut it down, detach and delete its seed, and
mark `vda` read-only in its domain XML. Create scenario guests only with
`validation/vm/clone.sh morpheus-validation-<scenario>`. The helper refuses to
clone a running or unsealed base, force-copies the disk, clears read-only only on
the clone, verifies the storage paths differ, and refuses replacement. Baseline
clones retain the guest hostname, machine identity, and SSH host key, so run one
scenario clone at a time until a later task explicitly adds per-clone identity
regeneration.
