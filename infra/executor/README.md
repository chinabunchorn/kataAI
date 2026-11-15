# Backend Kata executor adapter

`KataExecutor` implements the five operations in the backend branch's
[`FutureExecutor` handoff](https://github.com/chinabunchorn/kataAI/blob/49f94011b0f824d45dc1bf012473b3af978f3b77/backend/app/executor_contract.py).
It stages inert Python/CSV, creates fixed Kata Jobs, validates the bounded
termination result, and tracks cancellation, uncertain submissions and cleanup.
It never runs candidate code locally. Imports start no processes or network calls.

The adapter lives alongside the existing shared `infra.runner` helpers. It loads
the backend's actual contract/decoder modules lazily from `app`; it does not copy
production backend types or change the fake worker. The backend branch must have
both `infra/runner` and `infra/executor` available on its Python import path. Run
from the repository root with `backend/` also on `PYTHONPATH`, or package both
namespaces in the application's deployment environment. Backend Python remains
3.12; host-only checks also run on this checkout's Python 3.13.

## Construction and backend responsibilities

```python
from infra.executor import KataExecutor, KubectlAPI, SQLiteRunStore

# All arguments are trusted application configuration, never tool-call fields.
executor = KataExecutor(
    KubectlAPI(kubeconfig_path, context_name),
    SQLiteRunStore(private_state_directory / "kata-runs.sqlite3"),
    image=approved_runner_digest,
    resolve_dataset=authorized_bounded_csv_reader,
    authorize=approved_execution_policy,
    verify_image=released_image_provenance_check,
    observe_teardown=trusted_node_observer,
)

# Persist request_id/run_id in PostgreSQL BEFORE calling submit.
# Build the backend ExecutorRequest with timeout_seconds=30.
ack = executor.submit(persisted_executor_request)
observation = executor.status(request_id, run_id)
# Only observation.state == RunState.COMPLETED has read_result bytes.
raw_json = executor.read_result(request_id, run_id)
# Persist the validated outcome/result in the backend before requesting cleanup.
ack = executor.cleanup(request_id, run_id)
# Repeated caller-scheduled reconciliation also retries pending cleanup.
observations = executor.reconcile()
```

The snippet names application callbacks intentionally: the adapter cannot infer
dataset ownership, approve generated code, attest an image or inspect a node from
a dataset UUID or guest report. Required callback contracts:

- `resolve_dataset(request, cap) -> bytes`: verify the request's authorization and
  the dataset's ACTIVE/READY state; resolve the server-owned storage key; open it
  safely under the private dataset root; read at most `cap + 1` bytes, rejecting
  oversized input. Return the exact bounded snapshot to execute. The adapter also
  validates input caps/encoding, hashes and durably stages exactly these bytes.
  It does not use CSV rows for model generation. No caller-selected filesystem
  path is accepted by the adapter. Preserve the backend's POSIX file protections.
- `authorize(request) -> True`: an explicit application execution gate, checked
  again on resumed submission. Until isolation acceptance, allow only approved,
  hand-written fixture hashes/datasets. Missing/false approval rejects dispatch.
  This callback must also check the configured runner release is approved for the
  intended mode; a manifest digest alone does not establish acceptance.
- `verify_image(image, container_status) -> True`: match runtime `imageID` and the
  pinned image against independently verified release metadata. Runtime config
  IDs need not equal multiarch manifest digests. Missing/unverified evidence
  prevents collection. Never trust a guest-provided image identifier.
- `observe_teardown(record) -> True | False | None`: independently verify recorded
  Pod UIDs, nodes, CRI/container identities and previously correlated Kata
  sandbox/shim/QEMU identities have stopped. The observer must retain its live
  correlation before resources disappear. No node-administration credentials are
  added to the adapter. Without this observation, API cleanup remains pending.

`ack.status` describes the operation, not execution success or verified teardown.
`read_result` returns only user JSON bytes; missing/failed results raise a
sanitized `ExecutorError`. `outcome` returns host-owned runner/error information
separately. Guest JSON never determines the execution state or metrics.

## Fixed runner mapping

- Namespace `kata-lab`, RuntimeClass/handler `kata-qemu-runtime-rs`, immutable
  operator-selected image; no alternate runtime, shell or local fallback.
- Kubernetes run name `ka-` plus the persisted attempt UUID's 32 hexadecimal
  digits. The same UUID always uses the same Job and input ConfigMap names.
- Standard-library Python reads `/inputs/data.csv` (use `utf-8-sig` to support the
  backend's permitted BOM), runs `/inputs/script.py`, and writes a JSON object or
  array to `/tmp/result.json`. No pandas `df` or variable capture is provided.
- Backend code cap 16 KiB; CSV 512 KiB; serialized ConfigMap 768 KiB; result 2048
  bytes; termination envelope 3072 bytes. Shared runner validators apply; the
  backend decoder additionally rejects NUL and oversized integer values.
- The adapter rejects `timeout_seconds != 30`: that field is the fixed script
  budget. The Job retains its independent 120-second deadline. Model generation,
  queue/request deadlines and retry scheduling belong to the caller.

Update the backend's provisional DataFrame/result-variable prompt and execution
admission limits before routing model proposals here. This implementation does
not silently rewrite generated code or modify the runner release.

## Persistence, recovery and cancellation

`SQLiteRunStore` is an explicit, adapter-owned **local journal**. The existing
PostgreSQL request queue remains authoritative for application requests and
claims. The journal persists exact input manifests, hashes, identities, provider
UIDs, create intent, terminal outcome/result and cleanup evidence. Backend startup
must reconcile the same request/run IDs in both stores. A caller can supply an
alternative store with the same `operation/get/save/pending` methods, provided
it serializes operations across processes and durably checkpoints before each
remote side effect. It must not hold uncommitted intent across an API call.

Use an existing private local directory with restrictive owner permissions/ACLs;
the journal contains code, CSV and results. Protect its SQLite rollback journals
and `.lock` file too. Never use `:memory:`, a shared/network filesystem, or a new
journal path to recover an existing deployment. Backup/retention/removal must be
coordinated with PostgreSQL and resource cleanup. No database migration or shared
database write runs automatically.

The store's separate SQLite lock serializes adapter operations across cooperating
processes; individual journal checkpoints survive process death. Lock/storage
errors propagate and mean the caller must stop, retain the run ID and reconcile.
They never authorize another submission identity. The caller still owns admission
capacity, request/claim fencing and ensuring every worker uses the same journal.

Before each create, intent is committed. A retry GET adopts only an exact matching
manifest, identity annotations and recorded UID when known. A conflicting object
is never overwritten. If an uncertain create is absent, it is never recreated
automatically: the original request may still arrive. Reconcile or investigate
that identity; do not generate another UUID. Kubernetes physical execution is
not exactly once; the collector rejects multiple observed Pod attempts and the
journal retains one logical result.

`cancel` writes durable intent before deleting anything. A cancellation before
`submit` creates a durable tombstone. Cancellation after a persisted outcome is
rejected, preserving the committed result; cancellation that acquires the store
operation lock first prevents later result publication/dispatch. The caller maps
its own PostgreSQL cancellation intent to repeated adapter cancellation calls.

`cleanup` rejects active/uncollected runs; collect or explicitly cancel first.
It deletes the exact Job, associated Pods and input ConfigMap with UID
preconditions and foreground propagation. An acknowledged delete leaves cleanup
pending until API absence and independent guest teardown are both observed.
Unacknowledged creates keep cleanup unknown even if resources currently appear
absent, preventing a late create from being mistaken for verified cancellation.
The caller must continue reconciliation after disconnect/restart. Deletion
semantics follow [Kubernetes foreground garbage collection](https://kubernetes.io/docs/concepts/architecture/garbage-collection/#foreground-cascading-deletion).

## Transport and access

`KubectlAPI` requires an installed, trusted kubectl and explicit kubeconfig/context.
Every request checks the selected configuration uses HTTPS, a configured CA and
no `insecure-skip-tls-verify`. Use the existing approved private API route and
credential lifecycle. No credentials, SSH tunnels or RBAC are installed.

Raw API operations use argument lists and JSON stdin; neither source nor dataset
is evaluated by a shell. API process lifetime is bounded (20-second kubectl
request deadline, 25-second subprocess deadline plus bounded thread cleanup),
with 1 MiB stdout, 16 KiB stderr and 768 KiB request caps. Diagnostics/errors are
sanitized. The adapter never retrieves guest logs as results. See the official
[`kubectl create`](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_create/)
and [`kubectl delete`](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_delete/)
raw-request options.

The identity needs create/get/delete Jobs/ConfigMaps; get/list Pods/Events and
delete exact associated Pods; read the fixed RuntimeClass, namespace and relevant
Kubernetes/Calico policies. Preflight requires the existing exact default-deny
policy and no additional applicable Calico policies; missing access/evidence
fails closed. This check does not prove enforcement or replace the M6 gate.
Do not reuse the historical read-only client or a broad SSH/admin context as the
application identity. Admission enforcement of the fixed workload and the actual
network/resource limits remains necessary.

## Verification and remaining integration work

```powershell
python -B -m unittest discover -s tests/unit/executor -v
python -B -m unittest discover -s tests/unit/runner -v
```

Offline tests use the actual pinned backend dataclasses/enums/decoder and fake
API responses/processes. They cover success, failures, restart, lost create
responses, late creates after cancellation, duplicate/replacement identities,
bounded transport, TLS checks and interrupted cleanup. No candidate code,
kubectl, model or cluster is executed by these tests.

Live execution remains unverified. The known scratch-size propagation failure
must be resolved and the runner rebuilt/accepted; an explicit approval callback
cannot manufacture that evidence. Actual credential permissions, API behavior,
runtime image provenance and node teardown require the lab acceptance matrix.

The backend team still needs to connect a real worker to these operations, persist
its run IDs and real outcomes in PostgreSQL, expose real statuses in its API,
provide the authorized CSV reader/policy/observer callbacks, align its model
prompt and limits, and schedule reconciliation. The existing fake worker is
unchanged and continues to return fake results until that wiring is implemented.
