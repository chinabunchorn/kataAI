# M3 trusted Kata tests

**Historical live tests include a failed scratch-capacity test.** See the
[acceptance record](../../../docs/infrastructure/M3_ACCEPTANCE.md) for exact
passed, failed and untested cases and the revised 2026-11-15 policy. Runner 0.1.1
still requires its own build and actual Kata acceptance. Keep M1 assets and evidence intact. No candidate
fixture may run on Windows, the Kubernetes node, local Docker or ordinary runc.
The host harness reads fixture programs as bytes only. It accepts named
team-controlled cases from `catalog.py`, never an arbitrary script path.

## Host-only checks

Run from the repository root:

```powershell
python -B -m unittest discover -s tests/unit/runner -v
python -B tests/infrastructure/m3/run.py --help
```

These execute trusted pure validation/staging/collection code and mock every
supervisor launch. They do not import/execute fixture programs. No cluster or
image is needed. A successful unit run does not prove Linux/Kata enforcement.

## Build and prerequisites

Build and preserve an immutable runner artifact using
[`infra/runner/build.ps1`](../../../infra/runner/build.ps1) on a working approved
builder. Review `release.json` and distribute the image through an approved
registry/import mechanism; no deployment proceeds with a placeholder digest.
Ensure that the Kata node resolves the exact released image reference.

Use the existing approved SSH tunnel/private Kubernetes API route with TLS
verification and an explicit trusted-operator kubeconfig/context. No kubeconfig
or credentials are staged into the guest. Do not reuse M1's deleted temporary
identity or silently grant RBAC. Persistent application credentials/admission
remain later milestones. The harness's read-only preflight needs RuntimeClass,
namespace and Calico policy inspection; its mutations need create/get/delete
Jobs and ConfigMaps in `kata-lab`, get/list Pods, get logs and Job events. It never
requests Secrets, Pod exec, RBAC changes or infrastructure installation.

Check namespace, runtime/handler, available resources, node image resolution and
all effective policy layers. The harness requires the existing default-deny and
no global or kata-lab Calico policy objects. Namespaced policies elsewhere are
recorded but do not select kata-lab subjects. It stops on unavailable inspection or policy
changes; do not weaken policy to make a test pass. Other policy/admission systems
still require operator review. For `network`, reinspect its M1-recorded node, DNS
and controlled-peer addresses before running; a stale/unavailable target is weak
evidence. Record target identity and health separately.

## Render a reviewable case

```powershell
$image = '<approved-repository>/kataai-runner@sha256:<actual-built-manifest-digest>'
python -B tests/infrastructure/m3/run.py --case sales --run-id m3-sales-unique --image $image
```

The tool creates `.m3-runs/<run-id>/inputs.json`, `job.json` and `test.json`.
Nothing is submitted. Run IDs are DNS labels up to 40 characters. Inspect these
files and image provenance. Existing evidence directories/resources cause failure
instead of overwriting. The `missing-runtime` case alone substitutes a unique
nonexistent RuntimeClass; it never selects runc or removes the working class.

To execute the reviewed case, use a new unique run ID (rendered directories are
not reused):

```powershell
python -B tests/infrastructure/m3/run.py --case sales --run-id m3-sales-live-unique --image $image --execute --kubeconfig '<existing-operator-kubeconfig>' --context '<approved-remote-context>'
```

An existing operator SSH alias can alternatively drive remote kubectl without
copying kubeconfig/tokens or creating RBAC. Use `--ssh-host katavm` instead of
`--kubeconfig` and `--context`. This is test-only; M4 still communicates directly
with Kubernetes using its approved API credentials/transport.

Run one case at a time. `--execute` opts into creating that case's immutable
ConfigMap and fixed Kata Job, bounded observation, output validation and exact-UID
cleanup. It does not opt into infrastructure/RBAC reconfiguration. The local
operator harness uses kubectl against the secure API; future M4 supplies its own
direct Kubernetes API client and lifecycle logic.

## Case matrix

| Cases | Expected observation |
|---|---|
| `sales`, `totals` | Exact canonical object / distinct month-total array, `OK` |
| `security` | UID/GID 10001, denied script/CSV/runner writes, root read-only, absent token and known credential paths/env, scratch writable; 10 s correlation window |
| `network` | Bounded TCP and UDP probes to M1-recorded destinations fail while valid result collection works |
| `scratch-layout` | Record actual statvfs/mountinfo; positive writable tmpfs capacity may differ from 16 MiB; does not certify a quota |
| `invalid-json`, `multiple`, `duplicate-key`, `nan` | `RESULT_JSON` |
| `empty`, `blank`, `missing` | `RESULT_EMPTY`, `RESULT_EMPTY`, `RESULT_MISSING` |
| `oversized`, `deep`, `collection`, `total-items` | `RESULT_LIMIT` |
| `scalar`, `null`, `infinite-number`, `surrogate`, `result-symlink`, `result-fifo` | `RESULT_SHAPE` |
| `utf8` | `RESULT_ENCODING` |
| `syntax`, `runtime`, `status-spoof` | `SCRIPT_FAILED`; arbitrary result status cannot override failure |
| `timeout` | `RUN_TIMEOUT` after supervisor wall budget; no retries |
| `diagnostics`, `stderr-diagnostics` | `DIAGNOSTIC_LIMIT`, bounded retained log records |
| `missing-runtime` | Explicit runtime-not-found Job event, zero Pods; no fallback |

The original `scratch`, `scratch-failure` and proposed `scratch-multifile` probes
and original expectations are retained in `LEGACY_SCRATCH_CASES` and fixture
files, excluded from CLI choices and release acceptance. Their quota assumptions
do not apply to the unmodified runtime. Historical failed/unrun outcomes remain
unchanged. Do not execute new model-generated Python. The existing `security`
fixture observes actual scratch writes; `scratch-layout` records capacity.

Security probes observe specific paths/env plus fixed manifest controls. They do
not prove absence of every possible secret or certify M6 isolation. Network probes
have the same bounded-scope limitation. The harness checks the exact runner
termination report and Kubernetes status independently; no log line is a result.

## VM evidence and cleanup

The harness saves created UIDs immediately, terminal Job/Pod snapshots, bounded
diagnostics, policy/runtime snapshots, validated outcome or bounded failure and
cleanup observations. API checks alone do not establish a real VM or its teardown.
For `security`, collect node-side correlation during its 10 s hold in a separate
read-only SSH session, following M1 infrastructure sections 13.6 and 16.5:

```bash
kubectl -n kata-lab get pods -l kataai-m3-run=YOUR_RUN_ID -o json
sudo -n ctr -n k8s.io sandboxes ls
ps -eo pid,ppid,args | grep -E '[q]emu-system|[c]ontainerd-shim-kata'
```

Inspect the exact sandbox with `ctr -n k8s.io sandboxes info SANDBOX_ID`, correlate
its Pod UID/namespace and runtime, then record the linked shim/QEMU PIDs, start
time, guest kernel result and `accel=kvm` configuration. Preserve minimal redacted
evidence; never capture credentials/Secret objects or unrelated sensitive logs.
After harness cleanup, verify those exact PIDs, sandbox VM, Kata run directory and
kubelet Pod directory are absent. Record transient stopped metadata separately;
never remove runtime-managed files manually. See M1's retained evidence for
examples of the distinction between metadata residue and a live VM.

Cleanup deletes only resources whose create-response UIDs were recorded, using
API UID preconditions and foreground Job deletion. It uses a 60 s polling budget
plus separately bounded in-flight API calls, and explicitly records
`vm_teardown_verified: false` until independent node
evidence is attached. A lost create response may leave an object not in inventory:
the failure record identifies this uncertainty. Inspect the exact planned name,
UID, labels and staged input hashes before operator cleanup; do not rerun blindly
or delete by broad selectors. Durable uncertain-create reconciliation belongs to
M4/M5, not this small harness.

Promote reviewed evidence from ignored `.m3-runs/` to a deliberate evidence location
only after checking it for sensitive data. Do not mark M3 complete until image
release, all required actual-Kata cases and observed VM teardown have passed.

Consolidate local records without candidate execution, using a new output file:

```powershell
python -B tests/infrastructure/m3/summarize.py --image $image --output '<new-evidence-file>.json'
```

The [2026-11-11 evidence](evidence/2026-11-11/README.md) records 30 passing checks,
one failed capacity check and one dependent unrun case. Keep that distinction.
