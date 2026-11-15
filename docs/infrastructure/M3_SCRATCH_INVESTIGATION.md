# M3 scratch-capacity investigation

Date: 2026-11-11 (Asia/Bangkok)

Status: **Cause identified in the installed shim's source revision; no fix deployed.**

2026-11-15 follow-up: a [specific paired shim/agent correction proposal](M3_SCRATCH_FIX_PROPOSAL.md)
is ready for review. It is not approved or deployed. Runner 0.1.1 preparation
preserves the fail-closed capacity guard; see [release hold](../../RELEASE_0.1.1.md).

The initial M3 implementation/evidence is committed as `f7f8d06`. M3 remains
incomplete because the guest scratch filesystem does not enforce the approved
16 MiB capacity. This investigation changed no infrastructure or runner code.

## Finding

The 20 MiB write was allowed because it went to a **different tmpfs inside the
Kata guest**, not the node's 16 MiB tmpfs. The runtime creates that guest filesystem
without forwarding a `size=` limit. The guest reported capacity of 100,691,968
bytes, comfortably larger than the 20,971,520-byte probe.

The YAML was applied: the corresponding node mount had `size=16384k`. The limit
was lost in the host-to-guest storage translation. Increasing the YAML limit,
changing the test expectation, or treating an ordinary Python failure as ENOSPC
would not resolve this.

## Evidence and confidence

| Evidence | Observation | What it establishes |
|---|---|---|
| Preserved failed scratch Pod | Memory-backed `emptyDir`, `sizeLimit: 16Mi`, approved Kata RuntimeClass and pinned runner image | The intended configuration was submitted |
| Trusted probe source and diagnostics | Unbuffered writes of 64 KiB until 20 MiB; no ENOSPC; assertion failure; file removed in finally | Actual successful writes, not merely a Python userspace buffer |
| Matching host/guest mount observation | Node tmpfs `size=16384k`; guest `/tmp` tmpfs has no explicit size option and reports 100,691,968 bytes | The guest is not using the host mount's capacity boundary |
| Installed shim `--version` | Rust shim 4.3.1, commit `03cf2ec06a5d302f23af811744f6bcea49988bfb` | Source inspection is pinned to the installed shim's reported build revision |
| Installed shim SHA-256 | `c9a43977c61ff649c8233efd9ce6cf28e0bf777523071e838b8ebc3362f57016` | Fingerprint of the inspected node binary |

The earlier raw observations remain in
[final inventory](../../tests/infrastructure/m3/evidence/2026-11-11/final-inventory.json),
[failed Pod](../../tests/infrastructure/m3/evidence/2026-11-11/scratch-failed-pod.json),
[diagnostics](../../tests/infrastructure/m3/evidence/2026-11-11/scratch-failed-diagnostics.jsonl)
and [live results](../../tests/infrastructure/m3/evidence/2026-11-11/live-results.json).
New read-only version/config observations are recorded in
[runtime investigation metadata](../../tests/infrastructure/m3/evidence/2026-11-11/scratch-runtime-investigation.json).

## Source-level explanation

All Kata links below use the installed shim's reported commit, rather than a
moving main branch or an assumed release tag.

1. The Kubernetes helper recognizes a bind mount sourced from a Kubernetes
   `emptyDir` whose host filesystem is tmpfs. It changes its mount type to Kata's
   ephemeral-volume type. That conversion does not carry the host filesystem's
   capacity into a new mount option.
   [k8s.rs, lines 19–80](https://github.com/kata-containers/kata-containers/blob/03cf2ec06a5d302f23af811744f6bcea49988bfb/src/libs/kata-sys-util/src/k8s.rs#L19-L80)

2. Volume dispatch routes an ephemeral mount to `EphemeralVolume::new` before
   the block-emptyDir and shared-filesystem alternatives. Therefore the configured
   `shared_fs = "virtio-fs"` and `emptydir_mode = "shared-fs"` do not mean that this
   memory-backed emptyDir is simply shared as the node tmpfs.
   [volume/mod.rs, lines 108–123](https://github.com/kata-containers/kata-containers/blob/03cf2ec06a5d302f23af811744f6bcea49988bfb/src/runtime-rs/crates/resource/src/volume/mod.rs#L108-L123)

3. `EphemeralVolume::new` stats the source's ownership and supplies only an
   optional `fsgid` option. It constructs an agent Storage request for a new
   guest tmpfs and bind-mounts that guest path into the container. It does not
   read the host tmpfs's size or add `size=16777216` to the storage options.
   Retaining the container-side bind options does not preserve the capacity of
   the original host filesystem.
   [ephemeral_volume.rs, lines 37–77](https://github.com/kata-containers/kata-containers/blob/03cf2ec06a5d302f23af811744f6bcea49988bfb/src/runtime-rs/crates/resource/src/volume/ephemeral_volume.rs#L37-L77)

4. Agent code at the same project revision parses the ephemeral options, clears
   them for the initial mount, then handles the group ownership separately.
   Its ordinary initial tmpfs path is not a general pass-through for size options.
   Later remount RPC code exists in this file; that does not demonstrate a
   supported Kubernetes sizeLimit-to-remount path in the installed setup.
   [ephemeral_handler.rs, lines 49–83](https://github.com/kata-containers/kata-containers/blob/03cf2ec06a5d302f23af811744f6bcea49988bfb/src/agent/src/storage/ephemeral_handler.rs#L49-L83)

5. With no size/block-count option, Linux tmpfs defaults to half physical RAM.
   This explains why the capacity can follow guest memory rather than the
   requested 16 MiB. The exact guest memory available when the mount was created
   was not sampled, so deriving the precise 100,691,968-byte value from a memory
   total remains an inference; that capacity itself was directly measured.
   [Linux tmpfs documentation](https://docs.kernel.org/filesystems/tmpfs.html)

The installed guest-agent binary was not independently fingerprinted during this
read-only follow-up. The runtime's omission of the size is established at its
reported source revision; the agent source describes the matching project
revision, and the actual guest mount confirms that no effective 16 MiB bound
arrived. No live debug configuration was enabled to capture the agent RPC.

The upstream [memory emptyDir issue #10897](https://github.com/kata-containers/kata-containers/issues/10897)
reports the same class of limitation. It is supporting context, not the only
basis for this diagnosis.

## Why the other controls did not stop 20 MiB

Non-root UID and read-only root/inputs still permit writes to the deliberately
writable `/tmp` mount. They do not impose a volume quota.

The 64 MiB `ephemeral-storage` limit is not a substitute for a 16 MiB tmpfs cap:
Kubernetes accounts memory-backed emptyDir as memory rather than local ephemeral
storage. Even successful enforcement of the configured 256 MiB memory limit would
not by itself enforce a 16 MiB filesystem budget. This probe does not certify
memory-limit enforcement or every guest accounting path.
[Kubernetes resource accounting](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/#how-kubernetes-applies-resource-requests-and-limits)

The runner correctly distinguished the fixture's assertion failure as
`SCRIPT_FAILED`. It must not relabel that as resource exhaustion: the expected
ENOSPC event did not happen.

## Remediation implications — proposals, not approved changes

The enforcement point must bound the **guest filesystem actually receiving the
writes**, before candidate execution, while preserving non-root execution, dropped
capabilities, read-only inputs/root, no credentials and the approved Kata runtime.

- A runtime/agent correction must propagate and honor a trusted capacity value
  for this memory-backed volume. Editing only a YAML size or blindly adding an
  option to one layer is insufficient evidence. The initial agent option handling
  must also be reviewed. No runtime binary patch, upgrade or configuration change
  is authorized or deployed by this investigation.
- A genuinely capacity-bounded volume is another candidate, but must be proven
  compatible with this Kata stack. Switching to disk/block emptyDir is not an
  automatic fix: at this same revision the block path sizes its sparse backing
  file from the containing filesystem's capacity, not the requested sizeLimit.
  [block_emptydir_volume.rs, lines 85–91 and 268–274](https://github.com/kata-containers/kata-containers/blob/03cf2ec06a5d302f23af811744f6bcea49988bfb/src/runtime-rs/crates/resource/src/volume/block_emptydir_volume.rs#L85-L91)
- A per-file `RLIMIT_FSIZE` or periodic directory-size polling is not equivalent
  to a hard total-volume quota; neither should replace the failed acceptance
  test. Do not add root/CAP_SYS_ADMIN to the runner merely to remount tmpfs.

Before accepting any proposed fix, observe the guest mount's effective capacity,
exercise cumulative writes across multiple files, confirm ENOSPC at the approved
bound and verify result/error collection plus teardown. Preserve the original
20 MiB failing probe. Numeric contract changes or infrastructure/security changes
still require separate explicit approval.

No additional workloads, resource floods or candidate executions were needed for
this follow-up: it used preserved measurements, read-only node inventory and
static inspection of primary upstream source. No new test result is claimed.
