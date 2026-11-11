# M3 evidence — 11 November 2026

**M3 is incomplete: configured scratch capacity was not enforced inside Kata.**

- `release.json`: actual image manifest digest, platform, base, source/archive
  hashes and build metadata. False execution/acceptance flags describe the build
  stage, not the subsequent tests. The OCI archive is retained locally in
  `.m3-runs/build-20261111T104057-6ae52049/runner.oci.tar` and imported in the
  existing node image cache. No registry service or runtime reconfiguration.
- `live-results.json`: 30 passing live fixture checks, one failed scratch-capacity
  check and one unrun dependent scratch-exhaustion case. Includes independently
  revalidated reports, exact Job/Pod IDs and image/runtime, input hashes, native
  exit statuses, retained diagnostic byte counts and API cleanup observations.
- `node-security.json`: live Pod → sandbox → shim/QEMU/KVM correlation for the
  security fixture and exact PID/path teardown checks. This is one correlated VM
  observation, not a separate live process capture for every short test.
- `scratch-failed-pod.json`, `scratch-failed-diagnostics.jsonl`: preserved failing
  20 MiB probe, which must not be relabeled as successful resource enforcement.
- `final-inventory.json`: final namespace/runtime/process observations and node
  versus guest scratch mount-capacity discrepancy.

Host-only command `python -B -m unittest discover -s tests/unit/runner -v` passed
39 tests on Python 3.13.15. Trusted-source syntax and the PowerShell build script
parser passed. Static OCI inspection validated blobs, source contents, non-root
configuration, root ownership and traversable/non-writable trusted paths. No
candidate program was imported, compiled or executed by host checks/builds.

Only team-controlled trusted fixtures executed, inside the approved Kata guest.
Kubernetes/containerd/Kata/Calico configuration, persistent RBAC and M1 assets were
preserved. Final inventory found no remaining test Job/Pod/input ConfigMap, Kata
sandbox or shim/QEMU process. Inspected temporary remote archive staging was
removed; fixed runner image cache entries remain. Full scratch enforcement,
M6 security certification and M8 validation are not established by these records.

Full observations and limitations: [M3 acceptance](../../../../../docs/infrastructure/M3_ACCEPTANCE.md).
