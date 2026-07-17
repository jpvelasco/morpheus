# Morpheus Lifecycle Operations

Morpheus lifecycle control is a separate, authenticated command surface for
Morpheus-owned resources. The ordinary `morpheus` CLI remains read-only.
Lifecycle support is disabled by default and does not accept a container name,
resource name, executable, shell fragment, or caller-selected Compose path.

This document defines the implemented operation contract. It does not replace
the clean-VM install, upgrade, rollback, uninstall, and external-integrity
evidence required by the release validation plan.

## Fixed Deployment Layout

The host runtime agent must be configured with one absolute deployment root:

```text
/opt/morpheus-deployment/
├── morpheus.env
└── releases/
    ├── 0.1.0/
    │   ├── release.json
    │   ├── compose.yaml
    │   └── candidate.yaml
    └── 0.2.0/
        ├── release.json
        ├── compose.yaml
        └── candidate.yaml
```

`morpheus.env` is a locally created, mode-`0600` file containing the exact
candidate image references, project ID, ports, external network name, and
secret-file configuration. Lifecycle code passes this fixed path to Compose;
it does not read or emit its values.

Every `release.json` is a closed manifest. For example:

```json
{
  "compose_files": ["compose.yaml", "candidate.yaml"],
  "format": 1,
  "version": "0.1.0"
}
```

Release directories, manifests, environment files, and Compose files must be
regular non-symlink files beneath the configured root. Compose runs with a
fixed project ID, `--no-build`, and `--pull never`.

## Agent Configuration

The host agent configuration includes:

```dotenv
MORPHEUS_ENABLE_LIFECYCLE=true
MORPHEUS_LIFECYCLE_DEPLOYMENT_ROOT=/opt/morpheus-deployment
MORPHEUS_LIFECYCLE_LAB_AUTHORIZED=false
```

Keep `MORPHEUS_LIFECYCLE_LAB_AUTHORIZED=false` on ordinary installations. The
runtime-agent credential and either its loopback URL or owned Unix socket are
configured as described in the main environment template.

## Commands and Repeat Semantics

All commands support `--json`. Results use `applied`, `already_satisfied`, or
`validated` and report only whether the protected external runtime remained
unchanged.

```bash
morpheus-lifecycle validate 0.1.0 --json
morpheus-lifecycle install 0.1.0 --json
morpheus-lifecycle start --json
morpheus-lifecycle stop --json
morpheus-lifecycle migrate --json
morpheus-lifecycle backup before-upgrade --json
morpheus-lifecycle restore-preflight before-upgrade --json
morpheus-lifecycle upgrade 0.2.0 --json
morpheus-lifecycle rollback --json
morpheus-lifecycle uninstall --json
```

- Repeating install for the active version, start while running, stop while
  stopped, a completed migration, or the same named backup returns
  `already_satisfied`.
- Validate and restore-preflight are non-mutating and return `validated` on
  every successful run.
- Upgrade creates a deterministic Morpheus-only backup before replacement.
  Failure invokes recovery to the exact pre-operation lifecycle snapshot.
- Rollback restores the recorded pre-upgrade backup and prior release. Once
  completed, repeating rollback returns `already_satisfied`.
- Uninstall removes runtime resources but preserves Morpheus data and backups
  by default. Repeating it returns `already_satisfied`; reinstalling the same
  release reuses preserved state.

## Lab-only Purge

Purge is intentionally awkward. It requires a disposable lab agent configured
with `MORPHEUS_LIFECYCLE_LAB_AUTHORIZED=true` and the exact project-scoped
confirmation:

```bash
morpheus-lifecycle uninstall \
  --purge-confirmation purge:morpheus-lab \
  --json
```

Before data deletion, the adapter requires the exact Morpheus ownership marker.
It rejects unmarked, differently marked, symlinked, or broad data roots. The
external Docker network is never removed.

## Integrity and Recovery Boundary

Before and after every operation, the runtime agent hashes selected identity
fields for `qwopus-coder`, Open WebUI, and the configured external network. It
does not request container environment values. A changed digest fails the
operation evidence. Existing Compose-project containers, volumes, and networks
must also carry the exact `io.morpheus.project` label; protected external names
are rejected even if a label is forged.
