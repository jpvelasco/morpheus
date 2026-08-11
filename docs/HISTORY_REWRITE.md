# History identity migration

On 2026-08-10, before the repository's first GitHub publication, all 38 Git
commits were rewritten to replace the author's and committer's personal email
with the account-linked GitHub noreply address. Commit file trees, topology,
author and committer names, timestamps, and messages were preserved; abbreviated
Git commit references inside commit messages were translated automatically.

Because commit metadata participates in Git object identity, every affected
commit received a new SHA. A verified recovery bundle, the complete old-to-new
commit map, and before/after metadata ledgers are stored outside this repository
under:

```text
/home/operator/Documents/source/backups/morpheus-pre-noreply-rewrite-20260810/
```

## Deployed legacy candidate

The running ubuntu-1 images were built before this identity migration. Their
immutable tags and OCI labels correctly retain legacy source ID
`aa7174aff3194ffeb1ca455d53005f242abe6d82`. The content-equivalent rewritten
source commit is `fa5fe3ca2e393d6d20c1afa89dff2452650bf180`.

Do not relabel those existing artifacts as if they were rebuilt. A future
candidate build should use the rewritten Git identity normally, producing new
manifests, image labels, and artifact names.
