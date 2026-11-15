# Backend to Kata integration review

Inspected: 2026-11-15 (Asia/Bangkok). Status: integration incomplete; recommended work below is proposed, not implemented.

## Scope and evidence

- Backend branch pinned to [`49f94011b0f824d45dc1bf012473b3af978f3b77`](https://github.com/chinabunchorn/kataAI/commit/49f94011b0f824d45dc1bf012473b3af978f3b77), including application code, migrations, tests, CI, and the existing [integration handoff](https://github.com/chinabunchorn/kataAI/blob/49f94011b0f824d45dc1bf012473b3af978f3b77/docs/infrastructure/BACKEND_INTEGRATION_HANDOFF.md). This branch contains no `infra/runner` implementation.
- Runner inspected in the local `main` checkout at `7aee424a851e5505e149b1648efff0a589113aa4`, including preexisting uncommitted changes to Dockerfile/build inspection, contract, supervisor and artifact tests, and untracked `infra/runner/scratch.py`. Those changes were preserved. The local contract says version 0.1.1; the README and recorded released image describe 0.1.0. Source edits do not update the released artifact.
- Historical lab evidence: [M3 acceptance](infrastructure/M3_ACCEPTANCE.md), [scratch investigation](infrastructure/M3_SCRATCH_INVESTIGATION.md), and [infrastructure records](infrastructure/INFRASTRUCTURE.md). These describe observations on November 11, not current cluster health.
- Remote files were read through the GitHub connector and copied to ignored `.m3-runs/backend-review-49f9401/` for inspection. No branch switch, implementation change, infrastructure operation, database migration, model call, or candidate execution was performed.

## Assessment

The backend provides CSV intake/private storage, PostgreSQL request admission and idempotency, queue claims, cancellation intent, and an optional local Qwen proposal generator. It currently completes requests through a preset fake executor. The runner provides the guest execution protocol and pure host helpers for staging, fixed Job construction, and result validation. The missing bridge is a durable Kubernetes executor and reconciliation worker, principally roadmap M4/M5, plus contract alignment and unresolved M3/M6/M8 acceptance gates.

For this architecture, the persistent OpenStack VM hosts Kubernetes/containerd/Kata. Each execution Pod gets a Kata sandbox VM. The backend manages Kubernetes resources; Kata/containerd manage the guest. Creating/deleting an OpenStack server for each request is outside the documented lifecycle.

## Findings

### F1 — Blocking: execution is fake-only

[`phase6_processor.py:10`](https://github.com/chinabunchorn/kataAI/blob/49f94011b0f824d45dc1bf012473b3af978f3b77/backend/app/phase6_processor.py#L10) reads dataset headers and calls `run_fake_flow`. [`fake_flow.py:25`](https://github.com/chinabunchorn/kataAI/blob/49f94011b0f824d45dc1bf012473b3af978f3b77/backend/app/fake_flow.py#L25) constructs `FakeExecutor` directly. [`FutureExecutor`](https://github.com/chinabunchorn/kataAI/blob/49f94011b0f824d45dc1bf012473b3af978f3b77/backend/app/executor_contract.py#L84) is only a Protocol. There is no Kubernetes dependency/client or implementation of its operations.

Implement a real adapter and a dedicated worker path. Reuse `stage_inputs`, `make_job`, `ExpectedRun`, `collect_result`, and `external_failure` from the runner as shared host-side code. Never invoke the guest supervisor on the backend. Integrate the branch histories or package the shared helpers explicitly; copying divergent protocol constants will create drift. Preserve the fake path for tests and make real mode explicit.

### F2 — Blocking: the model and runner have incompatible contracts

[`model_adapter.py:23`](https://github.com/chinabunchorn/kataAI/blob/49f94011b0f824d45dc1bf012473b3af978f3b77/backend/app/model_adapter.py#L23) promises a pandas `df` and asks code to set `result`. The [runner](../infra/runner/supervisor.py) launches `/inputs/script.py` as a separate Python process, supplies no DataFrame, adds no pandas dependency, and reads `/tmp/result.json`. A proposal using the advertised interface can fail with an undefined `df`, unavailable pandas, or `RESULT_MISSING`.

Recommended first contract: retain the fixed standard-library runner, use `csv`/`json`, read `/inputs/data.csv`, and write one JSON object/array to `/tmp/result.json`. Update the model prompt and fixture expectations accordingly. Adding pandas and a DataFrame wrapper is a separate versioned runner change requiring a new artifact and acceptance evidence.

| Boundary | Backend today | Runner today | Required alignment |
|---|---|---|---|
| CSV bytes | 10,000,000 | 524,288 | Reject execution-incompatible data before generation/dispatch, or deliberately revise and retest staging. Never silently truncate. |
| Script bytes | 16,384 | 32,768 | Backend's stricter limit is compatible; document the effective limit. |
| Execution time | Interface accepts 1–300 s; fake handoff uses 60 s | 30 s script budget; 120 s Job deadline | Separate model, queue, script, Job and request deadlines. Do not promise a timeout the runner ignores. |
| Result bytes | 32,768 | 2,048; termination envelope 3,072 | Validate the runner envelope separately from the user result; use the agreed result cap. |
| Result shape | Any JSON root | Object/array root | Align root types and validation semantics. |
| Structure | Depth 16 from root zero; 4,096 values | Container depth 16 from root one; 128 entries/collection, 256 total | Share the actual validator/protocol, not just the numeric depth value. |
| String NUL | Backend rejects | Runner permits escaped NUL | Explicitly choose the accepted intersection or revise validators together. |

Sources: [`csv_intake.py`](https://github.com/chinabunchorn/kataAI/blob/49f94011b0f824d45dc1bf012473b3af978f3b77/backend/app/csv_intake.py), [`executor_results.py`](https://github.com/chinabunchorn/kataAI/blob/49f94011b0f824d45dc1bf012473b3af978f3b77/backend/app/executor_results.py), [`executor_contract.py`](https://github.com/chinabunchorn/kataAI/blob/49f94011b0f824d45dc1bf012473b3af978f3b77/backend/app/executor_contract.py), [runner constants](../infra/runner/contract.py), [runner validation](../infra/runner/validation.py).

### F3 — Blocking: requests are durable, execution attempts are not

[`fake_flow.py:21`](https://github.com/chinabunchorn/kataAI/blob/49f94011b0f824d45dc1bf012473b3af978f3b77/backend/app/fake_flow.py#L21) generates an ephemeral run UUID. The migrations through `0005_fake_results` persist neither attempts/provider identities nor real outcomes. The SQL status constraint and [`request_api.public_record`](https://github.com/chinabunchorn/kataAI/blob/49f94011b0f824d45dc1bf012473b3af978f3b77/backend/app/request_api.py#L23) support only the fake-era statuses. Dataset deletion/history rules also explicitly refer to fake terminal states.

Before any API mutation, persist the attempt UUID, deterministic Kubernetes run name, dispatch intent, approved runner digest/protocol, code and CSV hashes, and exact input snapshot/reference. Persist ConfigMap/Job/Pod UIDs as they become known. Record execution outcome and cleanup state independently. Update migrations, queue operations, API serializers, history and dataset-deletion guards together.

On a lost create response, read the deterministic object name and verify its UID when known, ownership, expected manifest and hashes; adopt only an exact authorized match. A collision or ambiguous result stays unknown. Do not generate another run ID and blindly submit again. Claim tokens/advisory locks fence database writes, not Kubernetes side effects. Publish at most one logical outcome; do not claim exactly-once physical execution. Kubernetes explicitly documents possible duplicate starts even for single-completion Jobs ([Jobs](https://kubernetes.io/docs/concepts/workloads/controllers/job/#handling-pod-and-container-failures)).

### F4 — Blocking: cancellation, reconciliation, and cleanup are absent remotely

[`RequestQueue.cancel`](https://github.com/chinabunchorn/kataAI/blob/49f94011b0f824d45dc1bf012473b3af978f3b77/backend/app/request_queue.py#L109) updates local intent only. [`fake_worker.py:62`](https://github.com/chinabunchorn/kataAI/blob/49f94011b0f824d45dc1bf012473b3af978f3b77/backend/app/fake_worker.py#L62) marks interrupted claims unknown on takeover, with no provider reconciliation. It must not be reused unchanged for real execution.

Build a worker that reconciles durable attempts after startup and connection loss, observes cancellation during staging/submission/running/collection, and uses UID-preconditioned deletion. Cancellation must prevent further dispatch or stop the associated Job/Pods and continue cleanup. Acknowledged deletion is not confirmed termination. Serialize cancellation and result publication so the winner and public outcome are deterministic, while cleanup always proceeds.

Persist validated output before deleting its termination-message source. Foreground-delete the exact Job, observe all associated Pods absent, remove the exact input ConfigMap, and retry unfinished cleanup after restart. The ConfigMap currently has no Job owner reference, so Job deletion alone will not remove it. TTL can be a backup after an evidence-retention window; it is not the result collector or the cleanup reconciler ([Jobs](https://kubernetes.io/docs/concepts/workloads/controllers/job/#job-termination-and-cleanup), [garbage collection](https://kubernetes.io/docs/concepts/architecture/garbage-collection/#foreground-cascading-deletion)).

The existing [test harness](../tests/infrastructure/m3/run.py) already has bounded transport and exact-UID API cleanup examples, but intentionally writes `vm_teardown_verified: false` for ordinary API cleanup. The [M3 node evidence](../tests/infrastructure/m3/evidence/2026-11-11/node-security.json) separately demonstrates one correlated sandbox teardown. Add a trusted node-side observer or operator verification procedure that links Pod UID → CRI sandbox → Kata shim/QEMU and confirms their disappearance. Keep API absence and guest teardown as separate facts; do not give the backend unrestricted node administration just to obtain this proof. A disconnected node can leave teardown unknown even if API objects disappear.

### F5 — Blocking for real dispatch: recorded client credentials are read-only

[Infrastructure §13.9](infrastructure/INFRASTRUCTURE.md) records a verified Windows SSH tunnel to the API, CA-validated TLS, and namespace-scoped read-only authentication. Job creation and Pod deletion were denied. This is a useful connectivity baseline, not a dispatch credential. The M3 SSH operator harness is explicitly not the application transport.

Provision a separate execution identity and credential lifecycle. Minimum required capabilities include create/get/delete ConfigMaps and Jobs, get/list (and watch if used) Pods/Jobs, optional bounded Pod logs and UID-associated Events. Add Pod deletion only if the selected cancellation/orphan policy needs direct deletion; normal dependent cleanup can use Job deletion. RuntimeClass/policy preflight also requires narrowly scoped read access or trusted operator-provided evidence. Avoid Secrets, pod exec, node writes, broad cluster-admin and policy mutation. Test this exact identity through the real local-to-remote route.

RBAC resource permissions cannot alone restrict a created Job to the approved image/runtime/security template. Use trusted server-owned construction and enforce the applicable admission/isolation controls before accepting model-generated code; verify policy effects and effective resource/network limits in the lab.

### F6 — Blocking acceptance: scratch enforcement is unresolved

[M3 acceptance](infrastructure/M3_ACCEPTANCE.md) records a successful 20 MiB write despite the declared 16 MiB guest scratch cap. Thirty other live checks passed; the capacity test failed and its dependent exhaustion test remains unrun. The investigation traces a guest tmpfs size-propagation omission in the installed runtime.

The local uncommitted 0.1.1 source adds `validate_scratch` and fails preflight if guest `/tmp` is not the approved writable 16 MiB tmpfs. On the recorded oversized guest filesystem it should reject execution; this is a guard, not a runtime capacity fix. There is no new build or live acceptance evidence in the inspected record. Correct the runtime behavior through a reviewed change, rebuild/pin the runner artifact, and repeat scratch-capacity/exhaustion and relevant runner regression checks. Do not mark the current image or M3 accepted based on host tests.

### F7 — Environment constraint: the backend data path requires POSIX

[`dataset_runtime.py`](https://github.com/chinabunchorn/kataAI/blob/49f94011b0f824d45dc1bf012473b3af978f3b77/backend/app/dataset_runtime.py), `local_csv_storage.py` and `dataset_columns.py` require POSIX directory descriptors, no-follow opening and ownership/mode checks. Native Windows does not satisfy this implementation. `pyproject.toml` requires Python >=3.12,<3.13; this review host has Python 3.13.15 and no backend dependencies.

For a Windows operator, use an explicitly configured WSL/Linux environment with appropriate private storage and loopback/tunnel topology, or implement and verify a separate Windows storage backend. Do not bypass filesystem checks. Confirm database/model/API reachability from the actual chosen process environment.

## Recommended implementation order

1. **Contract and source integration:** bring backend and runner code into one integration baseline, select one immutable runner release, reconcile the table above, and freeze one trusted CSV/script/expected-result fixture. Keep generated-code execution disabled while its isolation gates are unresolved.
2. **Durable execution storage:** introduce an attempts table and real result/error records. Include operation intent, provider UIDs, hashes, timestamps/deadlines, cancellation intent, cleanup observations and reconciliation errors. Keep the MVP at one admitted execution at a time; unresolved possibly-running attempts must count against capacity until reconciled.
3. **Kubernetes adapter:** implement submit/status/read_result/cancel/cleanup around shared runner helpers and bounded authenticated transport. Resolve an authorized ready dataset to its private storage key, read a bounded stable byte snapshot, check/hash exactly the bytes staged, and create the immutable input ConfigMap before the fixed Job. A dataset UUID alone transfers no data.
4. **Observation and outcome persistence:** associate every Job/Pod/Event with recorded identity; detect additional/replacement Pods; validate image provenance, runtime and termination evidence; collect the bounded termination report using `collect_result`; map external failures only from associated authoritative evidence. Diagnostic logs remain separate and bounded. Persist a structured success/failure outcome, including missing-report cases.
5. **Lifecycle worker:** add startup reconciliation, unknown-outcome recovery, cancellation and cleanup retries. Reuse deterministic object names to recover uncertain creates. Define short API timeouts, bounded backoff, queue/request deadlines, and an independent cleanup deadline. A backend/network timeout does not stop a remote VM; the fixed Job deadline and later reconciliation remain necessary.
6. **Lab acceptance and application completion:** resolve scratch enforcement, obtain scoped credentials, and prove the trusted fixture through the actual API/worker path. Then test real model generation against the agreed file contract after M6/M8 gates. Summarize only independently validated successful results; a summary failure preserves the computed result. Handle model text-only/clarification and generation failures as explicit application outcomes rather than stranding a claim as running/unknown. Never return fake presets as computed answers.

Suggested execution observations: preparing → submitted → running → collecting → succeeded/failed/timed_out/cancelled, with unknown available wherever evidence is lost. Track cleanup separately: not_started → pending → API_absent → guest_teardown_verified, retaining failed/unknown states and evidence timestamps. This is a proposed storage/API design, not an approved replacement for existing enums.

## Acceptance matrix

For every terminal case, retain request/run IDs, input/code hashes, image/protocol, ConfigMap/Job/Pod UIDs, relevant trusted timestamps and Kubernetes outcome, collection result, API cleanup evidence and correlated guest teardown evidence. Keep sensitive input/code out of ordinary logs.

| Case | Required observation |
|---|---|
| Trusted success | Exact expected JSON from the mounted CSV, genuine Kata association, result persisted, API resources and guest removed. |
| Script/result failure | Syntax/nonzero/missing/invalid/oversized result correctly classified, no fabricated success, same cleanup proof. |
| Timeout/resource failure | Script timeout distinguished from Job deadline, OOM and scratch exhaustion using appropriate evidence; cleanup verified. |
| Cancellation | Queued, staged, submitting, running and collecting cancellation races converge without late dispatch/result overwrite or abandoned inputs/guest. |
| Outage/restart | Kill worker or interrupt API link before/after each create, result commit and delete; restart reconciles the same attempt without blind resubmission. |
| Duplicate/mismatched objects | Duplicate dispatch, replacement Pods and wrong UID/image/runtime/report are detected; at most one logical result is published. |
| Partial create/cleanup | Orphan ConfigMap, lost create response and deletion timeout converge through durable reconciliation without deleting unrelated resources. |
| Missing Kata/image/permissions | Failure is explicit, no fallback runtime/local execution, remaining staged resources cleaned. |
| Integrated security | Approved isolation, network, privilege, resource and cross-dataset probes pass through the real request path before generated-code acceptance. |

## Verification performed

| Criterion | Status | Evidence and limit |
|---|---|---|
| Runner host contracts/artifact/mock-control checks | Passed | `python -B -m unittest discover -s tests/unit/runner -v`: 39 tests passed against the local working tree. No actual guest or candidate execution. |
| Backend snapshot parses | Passed | `ast.parse` over all 83 backend Python files in the pinned snapshot; this is syntax evidence only. |
| Current interfaces are directly compatible | Failed | Host-only pure-helper probes: valid 600,050-byte backend CSV rejected by runner; backend accepts null, 129-entry array and 3,000-byte string object that runner rejects; runner accepts escaped NUL that backend rejects; interface accepts 60 s while script budget is fixed at 30 s. No script execution. |
| Backend real dispatch/lifecycle implementation | Failed | Source inspection: fake executor construction, Protocol-only future adapter, no durable attempts/provider cleanup implementation. This is expected unfinished functionality, not attributed as a regression. |
| Scratch-capacity acceptance | Failed in historical lab evidence | November 11 record; current runtime behavior not rechecked. Local guard does not close this gate. |
| Backend pytest/PostgreSQL suite | Untested in this review | pytest/application dependencies absent; host Python 3.13 is outside declared support; no disposable PostgreSQL target supplied. Existing README/CI describe tests but are not a new passing execution here. |
| Live integrated execution, current credentials, VM teardown and M6/M8 acceptance | Untested | No cluster, model, database or runtime operations performed. Historical fixture evidence does not prove this integrated path. |

Only this report was added to tracked project content. Implementation and infrastructure changes remain follow-up work.
