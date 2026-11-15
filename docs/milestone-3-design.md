# M3 approved runner design

Status: **Approved — runner contract revision 1, with 2026-11-15 scratch policy amendment**

Revision: 1, inspected 2026-11-11 (Asia/Bangkok)

Release maintenance note (2026-11-15): the artifact patch candidate is now 0.1.1.
The artifact is now prepared as 0.1.1 with protocol v1. The user chose the
existing unmodified Kata runtime: exact 16 MiB guest scratch enforcement and
quota-exhaustion tests are no longer release requirements. Require writable
guest tmpfs with positive capacity/available space and actual write observations.
The configured `sizeLimit: 16Mi` remains, without a verified guest quota. Other
numeric limits and workload security controls remain required. See
[release preparation](../RELEASE_0.1.1.md) and the amended
[acceptance policy](infrastructure/M3_ACCEPTANCE.md). No custom runtime installation
is planned or authorized.

Approval evidence: user replied “Yes I approve” to revision 1 in this chat on
2026-11-11. Historical scratch-capacity failure remains recorded; current candidate
acceptance requires a real 0.1.1 build and evidence under the amended policy.

Implementation/evidence tracking: [M3 acceptance record](infrastructure/M3_ACCEPTANCE.md).
Subsequent read-only cached image inspection identified Python 3.12.16 and Debian
trixie for the approved base digest; no version was inferred from a mutable tag.
Actual Kata tests later verified the staging/result/non-root contracts but found
the configured 16 MiB memory emptyDir did not enforce that guest capacity. This
historical failure is preserved in the acceptance record. The user explicitly
amended its release requirement on 2026-11-15; no runtime/security reconfiguration
was performed.

## Authority and historical design baseline (2026-11-11)

The [master roadmap](../Sandboxed_AI_Inference_Master_Roadmap_v0.3.md), sections
0, M2, M3, M4 and decision register D07–D11, controls this work. The
[infrastructure record](infrastructure/INFRASTRUCTURE.md), especially sections
11–13 and 16.5, supplies M1 evidence. Infrastructure document decision IDs differ
from roadmap IDs; IDs below refer to the roadmap.

At initial design inspection, the repository contained the roadmap, infrastructure record, README,
and eight M1 assets. There was no M2 application skeleton, approved JSON contract,
runner image, M3 implementation, or CI configuration. All M1 assets were inspected
and preserved. Current runner and executor implementations are in `infra/runner`
and `infra/executor`; see their READMEs and the release record for current evidence.
M2 application contracts must be coordinated with the backend teammate;
this proposal defines only the runner-side interface, not an HTTP/API envelope.

M1 already demonstrates a tiny run-scoped read-only ConfigMap, UID/GID 10001,
canonical JSON in logs, denied input writes, absent ServiceAccount token,
network-denied trusted execution, Windows API collection, and correlated VM
teardown. These observations do not establish generic result limits or M3 acceptance.

Read-only SSH inspection in this session confirmed the RuntimeClass
`kata-qemu-runtime-rs` with handler of the same name, Kata annotation 4.3.1,
UID `97380e5b-2565-41fa-851e-82cee3dfc70f`, and Pod overhead 250m CPU / 320Mi
memory. Namespace `kata-lab` has one Kubernetes NetworkPolicy, `default-deny`,
UID `4da3eb78-8193-4f2b-85c6-3f52df396063`, selecting all Pods with no ingress
or egress allow rules. This session did not repeat packet probes or inspect all
Calico policy layers. No cluster resource was changed and no script was executed.

At that inspection, local Python 3.13, Docker, kubectl and SSH executables existed. `docker version`
reported client 29.6.2 but failed to connect to the Linux engine named pipe.
Read-only SSH worked with network sandbox escalation. No image build, registry
push, or M3 Kata test had run at design time. Subsequent builds, cache import and
actual Kata results are tracked in the release and acceptance records; these
historical prerequisites do not describe current release status.

## Approved decisions

The user approved the numbers and protocols in this section as M3 runner
defaults. Approval applies to revision 1 as a runner contract; later material
changes require an explicit revision.

| Decision | Approved selection | Reason / cost |
|---|---|---|
| D07 environment | Linux/amd64 Python 3.12 slim, starting from M1's observed immutable base `docker.io/library/python@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b`; no third-party runtime dependencies | Reuses verified lineage; CSV/JSON fixtures need only stdlib. Exact Python patch and base OS must be extracted from image metadata/build inspection before release; no guessed patch version |
| D07 artifact | Runner version `0.1.1`, digest-pinned base and deployed runner; fixed files only in build context, no dynamic pip/apt installation | Record source revision, base digest, actual Python version, build command/tool version, platform and output digest. Fixed inputs aid reproducibility; do not promise bit-identical builds without measuring |
| D09 staging | One immutable ConfigMap per run; exactly `script.py` and `data.csv`, explicitly projected into `/inputs`, mode 0444, read-only volume | Reuses M1; bounded MVP only, unsuitable for large or confidential datasets without separate storage/access review |
| D08 input caps | Script 32 KiB, CSV 512 KiB, serialized ConfigMap request 768 KiB; strict UTF-8, nonempty, no NUL; no arbitrary additional keys/paths | Leaves space below Kubernetes' 1 MiB ConfigMap data limit; validate bytes and serialized request before any creation. CSV headers remain task-specific; no sales schema imposed |
| D09 result | Script writes `/tmp/result.json`; supervisor validates and emits a versioned report to `/tmp/runner-termination.json`; Kubernetes `terminationMessagePath` points there, policy `File` | Network independent; separates diagnostics from data; avoids parsing mixed log lines. Actual non-root termination-file behavior must pass a Kata feasibility test |
| D08 JSON | Top-level object or array; nested standard JSON values including null allowed; reject scalar/null roots, duplicate keys, NaN/Infinity, non-finite parsed numbers and unpaired Unicode surrogates | Supports sales object and independent array analysis while keeping a clear first contract. Scalar roots can be added only by approved revision |
| D08 output caps | Raw result 2048 bytes; container nesting depth 16 (root container is depth 1); at most 128 entries per collection and 256 entries summed over all collections | Intentionally small results to fit termination transport; raw byte bound includes whitespace. Count object members and array elements; empty containers still contribute to depth |
| D08 transport cap | Complete compact report at most 3072 UTF-8 bytes; fail closed if report cannot fit, never truncate JSON | Leaves headroom below the single-container 4096-byte termination-message cap. Bound both raw result and encoded envelope; encoding expansion may make an otherwise valid raw result too large |
| D11 diagnostics | Capture at most 8 KiB each stdout and stderr; combined observed bytes exceeding 16 KiB ends execution with `DIAGNOSTIC_LIMIT` | Bounded pipe reads and retention; diagnostics never interpreted as JSON results. Host log retrieval must also use byte caps and detect truncation |
| D11 time | Script wall deadline 30 s, Job active deadline 120 s, termination grace 5 s; one run at a time, no retries | Runner deadline starts at subprocess launch; Job deadline also bounds scheduling/startup. Full queue/request budgets remain M4 decisions |
| D11 resources | M1 requests 100m CPU / 128Mi memory / 16Mi ephemeral storage; limits 1 CPU / 256Mi / 64Mi; scratch memory-backed emptyDir with configured sizeLimit 16Mi | Exact guest capacity and ENOSPC at 16 MiB are not release requirements. Require writable guest tmpfs and record actual capacity; do not claim an enforced quota. RuntimeClass overhead is additional |
| Security configuration | UID/GID 10001, fsGroup 10001 if needed for scratch; read-only root and inputs, no escalation, capabilities ALL dropped, RuntimeDefault seccomp, token automount false, service links disabled | Reuses M1 controls; tmpfs and fsGroup are proposed workload changes requiring live validation. No hostPath, Secret, kubeconfig, extra dataset, network service or sidecar |

ConfigMaps are not secret storage. MVP staging receives only the server-authorized
script and CSV; authorization stays with M4. Inputs must not contain application
or Kubernetes credentials.

## Execution and collection interface

Required files are `/inputs/script.py` and `/inputs/data.csv`. Trusted runner
modules reside under `/opt/kataai/`, root-owned and immutable. The fixed entry
command will be `python3 -I -B /opt/kataai/runner.py`; it takes no caller-controlled
shell command or infrastructure arguments. The child uses the same interpreter
with `-I -B /inputs/script.py`, working directory `/tmp`, stdin disconnected,
minimal explicit environment and separately drained stdout/stderr pipes. No shell
is involved. Code syntax is checked only within the Kata runner, not on the host.

The runner checks fixed input presence, regular file targets (allowing Kubernetes'
expected projected-volume symlinks), size, UTF-8 and non-root identity before
launch. Kubernetes enforces read-only mounts; interpreter flags do not. The runner
checks required write-denial behavior and emits a precondition failure if unsafe.
Input hashes/ConfigMap UID are retained externally by the harness for association.

Use a subprocess rather than exec/eval in the supervisor to distinguish script
exit from runner validation and to enforce wall time and diagnostic limits.
Create a new process session; terminate the group on timeout/limit/child exit and
bound all pipe-drain waits. Do not wait forever for inherited pipes held by a
descendant. Process-group control is lifecycle hygiene, not containment of hostile
processes that deliberately escape their session. The Pod deadline remains the
outer boundary, and later isolation acceptance must test bypasses.

Only after successful child exit does the supervisor read the result: reject
non-regular files/symlinks, open without following symlinks, read at most cap + 1,
decode strictly, parse exactly one value, validate shape/depth/items and bounded
serialized report size. Trailing whitespace is allowed; a second value is not.
Check depth before recursive parsing to avoid relying on parser recursion limits.
Use the same pure validation module in the runner and future M4 collector.

The report has fixed keys: `protocol` (`kataai.runner.v1`), `run_id`, `pod_uid`,
`code`, `script_exit_code` (integer or null), and `result` (present only for OK).
Run identity is supplied by trusted Job construction, Pod UID through the Downward
API. Diagnostics remain outside this report. Arbitrary keys inside `result`, such
as `status`, have no execution meaning. Report parsing rejects unknown/duplicate
keys and inconsistent code/result/exit combinations.

The implemented collector receives expected namespace, Job UID, Pod UID, run ID and
container name from its own run record. It checks the exact Pod owner, labels,
RuntimeClass, image digest, container identity, no restart, terminal state and
exit code, then bounds and validates its termination report and result anew.
Zero exit without a valid matching OK report is failure. Wrong origin, absent or
truncated messages are failures. Never accept an arbitrary Pod selected only by
a guest-provided run ID. Do not retry collection through logs as a result fallback.

The script and supervisor share an OS identity: the report is **not an authenticated
attestation against malicious guest code**. A hostile script may tamper with
guest-writable report files, signal the supervisor or bypass captured log pipes.
Kata isolates the guest from the host; `-I` removes Python import/environment
influences and `-B` suppresses bytecode writes, neither creates a Python security
sandbox. M4 owns authoritative outcome metadata, with Kubernetes status taking
precedence. This design is approved-trusted-fixtures-only until M6/M8; stronger
within-guest separation, log abuse and process escape controls remain explicit
security review items before accepting untrusted code.

## Proposed error mapping

| Runner code / exit | Trigger |
|---|---|
| `OK` / 0 | Child exit 0 and exactly one valid result |
| `SCRIPT_FAILED` / 10 | Syntax error, runtime exception, or other nonzero child exit; preserve actual child code/signal separately |
| `RESULT_MISSING` / 11 | No result file |
| `RESULT_EMPTY` / 12 | Empty/whitespace-only result |
| `RESULT_ENCODING` / 13 | Invalid UTF-8 |
| `RESULT_JSON` / 14 | Malformed JSON, multiple values, duplicate keys or nonstandard constants |
| `RESULT_SHAPE` / 15 | Disallowed root or Unicode/numeric values |
| `RESULT_LIMIT` / 16 | Byte, depth, entry or encoded-report cap exceeded |
| `RUN_TIMEOUT` / 17 | Supervisor's measured child wall deadline exceeded |
| `DIAGNOSTIC_LIMIT` / 18 | Diagnostic cap exceeded |
| `INPUT_INVALID` / 19 | Input/precondition violation |
| `RUNNER_INTERNAL` / 20 | Supervisor fault or unexpected channel failure |

No report is guaranteed after OOM, signal, full scratch or abrupt guest loss.
M4 maps observed OOMKilled/eviction to `RESOURCE_LIMIT`, Job DeadlineExceeded to
`RUN_TIMEOUT`, missing runtime to `KATA_UNAVAILABLE`, and distinguishable scheduling,
image pull/API failures to infrastructure errors. A signal or exit 137 alone is
not proof of OOM; a nonzero exit alone is not proof of timeout. Scratch ENOSPC may
be an ordinary script failure unless the controlled fixture or Kubernetes evidence
establishes the resource cause. M4's public error envelope remains its own contract.

## Implementation and required proof

Implemented layout: `infra/runner/` for Dockerfile, manifest and small runner,
validation, staging and collection modules; `tests/unit/runner/` for pure tests;
`tests/infrastructure/m3/` for trusted fixtures, fixed Job/harness and evidence
instructions. Keep FastAPI/Kubernetes SDK dependencies out of the runner. Staging
and collection adapters operate on plain bytes/dictionaries; M4 supplies transport.

R1 (M3-T01): Build version 0.1.1 without candidate execution; record actual base
metadata and immutable resulting image digest. A release without a real digest
does not satisfy acceptance. Choose an approved build host and distribution path
first; do not install/reconfigure Docker, a registry or containerd implicitly.

R2 (M3-T02–04): Pure staging tests enforce exact keys and pre-create caps. Kata
fixtures observe UID/GID, actual denied writes to both inputs/root, scratch write
success and actual capacity (no exact-capacity/exhaustion gate), absent token, and absence of unexpected env/mount
credentials. Inspect manifests too; a file-path probe alone does not prove absence
of all credentials. Inspect policy without weakening it and repeat bounded network
probes in the actual guest. No runtime fallback is permitted.

R3 (M3-T05–06): Pure unit tests cover every byte/type/depth/item boundary, exact-one
semantics, invalid UTF-8, duplicate keys, escaped content and envelope expansion.
Collector contract tests use fake Pod dictionaries to reject wrong run/owner/UID,
runtime/image/exit mismatches, missing or truncated reports, and diagnostic spoofing.

R4 (M3-T07–08): Actual Kata tests execute canonical sales object and a distinct
trusted array analysis, malformed/empty/missing/oversize/deep/scalar/non-UTF-8/
multiple results, syntax error, exception, infinite loop, writable scratch and
diagnostic flood. Candidate scripts are never executed by host tests or local
Docker. Host tests run only trusted validation/staging/collection code, with no
candidate import/exec or subprocess execution.

R5 (M3/M4 handoff): The harness renders fixed resources, validates the approved
RuntimeClass and existing network policy, stages one fixture at a time and records
Job/Pod/ConfigMap UIDs, image digest, termination state/report and live sandbox/
QEMU correlation. A missing-RuntimeClass negative uses a unique nonexistent name
and must produce no executed container; it never removes the working RuntimeClass.
Capture guest correlation during a bounded trusted hold so short runs remain
observable. Recheck effective policy before each live suite.

R6 (cleanup boundary): Harness cleanup is limited to exact resources it created,
using recorded UIDs/preconditions, including partial setup failure. Preserve
evidence before deletion; verify API absence and observed guest teardown. M4/M5
own durable restart recovery, cancellation, retention and orphan reconciliation.
No broad namespace deletion, runtime-state deletion, or persistent RBAC changes.

Local unit tests must not require cluster access. Live tests are opt-in and require
the approved image, reachable cluster, existing authorized operator credentials
and a reviewable rendered inventory. Any additional RBAC/build infrastructure
change must be proposed concretely first. M1's old temporary identity is deleted;
its old approval is not reused. M3 is complete only after recorded real-Kata
acceptance, not after pure tests or manifest generation.

## Alternatives and primary references

Stdout-as-result was demonstrated by M1 but mixes naturally with diagnostics;
collecting a dedicated result file through exec/copy adds privileges and lifecycle
coupling. A file plus small termination report is proposed for this bounded MVP;
larger result support requires an approved new artifact channel.

Kubernetes documents [ConfigMap size and immutability](https://kubernetes.io/docs/concepts/configuration/configmap/),
[termination message truncation and log fallback](https://kubernetes.io/docs/tasks/debug/debug-application/determine-reason-pod-failure/),
and [emptyDir memory/storage behavior](https://kubernetes.io/docs/concepts/storage/volumes/#emptydir).
Python documents the actual behavior of [-I and -B](https://docs.python.org/3.12/using/cmdline.html).
These references inform the proposal; none proves this new protocol works on Kata.
