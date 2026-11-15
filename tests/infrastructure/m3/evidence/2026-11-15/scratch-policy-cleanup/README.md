# Revised scratch policy cleanup evidence

2026-11-15 (Asia/Bangkok). **Host evidence only; Runner 0.1.1 is not released.**

- `host-tests-final.txt`: 48 Runner tests passed, including capacity variation,
  real preflight with mocked OS/child launch, legacy quota exclusion and release
  metadata/source inspection. `host-tests.txt` is the earlier passing run before
  expanding the preflight regression to positive launch cases.
- `executor-tests.txt`: 39 executor tests passed with fake transport/processes.
- `harness-help.txt`: harness CLI passed; 30 active cases, quota probes excluded.
- `build-script-check.txt`: PowerShell build-script parser passed.
- `diff-check.txt`: `git diff --check` exited 0 (possible Git line-ending warnings).
- `docker-version.txt`: existing Linux engine pipe unavailable; no candidate
  build, image distribution or Kata workload execution occurred.
- `preparation.json`: current Runner source hashes, base commit and dirty status;
  candidate digest/archive fields are null and live acceptance is false. This is
  not a build `release.json` and cannot identify a committed candidate.
- `preservation.json`: SHA-256 comparison with the working tree at task entry
  verified every original infrastructure evidence file, M3 fixture and
  `M3_SCRATCH_INVESTIGATION.md` unchanged, including preexisting edits.

No candidate fixtures or model-generated Python were executed. Host tests use
trusted test/implementation code, static synthetic OCI files and mocked launches.
No installed Kata runtime, Kubernetes configuration, RBAC or network policy was
changed. The original 2026-11-11 live records and earlier 2026-11-15 preparation
records remain unchanged; any references there to deleted proposals are historical.

The [release record](../../../../../../RELEASE_0.1.1.md) lists remaining real
candidate build and trusted Kata acceptance gates. Original abandoned patch
logs/provenance are preserved in [the adjacent archive](../abandoned-scratch-patch/README.md).
