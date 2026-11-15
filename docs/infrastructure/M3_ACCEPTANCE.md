# M3 implementation and acceptance record

## Current release policy — 2026-11-15

The user chose the existing **unmodified Kata Containers runtime** for KataAI.
Exact 16 MiB guest scratch enforcement is **no longer a Runner 0.1.1 release
requirement**. The custom Rust patch, correction and installation proposals,
and obsolete patch review were removed. Original patch check logs and provenance
are retained as [abandoned-work evidence](../../tests/infrastructure/m3/evidence/2026-11-15/abandoned-scratch-patch/README.md).
No installed runtime, Kubernetes configuration, RBAC or network policy is changed.

Required scratch behavior is a distinct writable guest tmpfs at `/tmp`, positive
capacity and available space, with bounded valid mountinfo. Preflight checks
mount identity and writable flags; the existing trusted `security` case must
observe real writes and `scratch-layout` must record actual capacity. The
configured memory emptyDir `sizeLimit: 16Mi` remains unchanged, but is not a
verified guest quota. Memory/CPU limits, read-only root/inputs, non-root identity,
result/diagnostic bounds, deadlines, runtime placement and network controls remain
required. Scratch can consume memory beyond 16 MiB; full scratch or abrupt death
can prevent a report. Do not infer a new effective memory bound from this policy.

The original `scratch` and `scratch-failure` expectations and fixture bytes remain
preserved, along with the proposed multi-file probe. They are legacy quota tests,
excluded from the current executable release catalog and acceptance gates. The
historical capacity test remains **failed** and the dependent case remains
**unrun**; neither is relabeled as passing or counted toward candidate acceptance.
[M3_SCRATCH_INVESTIGATION.md](M3_SCRATCH_INVESTIGATION.md) and original evidence
are preserved without rewriting their results.

## Current 0.1.1 verification — 2026-11-15

**M3 COMPLETE — Runner 0.1.1 RELEASED with user approval on 2026-11-15.**
All current M3 verification requirements passed under the amended standard-Kata
policy. The user explicitly approved Runner 0.1.1, closing M3, and committing
and pushing the verified records. M4/M5 and M6/M8 remain separate open gates.

- Clean source commit `11d5465cb95d7ff78fd74f903813a1dba40f966e`; inspected manifest
  `sha256:6a682ed00f47fc27c18eb3abd9e3448960133433265ec6442339c9484d246bf9`.
- 48 runner and 39 executor host tests passed. PowerShell, trusted AST, Docker
  static build checks, harness help, active links and diff checks passed.
- Exact OCI archive imported through the approved existing containerd cache path;
  manifest content and all executed Pods' actual imageID match the inspected digest.
- Full **30-case active trusted catalog: 30 passed, 0 failed, 0 unrun**, serially.
  Canonical object/array, invalid/missing/bounded results, syntax/runtime/status
  spoofing, timeouts, stdout/stderr bounds, security, scratch-layout, network and
  missing RuntimeClass passed. The negative runtime case created zero Pods.
- Security Pod `dd08f322-e02a-4ca6-becc-2f9f6ff8646a` matched Job UID
  `1bf66a13-e0a3-4e56-8932-dc484bd2941a`, sandbox
  `848a251799be5f736b104abc9f7e06e3b70092d28a212e040e498e1365d0d6e6`,
  Kata shim PID 1565141 and child QEMU PID 1565166 with `accel=kvm`.
- Every run reached exact-UID API cleanup and node-side stopped-process/path
  checks. Exact security PIDs and guest/runtime/kubelet directories were absent;
  initially retained stopped sandbox metadata was investigated and later absent.
  API cleanup records retain `vm_teardown_verified: false`; independent node
  evidence supplies the separate teardown proof rather than altering those records.
- Scratch-layout observed writable guest tmpfs with capacity/available space
  100,691,968 bytes. Security observed actual writes. No exact quota is claimed.
- Installed standard shim hash matches historical evidence. No installed runtime,
  policies, credentials, cluster configuration or VM allocations were changed.

See [current release decision](../../RELEASE_0.1.1.md),
[complete evidence](../../tests/infrastructure/m3/evidence/2026-11-15/runner-011-finalization/README.md),
[live results](../../tests/infrastructure/m3/evidence/2026-11-15/runner-011-finalization/live-results.json) and
[independent VM correlation](../../tests/infrastructure/m3/evidence/2026-11-15/runner-011-finalization/node-security.json).
Historical 0.1.0 observations below remain unchanged and do not certify 0.1.1.
M4/M5 application integration and M6/M8 generated-code gates remain open.

## Historical 0.1.0 acceptance — unchanged observations

Date: 2026-11-11 (Asia/Bangkok)

This is historical 0.1.0 evidence. The 2026-11-15 preparation of 0.1.1 is recorded
in [RELEASE_0.1.1.md](../../RELEASE_0.1.1.md). The current policy above supersedes
the historical exact-capacity release gate, without changing any results below.

Contract: [approved revision 1](../milestone-3-design.md)

Status: **Implemented and built; 39 host tests and 30 live Kata checks passed.
Scratch-capacity acceptance failed; one dependent case is unrun. M3 is not complete.**

User approval: “Yes I approve” in this chat, accepting the concrete revision 1
proposal. This approval freezes the M3 runner defaults. It does not mark tests
passed or authorize infrastructure installation, persistent RBAC changes, or
execution of model-generated code.

## Task traceability

| Roadmap task | Implementation | Acceptance evidence / remaining gate |
|---|---|---|
| M3-T01 | `infra/runner/Dockerfile`, `.dockerignore`, `requirements.txt`, `build.ps1`, fixed entry point, static OCI inspector | Built image, actual digest and source/archive hashes recorded; no candidate executed during build |
| M3-T02 | `staging.py`, `job.py`, guest preflight | Fixed input projection, actual read-only behavior and UID/GID observed in Kata |
| M3-T03 | `stage_inputs` immutable run ConfigMap with fixed keys, byte/request limits and input hashes | Pre-create tests pass; run-scoped live staging/API cleanup observed |
| M3-T04 | Fixed non-root security/resources/scratch Job and guest probes | UID/root/input/credential observations passed in Kata; **16 MiB scratch cap failed** |
| M3-T05 | Dedicated result file, separate bounded pipe diagnostics, small termination report | Canonical and distinct-array results collected through the non-root termination channel on Kata |
| M3-T06 | Shared `validation.py`, strict `report.py`, `collection.py` | Host origin/status contracts and live bounded result/negative cases pass |
| M3-T07 | Stable exit table, measured runner deadline, evidence-based external mapper | Live script/result/log/timeout/runtime-negative cases pass; hard scratch exhaustion remains blocked; OOM/infrastructure mappings only unit-tested |
| M3-T08 | `tests/unit/runner`, 32 named trusted live cases, render/execute harness | 39 host tests; 30 live checks passed, scratch-capacity check failed, dependent scratch-failure case unrun |

## Observed environment and blockers

Read-only SSH confirmed the existing approved RuntimeClass/handler and default-deny
namespace policy; their UIDs and overhead are in the design. The node has about
14 GiB free disk and no Job/Pod/input-ConfigMap leftovers at inspection. Calico
resource discovery confirmed the `projectcalico.org` API names used by the
harness. These checks are inventory, not new isolation evidence.

The cached base reference is
`docker.io/library/python@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b`.
Read-only `ctr content get` for config digest
`sha256:78976a69c067520ef8be34cde307ef9f6fea6dcefa50edb57039773d241ca0db`
showed Linux/amd64, `PYTHON_VERSION=3.12.16`, Debian trixie image history.
No base interpreter or candidate was executed on the node to inspect this.

Initial local checks found Python 3.13.15, Docker CLI 29.6.2 and buildx
0.35.0-desktop.2. Initially the Docker Linux engine pipe was absent. An attempt to start the
existing Docker Desktop with `docker desktop start --detach --timeout 30` failed:
`cannot find registry key "SOFTWARE\\Docker Inc.\\Docker Desktop"`.
Read-only node inventory found no docker/nerdctl/buildctl/buildah/podman executable.
Starting the existing Docker Desktop executable directly succeeded; Docker Desktop
4.83.0 / Linux engine 29.6.2 became available. No builder/registry was installed.

The corrected image was built on that local engine without any Dockerfile `RUN`
step or candidate execution, statically inspected as an OCI archive, copied to a
unique staging directory and imported into the existing node image cache:

`docker.io/kataai/runner@sha256:3fe4d6049f25c44d3b126f6b9de7462dfb019d3164bada7e775921a1b13abba8`

See [release metadata](../../tests/infrastructure/m3/evidence/2026-11-11/release.json).
Archive SHA-256: `da773c8d9e8ea387e6df9545bee592ee493d8f2c3fdf4a6f257f25c3925958ed`.
The release record's false execution/acceptance flags describe the build stage;
subsequent live observations are recorded separately.

The initial image `19bd54...` failed startup because COPY mode 0444 also removed
directory traversal. Static layer inspection found this, COPY was corrected to
0555, and regression tests now reject non-traversable directories. That initial
artifact is not the released runner. The first preflight also stopped before
creation because it over-scoped unrelated namespaced Calico policies; the fix
checks global and kata-lab policies while retaining snapshots of policies elsewhere.

## Checks performed

The executable command is:

```powershell
python -B -m unittest discover -s tests/unit/runner -v
```

39 tests passed on Windows Python 3.13.15. These are pure contract tests, synthetic
OCI inspections and mocked supervisor control-flow tests. They execute neither candidate fixtures nor the Linux runner entry
point. The harness's `--help` command and PowerShell build-script parser also
passed. Trusted Python source syntax was checked without parsing/executing fixture
programs. These checks do not replace the separate image/Kata observations.

No M1 test assets/evidence, RBAC, Kubernetes/containerd/Kata/Calico configurations
were changed. M3 created only run-scoped Jobs/ConfigMaps and added runner image
cache entries; only trusted fixtures executed inside Kata. The initial work made
no commits or pushes; the user subsequently authorized commit `f7f8d06` and the
read-only [scratch investigation](M3_SCRATCH_INVESTIGATION.md). Nothing was pushed.

## Live observations and blocker

Canonical sales and a distinct totals array passed the generic result channel.
The [live case records](../../tests/infrastructure/m3/evidence/2026-11-11/live-results.json)
contain expected/observed codes, Job/Pod UIDs, image/runtime identity, native
termination reports, retained diagnostic byte counts, fixture hashes and API
cleanup results. All 31 attempted final-image cases reached API cleanup, including
the failed scratch probe. The 30 passing checks include result validation,
syntax/runtime failure, stdout/stderr floods, 30-second measured script timeout,
symlink/FIFO rejection, status spoofing and absent RuntimeClass rejection with no
Pod creation. This count includes the separate read-only scratch-layout diagnostic;
it does not turn that diagnostic into a passing storage-capacity acceptance test.

The network fixture retrieved valid JSON while TCP to the API Service, node API,
node kubelet, metadata, public internet, DNS Service and rechecked CoreDNS peer,
plus UDP DNS, all failed. The API/DNS addresses and healthy controlled peer were
reinspected before execution. This covers selected destinations, not all M6 paths.

Security fixture `m3-security-20261111-1046` returned UID/GID 10001, guest kernel
6.18.56, actual denied input/runner writes, read-only root, writable scratch and
absent ServiceAccount/known credential observations. A live read-only snapshot at
10:43:22Z linked Pod UID `c44aec53-fef1-41a4-8880-30397d13a24f` and sandbox
`ce3eaaa1122da3e4cbb7846c0079fa9cae2017c775c19a902c7bfd05a41d30ba` to Kata
shim PID 67713 and child QEMU PID 67736, `accel=kvm`. By 10:43:51Z both PIDs,
the exact Kata/kubelet directories and sandbox record were absent. See the
[node observation record](../../tests/infrastructure/m3/evidence/2026-11-11/node-security.json).
Other cases retain Pod/runtime/image/status evidence; this is not a claim that
each short test had an independently captured live QEMU process.

**Scratch acceptance failed:** trusted case `m3-scratch-20261111-1048` wrote its
entire bounded 20 MiB probe without ENOSPC despite the Job's memory-backed
`emptyDir.sizeLimit: 16Mi`. It removed its file, raised an assertion and correctly
reported `SCRIPT_FAILED`; API cleanup passed. The original test remains failing.
The separate unhandled-scratch-exhaustion case is pending a working capacity cap.
No resource limit was raised and no privilege or policy was relaxed to pass it.
The read-only `scratch-layout` follow-up reported a guest filesystem capacity of
**100,691,968 bytes**, with `/tmp` mountinfo `tmpfs tmpfs rw` and no size option.
At 10:56:58Z the corresponding node mount for Pod
`5d52cafa-dc92-4e4b-9e05-b9a5abbfe452` had `size=16384k`.
This establishes a host/guest mount-capacity mismatch; it does not establish which
specific runtime implementation line causes it.

Follow-up source inspection has now identified the size-propagation omission at
the installed shim's reported revision: it creates a guest tmpfs storage request
with group metadata but no size limit. See the pinned source trace and evidence
limits in [M3 scratch investigation](M3_SCRATCH_INVESTIGATION.md). No fix was deployed.

This is consistent with the upstream discussion of [memory-backed emptyDir size
limits](https://github.com/kata-containers/kata-containers/issues/10897), but that
discussion alone does not diagnose this installed Rust runtime. Read-only config
inspection found `shared_fs = "virtio-fs"`, `emptydir_mode = "shared-fs"`,
`sandbox_cgroup_only = true`; permitted annotations cover hypervisor memory/vCPU/
kernel fields, not a demonstrated per-volume capacity override. Do not infer that
switching to a block/disk emptyDir fixes it: upstream [storage limitations](https://github.com/kata-containers/kata-containers/blob/main/docs/Limitations.md)
also require review. Any runtime/infrastructure correction requires the user's
explicit approval. Under that historical contract M3 could not be accepted with this failed scratch boundary. The current policy excludes exact guest quota enforcement.

## Cleanup and evidence scope

Final read-only inventory at 11:00:21Z found only `kube-root-ca.crt` among namespace
Jobs/Pods/ConfigMaps, zero Kata sandbox records, zero Kata shim/QEMU processes,
and the original twelve system runc sandboxes untouched. Exact security-run PIDs
and Kata/kubelet directories, plus final network/scratch-layout Pod directories,
were checked absent. Both task-created remote OCI archive files and their empty
staging directory were inspected and removed; local OCI archives remain under
ignored `.m3-runs/`. Runner image cache entries are retained, including the retired
initial image; no runtime-managed files were manually removed. See
[final inventory](../../tests/infrastructure/m3/evidence/2026-11-11/final-inventory.json).
Only the security run has separately captured live shim/QEMU/KVM correlation;
short cases have API/runtime/image evidence and the final aggregate absence check.
No per-case VM boot time or precise cleanup latency is claimed.

## Historical remaining acceptance at 0.1.0

The following original follow-ups describe the earlier quota contract. The
2026-11-15 policy above supersedes the quota-fix/rerun gate; no custom runtime
correction is required. Current 0.1.1 evidence is separate.

- Resolve the failed scratch-capacity boundary under a separately approved design;
  preserve the current failure and rerun both scratch cases after a real fix.
- Preserve and review the [trusted Kata evidence](../../tests/infrastructure/m3/evidence/2026-11-11/README.md).
  Extend per-case node correlation if the team's review requires it; API declarations
  alone do not prove every security property.
- Review same-UID guest tampering/log bypass/process escape limits before M6/M8
  permit untrusted code. M3 is not a Python security sandbox or certification.
- Coordinate this approved runner-side contract with the backend teammate's M2/M4
  interfaces; application state, API envelopes and durable lifecycle remain out
  of this change.
