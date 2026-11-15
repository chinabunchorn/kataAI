# Fixed Python runner 0.1.1 release verification

Date: 2026-11-15 (Asia/Bangkok). **RELEASED — user approved Runner 0.1.1 and M3 closure.**
All eight technical release gates passed. Runner 0.1.1 is approved for
trusted-fixture integration with the existing KataExecutor adapter.
The user subsequently instructed: “I approve runner 0.1.1 Commit the changes, close M3 in the master roadmap and push the commits”.
This authorizes committing and pushing the verified release records on `kata-infra`.
No merge, Git tag or registry publication is included.

## Artifact and provenance

| Field | Verified value |
|---|---|
| Source branch / commit | `kata-infra` / `11d5465cb95d7ff78fd74f903813a1dba40f966e` |
| Build source state | Clean; `source_worktree_status: []`; all 15 provenance files unchanged after build and finalization |
| Runner / protocol | `0.1.1` / `kataai.runner.v1` |
| Platform / interpreter | Linux/amd64 / Python 3.12.16; Debian trixie base metadata |
| Immutable base | `docker.io/library/python@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b` |
| Runner manifest digest | `sha256:6a682ed00f47fc27c18eb3abd9e3448960133433265ec6442339c9484d246bf9` |
| Config digest | `sha256:19e8bd4750d918f4c21daaea258434eeec3f080a61ae3821181cc1925245af12` |
| OCI archive SHA-256 | `3b3b90076419f21648a175cb5dc764dc38718bb049500e2662772b64eca35a2f` |
| Builder | Docker Desktop 4.83.0, Linux engine 29.6.2, BuildKit 0.31.2, buildx 0.35.0-desktop.2 |
| Built at | 2026-11-15 14:05:54 Asia/Bangkok (07:05:54Z) |
| Build command | `./infra/runner/build.ps1 -Repository 'docker.io/kataai/runner:0.1.1'` |
| Local archive | `.m3-runs/build-20261115T070549-3d8be925/runner.oci.tar` (ignored, retained locally) |

Use only this immutable execution reference:
`docker.io/kataai/runner@sha256:6a682ed00f47fc27c18eb3abd9e3448960133433265ec6442339c9484d246bf9`.

[Build release metadata](tests/infrastructure/m3/evidence/2026-11-15/runner-011-finalization/release.json),
[BuildKit materials](tests/infrastructure/m3/evidence/2026-11-15/runner-011-finalization/build-metadata.json),
[static inspection](tests/infrastructure/m3/evidence/2026-11-15/runner-011-finalization/inspection.json), and
[base lineage](tests/infrastructure/m3/evidence/2026-11-15/runner-011-finalization/base-lineage.json) record provenance. The base's layer
descriptors and rootfs diff IDs match the candidate prefix. All packaged trusted
source hashes match the clean revision. Static inspection verifies OCI blob
digests, linux/amd64, version, Python metadata, USER `10001:10001`, `/tmp` working
directory, root-owned non-writable traversable paths and the exact entrypoint
`python3 -I -B /opt/kataai/runner.py`. The live security fixture independently
observed UID/GID 10001. No candidate executed during build/inspection or on the host.
The build record's false live-acceptance flag describes build time; subsequent
acceptance is recorded separately, without rewriting provenance.

Docker initially had no Linux engine pipe. The CLI start command failed because
its registry lookup could not locate Docker Desktop. Starting the existing
Docker Desktop executable outside the sandbox succeeded. No reinstall, system
configuration change, registry service or new builder was needed.

## Verification results

| Gate | Result / evidence |
|---|---|
| Host runner tests | **48 passed**: `python -B -m unittest discover -s tests/unit/runner -v` |
| Host executor tests | **39 passed**: `python -B -m unittest discover -s tests/unit/executor -v` |
| Static checks | PowerShell parser, 19 trusted Python AST files, harness help, Docker build checks (no warnings), active documentation links and `git diff --check` passed |
| OCI artifact | Real manifest/config/archive hashes; source/layout/permissions/base lineage inspected |
| Distribution | Approved SSH/SCP → unique temporary archive → existing `ctr -n k8s.io images import --platform linux/amd64 --digests`; archive hash and manifest content verified; exact digest reference registered in cache |
| Live trusted catalog | **30 passed, 0 failed, 0 unrun**, serially; all executed Pods used the exact manifest imageID; missing-runtime created zero Pods |
| Kata placement | Security Job/Pod UID → containerd sandbox labels/runtime → shim 1565141 → QEMU 1565166, `accel=kvm`, guest kernel 6.18.56 |
| Cleanup | Exact-UID Job/ConfigMap deletion and associated Pod absence for every case; per-case node process/path observations; exact security PIDs/guest paths stopped and sandbox metadata later absent |
| Documentation / regressions | Current docs reconciled; historical failures preserved; no blocking runner regression observed |

[Complete evidence index](tests/infrastructure/m3/evidence/2026-11-15/runner-011-finalization/README.md) links host logs, deployed image checks,
all case snapshots/outcomes/cleanup, network target health and final node inventory.
[Live matrix](tests/infrastructure/m3/evidence/2026-11-15/runner-011-finalization/live-results.json) records exact identities, expected/observed
codes and bounded diagnostics. Security cleanup's first snapshot retained stopped
sandbox metadata, so the suite paused for investigation; exact PID/path absence
and later metadata garbage collection were recorded. Security was not rerun.
Successful API deletion alone was never treated as guest teardown proof.

The node was Ready, containerd active, with 4 allocatable CPUs, about 7.66 GiB
allocatable memory and 13 GiB free disk at preflight. The existing RuntimeClass,
handler and default-deny policy matched their historical UIDs. Applicable Calico
policy checks passed. Network target addresses/healthy CoreDNS peer and node API/
kubelet reachability were rechecked without relaxing policy. Kata shim fingerprint
matches the historical standard runtime. No runtime, cluster installation,
RBAC, policy or VM allocation was changed. Only trusted catalog fixtures ran in Kata.

## Contract, limitations and release boundary

The [approved design](docs/milestone-3-design.md) retains namespace `kata-lab`,
RuntimeClass/handler `kata-qemu-runtime-rs`, read-only root/inputs, UID/GID/fsGroup
10001, no escalation, dropped capabilities, RuntimeDefault seccomp and no token
automount/service links. Input caps remain script 32 KiB, CSV 512 KiB, ConfigMap
768 KiB. Results are JSON object/array, 2048 raw bytes, depth 16, 128 entries per
collection / 256 total; File termination reports are capped at 3072 bytes.
Diagnostics retain 8192 bytes per stream and terminate above 16384 observed bytes
combined. Script/Job deadlines are 30/120 s, no retries, restart Never. Resource
requests/limits and protocol exits are unchanged.

Standard Kata exposes writable guest tmpfs at `/tmp`, observed capacity and
available space **100,691,968 bytes**, with `rw` mount flags and actual successful
security-fixture writes. `emptyDir.sizeLimit: 16Mi` remains configuration, **not
a verified guest quota**. Exact quota and quota-exhaustion probes are excluded
from active release gates. The custom Rust shim/agent patch was abandoned.
Historical 0.1.0 evidence remains **30 passing checks, one failed quota check and
one dependent unrun case**, with the bounded 20 MiB write failure unchanged.
The historical 0.1.0 digest is not this release.

Scratch may consume memory beyond 16 MiB; full scratch/abrupt death may prevent a
report and collection fails closed. Same-UID report/process tampering, diagnostic
bypass, selected network/credential probe scope and host-only OOM/infrastructure
mapping evidence remain limitations. No general untrusted-code isolation or new
effective memory bound is claimed. M6/M8 still gate generated Python.

The existing [KataExecutor](infra/executor/README.md) is host-tested and uses this
runner contract. Live adapter/application integration, real worker wiring,
PostgreSQL/journal coordination, authorization/image/teardown callbacks,
application credentials, admission and recovery tests remain **M4/M5**, outside
this task. User approval closes M3 and authorizes committing/pushing these records.
The image remains in the verified lab cache; no registry publication is claimed.
