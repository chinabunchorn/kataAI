# Backend → infrastructure integration handoff

## Purpose and current status

This handoff is for the backend and infrastructure teams to agree on the first safe integration between the local application and a remote Kata execution environment. The goal is to answer one or two clear questions about a synthetic CSV using Python proposed by the local model.

**Current status: backend preparation is available; real execution is not.** The backend can validate a CSV, accept and persist requests, ask an explicitly started local Qwen model for Python, and drive a **fake-only** worker. Generated code remains inert text. The fake result is a preset, not an answer computed from the CSV. There is no implemented Kubernetes client, remote executor, input staging, real result retrieval, or remotely enforced cancellation.

The infrastructure specification and roadmap describe the intended topology, not proof that the cluster, access, runtime, or isolation is currently operational. The team must verify current conditions and agree on the interface before integration. See [infrastructure specification](INFRASTRUCTURE.md) and [project roadmap](../../Sandboxed_AI_Inference_Master_Roadmap_v0.3.md).

> **Safety gate:** Do not run model-generated Python on the laptop or in a non-approved runtime. Do not silently fall back to ordinary containers if Kata is unavailable. Real execution stays disabled until the team reviews and approves evidence for isolation, limits, network policy, I/O, cancellation, cleanup, and recovery.

## 1. Intended flow and responsibilities

```text
Local application (implemented fake-only preparation)
  CSV upload → validated private storage → request queue in PostgreSQL
  → one-shot worker → local Qwen proposes inert Python
  → FakeExecutor returns a labelled preset (current behavior)

Future integration (not yet implemented or agreed)
  backend worker → authenticated, least-privilege remote submission
  → isolated Kata workload + explicitly staged inputs
  → bounded, run-bound result and trusted lifecycle observations
  → backend validates and persists the outcome
```

| Area | Backend today | Integration work / decision needed |
|---|---|---|
| CSV and request | Validates CSV, publishes it to private local storage, records dataset metadata, and persists request intents. | Agree how an authorized CSV is staged into the remote workload and removed afterward. |
| Code proposal | Local Qwen can produce a bounded `run_python` proposal; the code is untrusted text. | Agree on the fixed runner, dependencies, input shape, code delivery, and output contract. |
| Execution | Fake executor returns a predetermined value. | Infra provides and demonstrates the approved isolated execution environment; backend implements a real adapter only after the contract and gate are approved. |
| State | Durable requests, token-fenced fake completion, cancellation intent, and conservative `unknown` recovery. | Agree on durable run/attempt and provider identities, idempotent submission or reconciliation, cancellation, and cleanup observations. |
| Results | A bounded JSON decoder exists and is exercised with fake data. | Agree on a bounded result channel and trusted origin/identity checks. Guest-provided status or metrics are not authoritative. |

## 2. What the backend currently provides

- **Dataset intake:** CSV only, strict UTF-8 (including optional BOM), with provisional limits of 10,000,000 bytes, 100,000 data rows, 256 columns, and 65,536 characters per field. The application uses a server-owned opaque storage key; a dataset ID is **not** a filesystem path or the storage key. See [`csv_intake.py`](../../backend/app/csv_intake.py) and [`dataset_columns.py`](../../backend/app/dataset_columns.py).
- **Requests:** `POST /v1/requests` accepts schema version `"1.0"`, a client request UUID, an active/ready dataset UUID, and a question. The same client ID and exact input resolve to the existing request; a different input under that ID conflicts. A lost response or uncertain commit does not prove rollback: retry the same ID and exact payload, not a new ID. This guarantee covers request creation only, **not remote submission**.
- **Input preflight:** New HTTP requests check header and question compatibility before queuing, including the complete encoded model request. Incompatible input returns sanitized HTTP 422 `MODEL_INPUT_INCOMPATIBLE`; an unavailable CSV returns 503. Existing idempotent requests are resolved first. Validation is point-in-time and can read the whole CSV while holding database locks; it does not make the file immutable. Existing queued requests are not retroactively checked.
- **Model:** The opt-in local Qwen3.5-9B Q4_K_M flow sends the question and column names—not CSV rows—to an explicitly started loopback model server. It validates a single tool proposal and stores the generated Python as inert text. The model can still generate incorrect code or guess; syntax checks are not correctness or safety checks. The server, not the requested model name, determines which weights are actually loaded.
- **Fake execution:** The one-shot worker does not start automatically. The Qwen fake flow returns `fake: true`, `metrics: null`, and `FAKE_PRESET_NOT_AN_ANSWER`; its preset is not a computation and is not summarized as an answer. The fake-only run ID is ephemeral, is not persisted for remote use, and must **not** become a real submission identity.
- **Retention and exposure:** Dataset deletion is logical and retains CSV files; hiding request history does not erase database records. Loopback Host/Origin protections are not user authentication. Questions, generated code, and metadata can remain in PostgreSQL and backups. Protect local storage, model access, and credentials; do not expose the local API or model service as an authenticated production service.

The canonical setup details, API behavior, limitations, and test guidance are in the [backend README](../../backend/README.md). PostgreSQL revision `0005_fake_results` is required by the current code. No migration runs automatically; verify and separately authorize a database target before applying migrations. Disposable test databases are not an application database.

### Existing local API and fake worker entry points

- Upload a CSV through `POST /v1/datasets`; use the returned `dataset_id` in `POST /v1/requests` with JSON fields `schema_version`, `client_request_id`, `dataset_id`, and `question`. The default local API expects `Host: 127.0.0.1:8000`; write requests also require the exact documented origin and `X-KataAI-Request: 1` header, including non-browser clients. The API boundary is not an infra authentication mechanism.
- Inspect `GET /v1/requests/{id}` or `GET /v1/requests` for status/history. `POST /v1/requests/{id}/cancel` requests cancellation; it does not prove an in-flight operation stopped.
- From the `backend/` directory, with its Python environment active and an explicitly configured, authorized, migrated PostgreSQL database and private local dataset root, `python -m app.phase6_worker --once` processes at most one request using a fake model and fake result. `python -m app.qwen_demo_worker --once --model-endpoint http://127.0.0.1:PORT/v1/chat/completions` instead uses an **already started** local model and still returns only a fake result. Replace `PORT` with the operator's configured loopback port. Neither command starts the model server or remotely executes code. Do not point tests or migrations at an unverified shared database.

## 3. Provisional backend-facing executor shape

The following is an **in-process Python interface for discussion**, not an implemented transport or an agreement with infrastructure. The source of truth is [`executor_contract.py`](../../backend/app/executor_contract.py).

| Handoff field | Current meaning |
|---|---|
| `request_id` | Backend request UUID. |
| `run_id` | UUID for a proposed execution attempt. The current fake ID is temporary and unsuitable for remote dispatch. |
| `dataset_id` | Backend dataset UUID; it does not by itself grant remote file access. |
| `proposal.code` | Untrusted Python source as inert text; maximum 16,384 UTF-8 bytes under the current proposal validator. |
| `timeout_seconds` | Provisional integer limit of 1–300 seconds; actual enforced bounds and deadline semantics require agreement. |

The proposed `FutureExecutor` operations are `submit`, `status`, `read_result`, `cancel`, and `cleanup`. `accepted` / `rejected` / `unknown` describe **an operation acknowledgement**, not successful execution or confirmed cleanup. Observations separately represent run state (`queued`, `running`, `completed`, `failed`, `cancelled`, `unknown`) and cleanup state (`not_started`, `pending`, `confirmed`, `failed`, `unknown`). These types do not provide transport, persistence, authentication, delivery guarantees, or verified lifecycle transitions.

The model prompt currently suggests a JSON-compatible variable such as `result = {"answer": ...}`. It also refers to a DataFrame, but **neither a runner-provided `df`, a fixed input path, nor a particular output channel is agreed or implemented**. Treat this as a prompt convention to negotiate, not an executable runner specification. The generated code is not verified merely because the tool call has the expected shape.

## 4. Decisions and evidence requested from infrastructure

Please reply with the following, distinguishing what is already implemented and verified from what is proposed:

1. **Current environment and access:** Is the VM/cluster healthy now, and is nested virtualization usable? Which Kata runtime class and version are actually available? Provide recent verification evidence. How can the local backend reach the Kubernetes API with verified TLS and least-privilege, scoped credentials? Do not paste secrets into issues or this repo.
2. **Submission and workload identity:** What API or service creates a run? Which immutable identifiers map our request and durable run/attempt ID to the Job, Pod, and sandbox? Is a stable idempotency key supported? How can the backend query/reconcile a submission when the response is lost or the worker restarts?
3. **CSV and code delivery:** How are the specific authorized dataset and inert code transferred to the workload? Specify integrity/provenance checks, data-size limits, input paths or objects, mount permissions, staging lifetime, cleanup, and behavior for missing or altered data. The backend currently holds local data; a UUID alone does not transfer it.
4. **Runner contract:** Provide a versioned runner/image and dependency manifest. Specify Python version and packages; whether the runner creates `df` or exposes a fixed CSV path; how it loads CSV; how it receives code; what output is required; and how failures are represented. Agree the format before changing the model prompt or implementing an adapter.
5. **Result channel:** How are result bytes returned without trusting guest logs as provider status? Define framing, maximum bytes enforced **while reading**, completion/availability, error cases, and request/run binding. Provide trusted exit/status evidence separately from user-controlled JSON and explain how metrics are obtained. Do not rely on guest-controlled `status` or `metrics` fields.
6. **Isolation and limits:** Provide an enforceable, tested policy for Kata selection, restricted privileges, filesystem access, credentials/secrets, network/egress and metadata service access, CPU, memory, processes, disk, execution time, output size, and protection of other workloads. Explain who enforces each limit and how it is verified.
7. **Lifecycle and recovery:** Define queued/running/terminal observations, timeouts, cancellation acknowledgement versus actual termination, Job/Pod deletion, guest and staged-input cleanup, and how cleanup is independently confirmed. Define behavior for disconnects, worker/session loss, API timeout, and an uncertain submission or cleanup.
8. **Trusted fixture and access procedure:** Supply a small, non-sensitive CSV and a **trusted, hand-written** Python fixture with expected output, plus the approved way to submit and observe it. This verifies plumbing first; it does not prove that model-generated code is safe.

## 5. Required coordination and failure semantics

- Before real dispatch, the backend must persist a stable run/attempt identity and submit intent, bind any provider IDs and returned results to it, and implement an agreed reconciliation process. A database session lock or claim token fences database writes; it does **not** fence a model call or a remote side effect.
- `unknown` means the outcome cannot currently be established. Do not automatically resubmit, generate a replacement run ID, or claim cleanup succeeded. Reconcile using the agreed provider identity and policy.
- Cancellation is currently cooperative: `cancel_requested` does not prove processing stopped, and an in-flight model call may continue. Real remote cancellation needs its own acknowledgement, observation, and cleanup design.
- The current one-shot fake worker holds a PostgreSQL advisory session lock; on takeover it marks interrupted running/cancel-requested work `unknown` instead of automatically retrying. This is not a complete distributed worker or remote lifecycle implementation.
- Real result ingestion must verify transport origin and request/run identity, enforce a bound during transport, and distinguish missing/unavailable results from valid JSON `null`. The existing decoder is only one defensive layer, not proof of provenance or correct execution.

### Current provisional JSON decoder limits

The backend's [`executor_results.py`](../../backend/app/executor_results.py) accepts at most 32,768 bytes, nesting depth 16 (root depth zero), 4,096 values including the root (object keys excluded), and integers of at most 1,024 bits. It rejects duplicate keys, invalid UTF-8/unpaired surrogates, NUL characters, non-finite numbers, malformed JSON, and over-limit payloads. These are backend defaults for discussion, **not yet an agreed runner protocol**. The helper receives bytes already in memory, so a future transport must impose its own streaming read cap first.

## 6. Suggested integration sequence and acceptance evidence

1. **Agree and document** the runner, identity, staging, result, lifecycle, and failure contracts above; assign owners and record open decisions.
2. **Verify infrastructure using trusted inputs only:** demonstrate Kata/runtime selection, scoped access, bounded resources, network restrictions, timeout/cancellation, and cleanup with the hand-written fixture. Capture evidence and independently verify the isolation gate. No model-generated code at this stage.
3. **Implement the backend adapter** against the agreed contract with persistent submission intent/identities, bounded I/O, trusted correlation, cancellation/cleanup tracking, and reconciliation of uncertain outcomes. Add fake-provider tests for error, retry, ownership, and crash cases first.
4. **Run an explicitly approved integration test** in the verified remote environment using only the trusted synthetic fixture. Confirm input delivery, expected output, correlated run/Job/Pod identities, and cleanup. Resolve failure-path tests and ambiguous outcomes before advancing.
5. **Only after separate approval**, consider one or two clear synthetic questions with model-generated code in the approved sandbox. Inspect correctness and failures; keep the no-local-execution rule. Neither a passing trusted fixture nor a well-formed tool call establishes general model correctness or sandbox security.

## 7. What has and has not been verified

- **Verified locally:** focused offline backend tests and targeted disposable-PostgreSQL tests of fake flows, request admission, idempotency, and deletion/concurrency behavior. A local synthetic probe called Qwen for two questions and saved inert code alongside explicitly fake results; the code was not executed. See the [backend README](../../backend/README.md) and tests under [`backend/tests`](../../backend/tests).
- **Not verified by this backend preparation:** current VM/cluster health or Mac access; runtime isolation and enforcement; a production or persistent database; live remote submission, data staging, trusted result transport, cancellation, cleanup, or end-to-end execution. The infrastructure team must provide fresh evidence and the teams must agree on the interface.
