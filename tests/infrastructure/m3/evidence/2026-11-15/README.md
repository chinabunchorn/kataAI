# 0.1.1 preparation evidence

2026-11-15 (Asia/Bangkok). Host-only evidence; **not live Kata acceptance**.

- [host-tests.txt](host-tests.txt): 47 runner tests passed with Windows Python
  3.13.15; no fixture programs executed.
- [preparation.json](preparation.json): base commit and exact SHA-256 hashes of
  the 15 build-provenance files for this uncommitted preparation. Digest fields
  are null because no candidate image/archive exists. This is not `release.json`.
- [docker-version.txt](docker-version.txt): client available, Linux engine pipe
  absent; command exited 1. Buildx separately reported
  `v0.35.0-desktop.2 b554ce1decd8b509893b1e7c6227eabfb923d094`.

Other host checks passed: M3 harness `--help`, PowerShell AST parsing of
`infra/runner/build.ps1`, trusted implementation/test/harness syntax compilation
without fixture compilation or execution, and `git diff --check`.

No build, image distribution, cluster access, workload execution or runtime
change occurred. Historical live evidence remains in the 2026-11-11 directory.
See [release decision](../../../../../RELEASE_0.1.1.md) and
[scratch proposal](../../../../../docs/infrastructure/M3_SCRATCH_FIX_PROPOSAL.md).
