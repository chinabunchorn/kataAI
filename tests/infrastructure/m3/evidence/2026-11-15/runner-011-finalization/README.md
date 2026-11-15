# Runner 0.1.1 final verification evidence

2026-11-15 (Asia/Bangkok). Technical gates passed; the user subsequently approved
Runner 0.1.1 release, M3 closure, and committing/pushing the records.
`final-validation.json` retains its original pre-approval HOLD status;
`release-approval.json` records the subsequent approval. Historical test and build
evidence is retained unchanged. No Git tag or registry publication is included.

- `release.json`, `build-metadata.json`, `inspection.json`: original clean-build
  provenance and static OCI checks. False execution/acceptance flags describe
  build time and are intentionally unchanged after live tests.
- `base-index.json`, `base-manifest.json`, `base-config.json`, `base-lineage.json`:
  cached immutable base metadata and matching candidate layer/diff-ID prefix.
- `runner-tests.txt`, `executor-tests.txt`: 48 and 39 passing host tests.
- `static-checks.txt`, `docker-build-check.txt`, `harness-help.txt`, Docker/buildx
  versions: static checks and tools. `final-validation.json` records final checks.
- `node-preflight.txt`, `network-targets.txt`, `runtime-fingerprint.txt`: health,
  resources, unchanged policies/runtime and rechecked healthy probe targets.
- `image-import.txt`, `deployed-image.txt`: copied archive SHA-256, import, exact
  immutable cache reference, manifest content hash and runtime image config.
- `live-results.json`: all 30 active cases, exact identities and outcomes.
- `cases/`: full rendered inputs/Jobs, inventories, policy snapshots, terminal
  Pod/Job reports, bounded diagnostics, outcomes/events and exact-UID API cleanup.
  These contain only approved trusted fixtures and synthetic CSV, no credentials.
- `suite-execution.json`, `suite-operator.py`, `*-harness.txt`, `*-node-cleanup.json`:
  serial orchestration and independent per-case stopped-process/kubelet checks.
- `security-live.json`, `node-security.json`, `security-teardown-followup.txt`:
  independent live Pod/sandbox/shim/QEMU correlation and exact PID/path teardown.
  Initial stopped sandbox metadata caused a pause for inspection, not a fixture
  failure or retry. It later disappeared under normal runtime garbage collection.
- `final-node-inventory.txt`: namespace/API absence, no Kata sandbox/shim/QEMU,
  exact security guest resources absent and inspected temporary archive cleanup.
- `preservation.json`: historical evidence, M1 assets and fixtures unchanged;
  all 15 build-provenance file hashes still match the clean-build source.

Client observation timestamps are retrieval times; node `date -u`, Kubernetes
timestamps and process start times retain their own clocks. No precise VM stop
latency or synchronized-clock measurement is claimed. Short cases have runtime/
image/terminal evidence and subsequent node absence checks; only security has
independent live QEMU correlation. API cleanup files deliberately do not claim
VM verification; the separate node observations supply that proof.

OCI archive retained locally under ignored
`.m3-runs/build-20261115T070549-3d8be925/runner.oci.tar`. No registry push occurred.
The temporary copied archive was removed after checking its exact path/hash;
imported image cache entries remain available. No runtime-managed files removed.
