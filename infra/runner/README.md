# Fixed Python runner 0.1.1

Contract: [approved M3 design revision 1](../../docs/milestone-3-design.md).
Implementation status and evidence: [M3 acceptance record](../../docs/infrastructure/M3_ACCEPTANCE.md).
This runner is **trusted-fixtures-only** until M6 isolation and M8 validation pass.

The project uses the existing unmodified Kata runtime. The historical 20 MiB
write succeeded despite the configured 16 MiB sizeLimit; that failed quota test
and its evidence remain intact. Exact 16 MiB guest capacity is no longer a
release requirement. Treat the sizeLimit as configuration, not a verified quota.

The 0.1.1 preflight requires a distinct writable tmpfs at `/tmp`, positive capacity
and available space, bounded valid mountinfo and a writable mount flag. Capacity
may differ from 16 MiB. Security tests must still observe actual guest writes.
Current release decision (pending candidate build and live acceptance):
[0.1.1 release record](../../RELEASE_0.1.1.md).

## Artifact and build

The Dockerfile uses the immutable Python base already observed in M1. Read-only
containerd config inspection on 2026-11-11 identified **Python 3.12.16, Linux/amd64,
Debian trixie** (image history), config digest
`sha256:78976a69c067520ef8be34cde307ef9f6fea6dcefa50edb57039773d241ca0db`.
No third-party runtime requirements, package downloads, shell startup, or build
`RUN` steps are added. The base includes its own Python packaging tools; there is
no supported package-install operation in the runner. A read-only root and denied
guest networking are required independently of this image.

From the repository root, with a working Docker/BuildKit OCI exporter:

```powershell
./infra/runner/build.ps1 -Repository '<approved-repository>/kataai-runner:0.1.1'
```

The script outputs an OCI archive, BuildKit metadata and `release.json` in a unique
`.m3-runs/build-*` directory. The release record includes version, real manifest
digest, archive SHA-256, source file hashes (covering uncommitted code), source
revision and dirty worktree status, base, platform and builder. `scratch.py` and
the host-side runner modules are included. Hashes are captured before build and
checked afterward; the statically inspected manifest must match BuildKit's
digest. `inspection.json` preserves packaged-source hashes. It never launches
the runner. Review and
preserve this record with acceptance evidence. Do not invent a runner digest from
the base digest or image configuration ID. Rebuild after source changes; repeat
builds can be compared by archive/manifest hashes, but bitwise equality is not
claimed. Do not publish a mutable tag as the execution contract.

Distribute the OCI archive through an approved image registry or a separately
approved node import. Record its exact digest and verify containerd resolves the
chosen `repository@sha256:digest` before submission. The Dockerfile and build
script do not install a registry, modify runtime configuration or copy credentials.
The historical 0.1.0 artifact (not this 0.1.1 candidate) reference is
`docker.io/kataai/runner@sha256:3fe4d6049f25c44d3b126f6b9de7462dfb019d3164bada7e775921a1b13abba8`.
The [release record](../../tests/infrastructure/m3/evidence/2026-11-11/release.json)
captures its source and archive hashes. It was imported into the existing node
image cache for trusted tests; no registry service was deployed.

## M4 integration

All modules are standard-library-only and safe to import on the application host
except `entrypoint.py`, which is the fixed image entry point. Never call
`supervisor.main()` or `run_child()` on the application host. The supervisor has
Linux UID/mount preconditions, but those checks do not prove a Kata VM: placement
is guaranteed by trusted Job construction plus runtime evidence, not a Python flag.

1. Authorize one dataset and script outside the runner. Read input bytes with
   upload limits upstream; `stage_inputs(run_id, script_bytes, csv_bytes)` validates
   the 32 KiB / 512 KiB / 768 KiB input/request caps before any API mutation and
   returns an immutable ConfigMap dictionary. No arbitrary file keys or paths.
2. Persist dispatch intent and deterministic run ID in M4/M5's local store.
   `make_job(run_id, immutable_runner_image)` returns the fixed server-owned Job
   selecting namespace `kata-lab` and RuntimeClass `kata-qemu-runtime-rs`. Caller
   input cannot override infrastructure. Do not remove the runtime field or retry
   on another runtime. Preflight runtime and effective policies; leave controls
   unchanged on failure. Preserve ConfigMap/Job UIDs from API creation.
3. Mount only `/inputs/script.py` and `/inputs/data.csv` read-only (0444).
   Candidate writes exactly one UTF-8 JSON object/array to `/tmp/result.json`.
   No task-specific field names are required. All raw bytes, including whitespace,
   count toward 2048 bytes. Root container depth is 1, max depth 16, max entries
   128 per collection / 256 total. Object member counts and array lengths count;
   keys are validated strings, not separate collection entries. Nested null and
   scalars are allowed. Duplicate keys, nonstandard/nonfinite numbers, unpaired
   surrogates and multiple JSON values are rejected. Leading/trailing ordinary
   JSON whitespace is allowed; UTF-8 BOM is rejected.
4. Fixed command: `python3 -I -B /opt/kataai/runner.py`. Root-owned trusted modules
   are separate from projected candidate files. Supervisor spawns Python directly
   without a shell; `-I` isolates Python startup/import environment, `-B` avoids
   bytecode writes. Neither isolates hostile code from the guest OS or supervisor.
5. Candidate stdout/stderr are diagnostic pipes, each retaining at most 8192
   bytes. More than 16384 observed bytes combined terminates the child. A single
   stream may be truncated at its retention cap even before the combined limit.
   Runner emits two bounded base64 JSON diagnostic records to container logs;
   nothing from those logs is interpreted as a result. M4 must cap log retrieval
   and label retained diagnostics as possibly truncated. Direct hostile writes
   bypassing the pipes remain an M6 review item.
6. Runner validates the file and writes at most 3072 bytes to
   `/tmp/runner-termination.json`. Kubernetes reads it using
   `terminationMessagePolicy: File`; no fallback to logs. Writes are in place
   because kubelet may bind-mount the file. Kubelet's documented 4096-byte cap is
   not the application result cap. Non-root termination writes and retrieval have
   now passed the canonical and security fixtures on the actual Kata stack.
7. Record the expected Job/Pod UID and use
   `collect_result(pod_snapshot, ExpectedRun(...))`. It checks owner, namespace,
   run label, Pod UID, runtime, fixed command/image/container, no restart, terminal
   phase, exit/report consistency and validated report contents. Runtime `imageID`
   is recorded, not assumed equal to a multiarch manifest digest. M4 must verify
   its image provenance against the released runner artifact. API responses must
   be bounded upstream; do not feed arbitrary unbounded Pod/log content here.
8. `external_failure(job, pod, events)` provides evidence-based deadline/OOM/image
   failure/runtime classification for already associated snapshots. Callers must
   bind events to recorded UIDs and prefer authoritative Kubernetes failure
   evidence. This helper is not a watch/reconciliation loop. Exit 137 alone is not
   OOM, and nonzero script exit is not timeout. Unknown causes stay unknown.
9. Persist one server-owned outcome; then request exact-UID cleanup of the Job,
   dependent Pods and input ConfigMap. Confirm API absence and guest teardown.
   Cancellation/restart recovery, durable state, retention and orphan detection
   belong to M4/M5. No Kubernetes SDK, FastAPI, database or long-lived service is
   introduced by M3.

The report schema is `protocol`, `run_id`, `pod_uid`, `code`,
`script_exit_code`, and `result` only for `OK`. The protocol identifier is
`kataai.runner.v1`. Outcome and result are separate dictionary members. A result
containing `status: success` cannot override child failure or Kubernetes exit.
The shared guest UID means a malicious script can tamper with guest-writable
reports or processes: this is not authenticated execution attestation. M4 must
never accept guest status without independent association and termination checks.

Stable runner codes/exits are in `contract.EXITS` and the approved design error
table. `RESULT_*` requires child exit 0; syntax/runtime failure is `SCRIPT_FAILED`
with its actual child exit/signal. Missing/empty/invalid/oversized/deep/type-invalid
outputs have distinct codes. `RUNNER_INTERNAL` covers unexpected supervisor faults.
Abrupt death, full scratch or failed termination-file writes may leave no report;
the collector fails closed. Resource and infrastructure causes require external
evidence. Scratch ENOSPC escaping the script is normally `SCRIPT_FAILED`.

## Required workload controls

UID/GID 10001; read-only root and inputs; fsGroup 10001; memory emptyDir with
configured `sizeLimit: 16Mi` (not a guaranteed guest capacity)
at `/tmp`; no escalation, all capabilities dropped, RuntimeDefault seccomp;
token automount and service-link env disabled; no host mounts, Secrets, init or
sidecar containers. One Job completion, no retry, restart Never, 30 s measured
script budget and 120 s Job deadline. Requests/limits are the approved M1-derived
values in `job.py`; RuntimeClass overhead is additional. Existing network denial
is required; image pulls happen at the node, not via guest networking.

Manifest declarations alone do not verify enforcement. See the
[trusted Kata test runbook](../../tests/infrastructure/m3/README.md) for actual
observation requirements and the host-only test command.
