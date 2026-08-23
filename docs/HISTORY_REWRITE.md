# History identity migration

On 2026-08-10, before the repository's first GitHub publication, all 38 Git
commits were rewritten to replace the author's and committer's personal email
with the account-linked GitHub noreply address. Commit file trees, topology,
author and committer names, timestamps, and messages were preserved; abbreviated
Git commit references inside commit messages were translated automatically.

Because commit metadata participates in Git object identity, every affected
commit received a new SHA. Before publication, a verified recovery bundle, the
complete old-to-new commit map, and before/after metadata ledgers were used to
validate the migration. After rewritten `main` was independently verified on
the private GitHub origin, that external legacy recovery material was
intentionally deleted on 2026-08-10. The published repository therefore retains
no pre-rewrite Git objects; only the operational legacy artifact identifiers
documented below remain.

## 2026-08-22 GitHub Refresh Reconciliation

During the 2026-08-22 documentation refresh, GitHub reported a forced update of
`origin/main` from local tip `712d3df` to remote tip `9b4cda0`. Git found no
merge base between the two histories; the remote contained rewritten
counterparts of earlier pull-request commits plus later work through PR #49.
The clean local pre-refresh tip was preserved on the local archival branch
`archive/local-main-before-refresh-20260822`, and local `main` was then aligned
to `origin/main` without relabelling any artifact.

This refresh discontinuity affects source commit identity only. Historical v0.1
artifact manifests and the explicit legacy-to-rewritten candidate mapping below
remain authoritative for their exact files. Do not infer an artifact rebuild or
translate an embedded source ID merely because branch history changed.

## Deployed legacy candidate

The running ubuntu-1 images were built before this identity migration. Their
immutable tags and OCI labels correctly retain legacy source ID
`aa7174aff3194ffeb1ca455d53005f242abe6d82`. The content-equivalent rewritten
source commit is `fa5fe3ca2e393d6d20c1afa89dff2452650bf180`.

Do not relabel those existing artifacts as if they were rebuilt. A future
candidate build should use the rewritten Git identity normally, producing new
manifests, image labels, and artifact names.
