# Backend: provisional local prototype

`GET /health` reports process health, not model, executor, database or isolation
readiness. Explicitly configured dataset and request APIs use PostgreSQL and a
private local dataset root. Request intents are durable; a separate, explicitly
invoked fake-only worker processes at most one per run. An opt-in demo worker can
use a local model with a fake executor. There is no generated-code execution or
remote executor. Fake completion is not computation or a benchmark measurement.

## MVP direction: real model-generated code, narrowly evaluated

**Selected local model:** Qwen3.5-9B Q4_K_M is the current MVP candidate after
comparison with 4B. The operator must explicitly start the 9B llama.cpp server;
the application does not choose or launch model weights automatically. Earlier
4B test observations below are historical. The first MVP demonstration focuses
on one or two clear, answerable synthetic questions. Comprehensive ambiguous-
question handling is deferred; do not claim arbitrary questions are supported or
present a guessed answer as verified.

**This section describes the agreed direction, not functionality implemented
or enabled today.** Keep Qwen as the generator of Python for a user's natural-
language CSV question; the MVP is not merely an intent classifier selecting
between prewritten sum/count templates. To keep the first milestone manageable,
evaluate with one small synthetic CSV and one or two representative questions
(Thai and/or English). These are initial evaluation examples, not the only
questions the interface may accept, and they are not evidence of general
correctness on arbitrary data, questions or languages. Exact fixture and
question selection remain to be agreed before claiming an acceptance pass.

The intended future path is: user upload and question → local Qwen proposes one
`run_python` code string → backend validates the envelope, binds server-owned
dataset/runtime settings and displays the code as inert text → an independently
approved remote isolated executor runs it → backend validates and displays the
result with any supported metrics. Model output and CSV headers remain untrusted;
a valid tool call, successful execution or isolated guest cannot prove that the
code answers the question correctly. Unanswerable, ambiguous, invalid and failed
requests must surface as such without fabricated answers. The adapter now
distinguishes a bounded text-only response via `ModelTextOnlyOutcome`, but the
worker does not yet surface a clarification to the user or persist this as a
terminal outcome; text alone is not proof that a response is a clarification.

**Execution remains disabled.** Neither local Python nor an ordinary local
container may run generated code. The fake executor returns presets only. A real
remote integration begins with trusted synthetic fixture code and can accept
model-generated code only after the infrastructure team supplies and the team
reviews evidence of the actual isolation, limits, I/O, cancellation and cleanup
gates. Do not silently fall back to the laptop. Record provider outcomes as
unknown when appropriate and do not assume a database claim fences model calls.

A 2026-11-13 local synthetic retry compared thinking off (one run per question)
with thinking on (three seeds per question), using the same four questions,
8192-token context, temperature 0.6 and top-p 0.95. In thinking mode the model
proposed plausible column sums on the English and Thai cases in all three runs;
it abstained without a tool call on each missing-profit/ambiguous-average case
in two of three runs. In the remaining runs it used a tool call for the missing
profit case and guessed a column for the ambiguous average. Off mode guessed
on average and returned a missing-profit explanation inside a tool call. No
proposed code was executed or independently validated for computation, and
some proposals were bare expressions rather than a verified runner contract.
This is a tiny exploratory probe, not a benchmark or evidence of reliability.

The immediate evaluation work is to freeze a synthetic fixture and expected
answers, define the code/result runner contract and response handling for
clarification versus failure, then repeat local generation and human-review code
against those questions and selected negative cases (missing columns, ambiguity,
unsupported inputs). Record model/version, quantization, prompt, thinking mode,
sampling, seeds, output and latency; never count an invalid or uncertain run as
success. Run generated code only after the remote isolation gate, compare actual
results with independently established expected values, and report any failure.
Two successful examples cannot substantiate a general-purpose accuracy claim.

A follow-up smoke evaluation used `tests/fixtures/qwen_mvp/` with a four-row
synthetic sales file, two positive questions and two negative controls. With
thinking enabled and the current generation prompt, three seeded runs produced
an incorrect revenue expression in two runs; all three ambiguous-total prompts
made a tool call instead of asking for clarification, and two of three
missing-profit prompts used a tool call. A separate exploratory prompt explicitly
advised row-wise operations and clarification: one of three revenue proposals
still had the same wrong aggregation, all three ambiguous prompts called a tool,
and two of three missing-profit prompts called a tool. English revenue and Thai
East-quantity proposals were manually inspected as inert text, not executed.
The probe did not specify the fixture's hypothetical JSON result contract, which
is not team-approved, so none of these runs proves end-to-end compatibility.
These cases and repetitions are too few to establish a reliability rate; their
failures do show the MVP acceptance gate has not been met.

## Local model adapter (experimental)

`app.model_adapter.LocalModelAdapter` is an explicitly invoked library client for
an independently started llama.cpp server at a numeric IPv4 loopback HTTP
endpoint. It does **not** start the server or worker, connect to the request API,
execute generated code, or dispatch it anywhere. The opt-in Qwen demo worker
uses it with the fake executor as described below; the default fake worker does not.
Model availability, tool-calling accuracy and runtime performance depend on the
installed model and server; a valid proposal is not
proof that it will compute a correct answer or be safe to execute.

`generate(question, columns)` sends the question, column names and a fixed
provisional runner description—**never CSV rows**—and accepts exactly one
`run_python` function call with a bounded code string. The code is untrusted,
inert text. Dataset identity, files, runtime, permissions and budgets are never
model-selected. No automatic retries or repair are performed. The runner's
`df` description is a provisional future contract, not an implemented executor.
Prompt instructions alone do not prevent injection or unsafe proposals.

`summarize(question, result)` validates bounded JSON and sends the question and
result with tools disabled. It returns the original result, summary and warning;
a model/validation failure returns the original value and `SUMMARY_UNAVAILABLE`.
A caller must independently validate an executor result before displaying it as a
successful result. Summaries and all user/model content remain untrusted. No
results, questions or code are intentionally logged by this adapter.

The endpoint must be explicitly supplied by the operator; the optional model name
defaults to `local-model`. Only `http://127.0.0.1:<port>/v1/chat/completions`
is accepted. Calls have a maximum
120-second wall-clock deadline, bounded input and response sizes, no redirects,
no remote endpoint fallback and no automatic retry. Only HTTP 200 responses with
one explicit `Content-Length` are accepted; chunked, close-delimited and
informational responses fail closed. Transport configuration is
trusted internal code, not an HTTP client-controlled setting. The local server
and other same-user processes are not authenticated by this loopback restriction.
There is no production model-backed API. The opt-in demo worker persists the
model's generated code as part of its explicitly fake result; it does not
persist a computed answer.
llama-server itself may allow browser cross-origin access without an API key;
loopback binding is not authentication. Keep its availability and exposure under
operator control, avoid sending private data through an unprotected service, and
stop it when not in use.

A synthetic compatibility probe on 2026-11-13 used `llama-server` build 12110
and `unsloth/Qwen3.5-4B-GGUF` Q4_K_M with an 8192-token context and reasoning
off. English and Thai prompts produced parseable single-tool proposals, but a
missing-profit-column prompt **invented a profit formula**, even with an
abstention instruction. These proposals were not executed or checked for
correctness. One tools-disabled synthetic summary returned `3`. This small probe
is not a quality benchmark. The adapter now identifies bounded text-only replies
with `ModelTextOnlyOutcome` (a `ModelAdapterError` subclass); the exception
message omits model text, but traceback frames may retain model responses and
inputs. Do not capture or persist traceback locals. Current worker handling
remains generic failure; it does not yet surface or persist a cannot-answer
message. A text-only response is not necessarily a valid clarification. A
proposal's syntactic validity must never be interpreted as semantic validity.

## Fake-backed application flow (experimental)

`python -m app.phase6_worker --once` explicitly processes at most one queued
request. It reads the selected ready CSV to validate it and obtain **only the
column names** for the model interface. The shipped demo uses a deterministic
fake model and a fixed fake executor; it does not start Qwen or execute generated
Python. Its preset `{"example": [1, 2]}` is **not computed from the CSV** and
must never be presented as a real answer. Generated code is untrusted inert text.
There is no automatic worker startup or polling service.

A newly processed request may expose `fake_result` in detail and history with
`fake: true`, `code`, the preset `result`, `summary`, `warning`, and `metrics`.
`metrics: null` means unavailable, not zero. The shipped fake model has no
summarizer, so the result is retained and `SUMMARY_UNAVAILABLE` is returned.
Previous status-only fake completions may have no `fake_result`. Hiding history
retains the result, question and code in PostgreSQL and backups; it is not
secure erasure. The database and browser must be protected accordingly.

The worker keeps the existing session ownership and claim-token fencing. If
cancellation is requested during processing, the processor may continue until it
returns; final acknowledgement records `cancelled` without publishing a result.
A lost worker or uncertain commit is
not automatically retried; the next worker marks interrupted work `unknown`.
The column reader requires a trusted private dataset root, a ready dataset and a
server-owned storage key. File validation does not prove immutability or
provenance against uncooperative same-user processes. Logical deletion still
retains CSV files and does not reclaim space.

Revision `0005_fake_results` is required before using this code. No migration is
run on startup; verify and separately authorize the target before migrating.
Downgrading revision 0005 is refused while fake results are stored; a later
schema downgrade may still destroy other data. This demo does not establish model
quality, real execution, isolation, computation correctness or resource metrics.

## Opt-in local Qwen with fake execution

For the selected local MVP model, an operator may start a loopback-only server
explicitly (this is a one-process demo, not authentication):

```sh
llama-server --model "$HOME/Library/Caches/kataai/models/Qwen3.5-9B-Q4_K_M.gguf" \
  --host 127.0.0.1 --port 18942 --ctx-size 8192 --gpu-layers 99 \
  --parallel 1 --jinja --reasoning on
```

The server controls which weights are used; the worker's model name is a
request identifier and does not establish the loaded model's identity. The
adapter sends the provisional MVP prompt asking for `result = {"answer": ...}`
with a Python numeric value and explicitly requests coding-oriented sampling
(temperature 0.6, top-p 0.95, top-k 20, min-p 0, presence penalty 0, repeat
penalty 1). The JSON convention is not an approved remote runner contract;
validating the `run_python` envelope does not verify the generated program,
result type or answer. Do not assume that a server enforces or supports every
sampling option without checking its behavior. The model call has a maximum
120-second wall-clock deadline, so slower 9B calls can time out; a timeout does
not guarantee that inference already in progress has stopped.

`python -m app.qwen_demo_worker --once --model-endpoint
http://127.0.0.1:PORT/v1/chat/completions` explicitly processes at most one
queued request with a separately started local model. Dataset runtime and the
model endpoint must be explicitly configured. The worker does not start a model
server, and **never executes generated code**. It uses the fixed fake executor,
returns `fake: true`, `metrics: null`, and the warning
`FAKE_PRESET_NOT_AN_ANSWER`, and does not summarize the preset as an answer.
Questions and column names are sent to the local model; CSV rows are not.

**Header/request compatibility limit:** CSV intake allows field values up to
65,536 Unicode code points and up to 256 columns, but the model adapter accepts
at most 1,024 UTF-8 bytes per column name and at most 32,768 UTF-8 bytes for
the encoded question-and-columns JSON (including JSON syntax and escaping).
A successfully uploaded, ready CSV does not guarantee that a particular question
fits the model request. The question also consumes this combined byte budget.
If an incompatible request is claimed, the adapter fails before sending it; the
one-shot worker reports a sanitized failure and its committed claim can remain
`running` until the next worker takeover marks it `unknown`. There is no automatic
retry or user-facing resolution API for `unknown`. For the current MVP, use
short column names and questions; aligning admission and user-facing recovery is
future work, not an implemented validation guarantee.

A synthetic local integration probe used a disposable PostgreSQL instance and
real HTTP requests: upload and queue two selected fixture questions, invoke this
worker against a separately started Qwen3.5-9B Q4_K_M server, and retrieve detail
and history. Both responses contained generated code and the labelled fake
preset; the code was not executed and the preset was not calculated. A single
run of two examples does not prove general model reliability or runner
compatibility. The disposable database was removed and the test servers stopped.

The model can still produce incorrect proposals. Synthetic local tests observed
Qwen replacing the provided DataFrame with an empty DataFrame for a sales
question, answering a profit question using sales, and guessing which column to
average for an ambiguous question. No proposal was run. Do not treat this flow
as reliable analysis or use syntactic validation as proof of correctness.
Cancellation is cooperative: a request cancelled after claim may still send its
question and column names to the model, and a model call already in progress may
continue. The token-fenced final update prevents publishing a fake result if
cancellation wins. If the worker loses its database session, an in-flight model
call can outlive ownership; the token fences only database writes, not model-side
activity. Worker/session failure or lost commit acknowledgement is uncertain and
is not blindly retried. No authentication is provided by loopback alone; do not
expose the model server or send private data to an unprotected local service.

## Provisional executor handoff (no real executor)

`app.executor_contract` defines an in-process handoff shape containing a
server-owned request ID, run ID, dataset ID, bounded inert Python proposal, and
provisional timeout. The protocol separates operation acknowledgement from
observed run and cleanup states; an `unknown` outcome is not a safe retry signal.
`read_result` is a proposed untrusted byte channel, not an implemented provider.
There is no Kubernetes client, VM connection, remote dispatch, input staging,
real cancellation, or real result persistence in this phase.

The fake worker constructs the shape with the request/dataset IDs and a fresh
**ephemeral fake-only** run ID and passes the complete handoff to `FakeExecutor`.
This ID is not stored or sent anywhere and must not be used for real submission.
A real integration must first persist the logical run/attempt identity and submit
intent, establish provider-side idempotency or reconciliation, bind results to the
correct run, and define cancellation/cleanup confirmation with infrastructure.
A database claim token alone does not fence remote execution.

`app.executor_results.decode_execution_result` decodes bounded untrusted UTF-8
JSON with explicit byte, nesting, item and integer limits; it rejects duplicates,
non-finite values, NUL characters, invalid Unicode, and malformed or oversized data. JSON `null`
is a valid value distinct from a missing or unavailable result. Guest fields
called `status` or `metrics` are only data, not trusted execution status or
resource measurements. Limits are provisional; transport must bound bytes while
reading, before accumulating the entire result. The fake flow applies this decoder
to the preset and still returns `fake: true`. This neither executes a proposal
nor validates a computation. Real origin, isolation and provider contracts remain
unverified; no remote result can be accepted merely by matching this JSON shape.

## Provisional request API and fake-only queue

The API contract, states and limits are local prototype decisions, not a
frontend/teammate agreement. Explicit local PostgreSQL and private dataset-root
configuration are required as described below; no schema migration is run on
startup. `POST /v1/requests` accepts exactly these required JSON fields:

- `schema_version`: the string `"1.0"` only.
- `client_request_id`: a UUID string, normalized as the idempotency key.
- `dataset_id`: a UUID string for an active, ready dataset.
- `question`: a nonblank UTF-8 string of 1–4,096 Unicode code points. NUL and
  unpaired surrogates are rejected. Thai and English are accepted as data.

For a new key and ready dataset, the endpoint creates a durable queued intent
and returns 201 with its server-generated `id`, `status` and `provisional` flag.
A retry with the same client UUID, dataset UUID and **exact same question**
returns the same request ID and current status with 200, even if the dataset's
state subsequently changes. Reusing the key for different input returns 409.
The normalized UUID spellings identify the same key. Missing/deleted datasets
return 404; incomplete datasets, unavailable configuration or uncertain database
operations return 503. Malformed input returns sanitized 422. Unknown fields,
including client-controlled infrastructure settings, are rejected.

Success is returned only after a confirmed commit. A 503 or lost reply does not
prove rollback. For submission recovery, retrying the **same client ID and exact
same payload** is idempotent; it does not enqueue a duplicate or redispatch
claimed/unknown work. Do not generate a new ID merely because a response was
lost. This guarantee concerns request creation, not any future external provider.

`GET /v1/requests/{id}` returns the last recorded status, dataset ID, original
question and creation time, or 404 for a missing or hidden request.
`GET /v1/requests` returns visible history, newest first, with a `limit` of
1–100 (default 20). A returned `next_cursor` can be passed back as the `cursor`
query parameter. Pagination is keyset-based, not a stable snapshot: concurrent
inserts or hiding may change what later pages contain; a cursor may lead to an
empty page. The
question is returned as **untrusted plain data**, never as safe HTML or code.
Successful request status and history responses include `Cache-Control: no-store`.
These endpoints have no authentication beyond the documented local browser
boundary. Questions are stored in PostgreSQL and returned through local history;
the application provides no encryption-at-rest or retention policy. Hiding a
request does not erase its question or database record. Protect the database,
backups and trusted browser accordingly. No
question, storage path or SQL exception is returned in an error message.

`POST /v1/requests/{id}/cancel` changes queued work to `cancelled`, or marks
running work `cancel_requested` until the fake worker acknowledges it. A
`cancel_requested` response does **not** mean a worker or external provider has
stopped. Cancellation and fake completion are serialized: their commit order
determines precedence, and a running cancellation still requires acknowledgement.
Already completed or `unknown`
work cannot be cancelled and returns 409. A subsequent worker takeover marks
interrupted `running` or `cancel_requested` work `unknown`, never requeues it.

`DELETE /v1/requests/{id}` **hides** a cancelled or fake-completed request from
normal detail and history responses; it returns 204. Active or unknown requests
cannot be hidden and return 409. Hiding is not secure erasure: the full record,
including the question, idempotency key and dataset reference, remains in the
database. A repeated submission using the same client key and payload returns
the retained original ID and status without unhiding or redispatching it. A
repeat hide of an already hidden ID returns 404.

### Fake worker and crash semantics

The HTTP server **does not start a worker**. With the same explicitly configured
local runtime and migrated database, run the one-shot fake worker separately:

```sh
python -m app.fake_worker --once
```

Each invocation processes at most one queued request and exits. Run it again to
process another; there is no automatic polling service in this phase. The outcome
`fake_completed` is a preset state transition, explicitly marked `fake: true` in
status/history. It does not read CSV rows, compute an answer, call a model, or
execute Python. `queued` means waiting; `running` is the last committed claim,
**not proof of current liveness**. On the next worker takeover a previous running
or cancel-requested claim becomes `unknown`, not queued, and is never
automatically redispatched.
A new worker may process another queued request. There is no API for resolving or
retrying `unknown` work in this phase.

Cooperating fake workers hold an exclusive PostgreSQL session advisory lock on a
dedicated non-pooled connection; a database constraint and claim token further
protect the running transition and fence stale database writes. The token does
**not** fence external side effects, and these guarantees do not establish safety
for a real provider. Lost database/commit acknowledgments remain uncertain; the
worker stops without blind retry. An operator must coordinate all writers before
manual intervention. Future real execution requires separately approved isolation,
provider idempotency and recovery design.


The provisional transport limit for `POST /v1/requests` is 65,536 body bytes,
inclusive, counted from the ASGI stream before JSON parsing rather than trusting
`Content-Length`. Larger bodies return HTTP 413 with
`{"error":{"code":"REQUEST_TOO_LARGE","message":"Request body is too large."}}`.
This bounds application accumulation per request, not the size of an individual
chunk already delivered by the ASGI server, server/proxy buffering, parsing
overhead, concurrent requests, or request duration. It is not a global memory or
denial-of-service limit; deployment still needs server/proxy limits, timeouts,
and concurrency controls.

## Local browser security boundary (Phase 1)

The shipped ASGI policy is explicit and fixed: `Host: 127.0.0.1:8000` and,
when present, `Origin: http://127.0.0.1:8000`. Host includes the port. Only
literal IPv4 `127.0.0.1` with a canonical explicit port is supported, not
`localhost`, IPv6, wildcard hosts, default-port omissions, HTTPS or DNS names.
`SecurityPolicy(host, origin)` validates each independently; a trusted embedding
application can inject a different explicit port on each via
`LocalSecurityMiddleware`, but the shipped app has no environment overrides.
Invalid policy construction raises an error, never broadens access. Tests inject
policy directly; this is not runtime user configuration. The shipped application
supports only this same-origin arrangement; serving a frontend and supporting
alternate backend/frontend ports in the shipped app are deferred.

All HTTP paths, including unknown routes, are checked before reading request
bodies. Duplicate, missing or foreign Host, and duplicate, `null`, malformed or
foreign Origin are rejected with a fixed 403. Origin-less GET/HEAD is permitted;
these methods must never mutate state. All other methods require the exact Origin
and exactly one `X-KataAI-Request: 1`. Origin-less CLI writes are unsupported.
Approved preflights only allow GET/HEAD/POST/PUT/PATCH/DELETE and the
`content-type` and `x-kataai-request` headers, with an exact origin, no wildcard
or credentials. WebSocket scopes are refused. FastAPI's CDN-backed interactive
`/docs` and `/redoc` pages are disabled so external scripts are not loaded into
the trusted backend origin; host-guarded `/openapi.json` remains available. No
`X-Forwarded-*` header is used for these decisions; do not place the service
behind an untrusted proxy.

**Threat model:** single trusted local user, no authentication. The Host check
limits browser DNS rebinding, and the non-simple header plus strict CORS and
Origin check protects against simple-form CSRF from foreign origins. Neither
Origin nor the header authenticates a client: native programs can forge them;
compromise of the trusted origin, client-side CSRF, XSS, other local processes,
and an adversary who can bind or control the trusted frontend are out of scope.
Fetch Metadata is not used as authentication. ASGI cannot enforce socket binding:
the operator must bind to `127.0.0.1:8000`, disable untrusted proxy rewriting,
and not expose the service on a network. This is not a multi-user service.

## Dataset upload and lookup HTTP API (provisional)

The route names, limits and error codes are local prototype choices, not a
frontend/teammate agreement. Requests are protected by the local security policy
above. No login, browser UI, file-download API, automatic reconciliation or
generated-code execution is provided.

**Explicit configuration is required:** set `DATABASE_URL` to a migrated local
PostgreSQL target at literal `127.0.0.1`, `::1`, or an absolute Unix-socket path,
and set `KATAAI_DATASET_ROOT` to an existing absolute, owner-private local
filesystem directory. Inherited `PG*` environment variables are rejected. The
application does not create the directory, connect or run migrations on import,
or choose a default database. Missing, invalid or unavailable configuration
returns sanitized HTTP 503. Configure and authorize a target before running any
migration; never use a real database as a disposable test target. Protect URL
credentials; do not place them in repository files, logs, or shell history.
The root's ancestors, local filesystem semantics, ACLs and same-UID processes
must be trusted; permission checks alone do not establish privacy.

`POST /v1/datasets` accepts `multipart/form-data` with exactly one part named
`file` and no additional file or text parts. Filename is optional (default
`upload.csv`) and is untrusted display metadata, never a storage path. Names
with path separators, control/format characters, leading/trailing whitespace,
`.`/`..`, invalid UTF-8 or more than 255 Unicode code points are rejected.
The part's Content-Type and request Content-Length do not prove file contents.
Actual CSV validation uses the strict provisional grammar and limits below.

The observed raw request body, including multipart framing, is limited to
10,065,536 bytes; file bytes are limited to 10,000,000. The multipart parser
limits part headers to 8,192 bytes and the ASCII boundary to 70 bytes, accepts
only one part, and accepts at most a final CRLF after the closing boundary. A
15-second idle and 60-second total **intake** budget are checked around receives
and processing. A nonblocking advisory filesystem lock admits one cooperating
upload at a time across processes using the same private root; contention returns
503. This requires a trustworthy local filesystem and cooperating processes.
The budgets cannot interrupt a blocked kernel filesystem or database operation;
server/proxy buffering and producer-side allocations are outside these limits.

Uploads are streamed to an exclusive 0600 temporary file in the configured root,
not the system temporary directory. The CSV is validated before metadata is
created, then staged and validated again by the publication adapter. A successful
201 includes only `dataset_id`, `display_name` and `state: "ready"`; storage
keys, paths and file contents are not returned. `GET /v1/datasets/{dataset_id}`
returns 200 only for active/ready records, 404 for missing/deleted records, 503
for pending/unknown or an unavailable backend, and 422 for a malformed canonical
UUID. A ready row is a point-in-time metadata state, not an integrity or
availability guarantee against later file loss or replacement. Display names
are untrusted and consumers must render them safely.

`DELETE /v1/datasets/{dataset_id}` performs **logical deletion only**: it
marks an eligible dataset deleted in PostgreSQL and returns
`file_cleanup: "not_attempted"`. It does not inspect, unlink or erase its CSV;
**disk space is not reclaimed**. A repeat delete of a tombstone returns the same
logical result, without claiming the file exists. Missing IDs return 404.
Pending/unknown publication or any associated queued, running, cancel-requested
or unknown request blocks deletion with 409. Completed or cancelled request
records remain retained. There is no API to resolve unknown work in this phase.

The delete path takes the shared upload admission lock before the queue claim
lock and dataset row lock; request creation is serialized by the dataset row lock.
These protections require a trusted local root and cooperating HTTP publishers;
direct internal or out-of-band writers are not covered by the filesystem lock.
Database or lock failure can leave a commit outcome unknown and returns 503.
An operator must inspect the durable tombstone rather than assume rollback;
ordinary dataset GET returns 404 for both deleted and missing records. No deletion path
attempts physical file cleanup or promises secure erasure.

Invalid multipart, filename, CSV or encoding returns a sanitized 422; oversized
input returns 413; an intake timeout returns 408; storage, admission, database
or uncertain outcomes return 503. Failures and lost connections **do not prove
rollback**: a publication or final commit may have succeeded. Do not blindly
retry or delete a final file. A private `.upload-admission.lock` file is retained
for advisory locking. The temporary upload and publication stage can coexist,
requiring space for roughly two file copies plus overhead. No total disk quota,
crash cleanup or safe automatic reconciliation is implemented; an operator must
coordinate with all active writers before any investigation. Only owned spool
entries are removed on ordinary cleanup, with cleanup failure treated as uncertain.

Dataset readiness does not imply real execution readiness. Exact API contracts,
decimal byte convention, resource budgets, and frontend compatibility require
team review.

## Internal model-proposal validator (execution disabled)

The provisional proposal input is a list with exactly one object containing only
`name` and `arguments`; `name` must be `run_python`, and `arguments` must contain
only a non-whitespace `code` string of at most 16,384 UTF-8 bytes. This shape and
limit are local test decisions, not an agreed external contract. Error names are
likewise provisional. Do not treat this validator as a sandbox.

## Provisional B2 internal metadata-first coordinator

`app.dataset_publication.publish_dataset_on_connection(connection, root, name, source)`
creates pending PostgreSQL metadata, commits it using that same connection, calls the
private CSV publisher with its stored UUID key, and commits a conditional ready
transition only after the publisher returns successfully. Use only a dedicated connection
with no unrelated pending work, a migrated schema and the correct search path;
this function commits the connection's entire transaction. The lower-level
`publish_dataset(store, commit, ...)` is an injected internal seam: its callback
must commit the very transactions containing that store's insertion and ready
transition. A no-op,
different transaction, or in-memory store cannot establish this guarantee. The
caller owns connection and source lifetimes. The dataset upload route calls this
coordinator after intake validation using a dedicated database connection.

**Critical: `active` is a lifecycle value, not file readiness.** `publication_state`
is separately `unknown`, `pending`, or `ready`. Legacy rows and direct SQL inserts
default to `unknown`; adapter-created rows start `pending`. The conditional ready
update requires matching ID, storage key, active lifecycle, and pending state; only
the coordinator may use it after successful publication. The store primitive cannot
itself prove publication; trusted callers must respect this contract. A successful
coordinator return means the ready transaction's commit returned successfully.
No cross-resource atomicity, integrity audit, or automated reconciliation is
implemented. An HTTP-ready state is not a guarantee of later file integrity.

A successful return contains the committed metadata and observed CSV metadata;
CSV counts and headers are not persisted. On an ordinary commit exception the
service reports `commit_unknown`, keeps the generated identity in the exception,
and does not attempt file publication; the commit may nevertheless have happened.
Publication errors report `publication_failed`, the identity and the adapter's
sanitized code/publication/cleanup states. The row is already committed. No final
file is removed and no retry is attempted. Insert errors propagate from the store; the caller must handle the transaction,
including rollback where appropriate. `ready_conflict` means the conditional
update matched no row; `ready_update_unknown` and `ready_commit_unknown` mean the
outcome is uncertain. In particular, a lost final commit reply can leave a durable
ready row despite the error. Never infer rollback from an exception. Interruptions
propagate; commit/update `KeyboardInterrupt` loses its arguments and context,
and publication interruptions follow the storage adapter's rules. Other
`BaseException` types can contain secrets; do not log them unsafely.

After restart, `PostgresDatasetStore.list_incomplete(limit=100, after=None)`
offers read-only observations of pending and unknown rows (including tombstones).
It accepts limits 1–1000 and a `(created_at, id)` keyset cursor from the last
row. Ordering is deterministic, but pages are not a stable cross-transaction
snapshot: inserts, state changes, and transaction timestamps can cause omissions
or changes. A pending row may still have an active publisher; this list does not
claim or lock work, establish writer liveness, or authorize intervention. A crash
after publication may leave a pending row and a file; a crash after ready commit
may leave ready without a reply. File existence alone never promotes readiness.
Manual handling requires separately coordinating with all writers; there is no
implemented safe reconciliation procedure, blind retry, or automatic deletion.
Tests observe pending and legacy unknown rows through a new PostgreSQL connection;
that is a reconnect simulation, not an actual process-crash or power-loss test.
CSV metadata and file fingerprints are not persisted. Ready is not a permanent
integrity or availability guarantee against later file loss or replacement.

## Provisional B2 private local publication

`app.local_csv_storage.publish_csv(root, source, key, limits)` is an internal
adapter only. The trusted application must supply an existing private local
root, a caller-owned binary readable stream, and a server-issued `UUID` storage
key; it accepts no client filename or path. The internal coordinator above supplies
the key from committed metadata, with the explicit readiness limitations described.
The upload and metadata-lookup routes use this adapter; dataset deletion is
logical only and there is no file-download endpoint. Processing remains fake-only.

The adapter opens the normalized final root component without following a
symlink, requires a directory owned by the effective UID with no group/other or
special mode bits, and never chmods the root. Ancestors are trusted; normalization
is lexical and is not a secure walk of ancestors. Ownership and mode bits do
**not** prove privacy against macOS or inherited ACLs, network/shared filesystem
semantics, or other same-UID processes. The operator must establish a trusted
local root and trusted ancestors and ensure ACLs and filesystem policy are
private. This is not a defense against a hostile process with the same UID.

Only exact `bytes` chunks are accepted; subclasses and other types are rejected
before their special methods can affect EOF or byte counts. Observed bytes are
bounded by `CsvLimits`; the adapter creates an exclusive
random 0600 staging file, loops over partial writes, fsyncs it, and validates
its already-open inode using the existing CSV validator. It then hard-links the
stage to the UUID name without replacing a pre-existing entry, removes the stage,
and fsyncs the directory. Operations on entries are relative to the opened root
fd with no-follow and exclusive/no-replacement primitives; unsupported required
primitives fail closed. These semantics assume a trustworthy local POSIX
filesystem. The caller owns and closes the source. A byte bound does not prevent
blocking source reads or memory already allocated by a producer; concurrency,
timeouts and total disk quotas are outside this adapter.

`CsvStorageError` has sanitized `code`, `publication`, and `cleanup` fields.
CSV validation codes are preserved; `SOURCE_ERROR`, `STORAGE_ERROR`,
`KEY_COLLISION`, `INVALID_KEY`, `INVALID_ROOT`, and `UNSUPPORTED_PLATFORM`
represent local failures. `publication` is `not_published` when no link was
attempted; `indeterminate` means a link operation (including `FileExistsError`)
or subsequent publication/cleanup operation failed and the
final entry may exist or its durability is uncertain. `cleanup` is `confirmed`
when no stage was created or its removal and directory fsync completed, and
`unknown` when removal or its directory fsync fails. Never infer rollback from
an error or automatically remove the final entry; it may have been replaced.
`KEY_COLLISION` indicates a `FileExistsError` during linking, not proof that
this attempt did not publish: a link implementation could succeed then raise.
A successful return supplies the validator's metadata. The header remains
untrusted. Error details never contain file contents or paths. Interruptions
such as cancellation or `KeyboardInterrupt` propagate after best-effort cleanup;
they carry no cleanup/publication confirmation, so callers must treat the
outcome as unknown and must not blindly retry or infer rollback.
KeyboardInterrupt is re-raised without its original arguments or context. Other
BaseException types, including cancellation and SystemExit, propagate unchanged;
their arguments and traceback may contain sensitive producer information. The
source interface is therefore trusted with respect to such exceptions: callers
must not log them or expose them to untrusted clients without their own safe
handling. Arbitrary cancellation types cannot be generically reconstructed safely.

Crashes, process termination, filesystem faults, and failed cleanup may leave
staging or final orphans. Directory fsync is not a cross-platform promise of
hardware durability. There is no crash cleanup, reconciliation, DB/file atomic
transaction, lifecycle/deletion protocol, or safe automated retry here. The HTTP
route has separate browser-origin and streaming controls, but must not be treated
as proof of automatic recovery or execution readiness.

## Provisional B2 CSV intake core

`app.csv_intake.validate_csv(source, limits)` consumes a caller-owned binary
file-like object or iterable of byte chunks once and returns immutable
`CsvMetadata(columns, byte_size, row_count)` only after successful EOF. It does
not close the stream, use filenames or client hints, retain rows, persist files,
connect to a database, call a model, or execute CSV text. The upload route invokes
this validator before metadata creation. Request processing remains fake-only. Header names are
untrusted data, not safe HTML, SQL, spreadsheet formulas, or model instructions.

All rules are **provisional**, not frontend/teammate-approved. Default inclusive
limits are 10,000,000 bytes (decimal, including BOM), 100,000 data records,
256 columns, and 65,536 Unicode code points per decoded field (after unescaping);
`CsvLimits` allows positive integer overrides, but `max_bytes` cannot exceed the
hard 10,000,000-byte ceiling. Decimal versus binary MB is still
open. Observed source bytes, not hints, determine acceptance. The first record
is the required header; its names are returned verbatim, must contain a
non-whitespace character, and must be unique by exact Unicode string equality
(no trimming, case folding, or normalization). Header-only files are accepted
with zero data rows. Every record must have exactly the header width. A truly
blank unquoted physical record is rejected regardless of width; an explicitly
quoted empty field is allowed as a one-column data record. No automatic
delimiter or encoding detection is done.

The exact grammar is provisional, not an agreed CSV contract. It is
comma-separated, UTF-8 only with an optional initial UTF-8 BOM;
a later U+FEFF is ordinary field content. NUL is forbidden. LF, CRLF, and CR
end records outside quotes. A quote may start only at the start of a field;
doubled quotes inside a quoted field decode to one quote; quoted fields may
contain commas and arbitrary line breaks. After a closing quote only a comma,
record ending, escaped quote, or EOF is allowed. Unterminated quotes and quotes
in unquoted fields are rejected. Spaces are significant and there is no escape
character. This deliberately strict grammar is not a claim of full RFC 4180
compliance or parity with other CSV engines.

The implementation uses an incremental UTF-8 decoder and a small state machine,
not `csv.reader` or `TextIOWrapper`, and never mutates `csv.field_size_limit`.
The stdlib CSV reader's process-global field cap, permissive strict-mode grammar,
and potential whole physical-line/logical-record buffering are unsuitable for
these independent per-call policies. Byte input is requested in 65,536-byte
reads, and large returned chunks are checked against remaining budget *before*
decoding, then decoded in slices. A producer can already have allocated an
oversized chunk before returning it; this code cannot prevent that allocation.
Peak memory is not a 64 KB or constant-memory guarantee: retained header strings,
Python object overhead, decoding, caller buffers, and concurrency add overhead
bounded by the configured limits. The validator cannot enforce source-side
buffering, deadlines, blocking reads, or concurrent request limits; sources can
block indefinitely and the byte limit is not a duration limit. The HTTP route
applies separate intake controls as described above. More than 1,024 total empty
iterable chunks are rejected to avoid no-progress amplification. Stream reads
returning empty exact bytes signify EOF; non-exact-bytes chunks are rejected
without invoking their comparison, truth, length, or slicing methods.

Errors are `CsvIntakeError` with a stable `code` of `INVALID_UPLOAD`,
`UPLOAD_TOO_LARGE`, or `UNSUPPORTED_ENCODING` and fixed content-free messages.
For a complete byte stream, precedence is `UPLOAD_TOO_LARGE` over
`UNSUPPORTED_ENCODING` over `INVALID_UPLOAD`. After syntax or encoding failure,
scanning continues to EOF or the byte limit; source errors or invalid chunks
before that point produce `INVALID_UPLOAD` because the input is unavailable.
Ordinary source `Exception` errors do not appear in the public error, and
`KeyboardInterrupt` propagates with its arguments and context removed. Other
`BaseException` types propagate unchanged; source producers are trusted not to
include secrets in those exceptions, or callers must sanitize them safely at
their boundary. Never log source
inputs, headers, traceback locals, or exception internals; traceback frames can
retain sensitive input even when the rendered exception is sanitized. No error is
a substitute for transport-level controls.

## Python 3.12 setup and checks

From `backend/`:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
# Avoid inheriting packages from a different Python environment, if set.
unset PYTHONPATH PYTHONHOME
python -m pip install -e '.[dev]'
python -m pytest -q
python -m ruff check .
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Direct dependencies are pinned; transitive dependencies are not locked. The test
suite is offline after installation. Loopback binding is intentional but alone
is not a browser-origin/CSRF security policy; do not expose this skeleton on a
network. The real execution feature remains disabled pending the isolation and
infrastructure gates in the implementation plan.

## Provisional database migration foundation

Dataset upload, metadata lookup, logical deletion and the durable fake-only queue
use this foundation; no file-download endpoint exists. The provisional `datasets`
table contains a caller-supplied UUID primary key, a separately generated unique
UUID storage key (never a path), a bounded display name, creation time, and an
`active`/`deleted` tombstone with a matching deletion timestamp. Producers must
generate opaque IDs and sanitize display names before insertion; constraints are
only a defensive minimum, not HTML escaping or a complete Unicode/confusable
policy. Request intents retain a non-cascading dataset reference; no separate
history-retention policy, physical deletion protocol, file/DB atomicity, complete
race protection, or automatic cleanup is implemented. Revision 0004's downgrade refuses while
cancelled, cancel-requested or hidden records exist; this guard does not make
other downgrade paths safe. Downgrading revision 0003 drops the entire
`request_intents` table, including history and idempotency records. Downgrading
revision 0002 drops readiness information; re-upgrading assigns `unknown` to
existing rows, requiring manual reconciliation. Downgrading to base also removes
the dataset table and its data. None is a safe production rollback strategy.
Schema, policies and API are provisional.

## Provisional metadata storage port

`app.dataset_store.DatasetStore` supports only `create(display_name)` and
`get(UUID)`, including retrieval of deleted tombstones. `DatasetMetadata` is an
immutable typed record. UUIDs for IDs and opaque storage keys are generated by
the adapter (UUID4 by default), never derived from a filename or path. A supplied
factory and the fake's clock are for deterministic tests; callers should not
derive identifiers from untrusted input. Names are validated before either
adapter writes: 1–255 Unicode code points, no leading/trailing whitespace,
slashes, Unicode control/format/surrogate characters, or `.`/`..`. This is
intentionally stricter than the migration and is not output escaping or a full
Unicode security policy. Duplicate IDs or storage keys fail with
`DuplicateDatasetMetadata`; invalid input with `InvalidDatasetMetadata`; missing
IDs with `DatasetNotFound`. PostgreSQL SQLAlchemy errors become the stable
`DatasetStorageError` without SQL, parameters, or connection details in the
rendered exception. Do not log exception internals or enable SQL parameter
logging when handling sensitive data.

Inject an already-open SQLAlchemy PostgreSQL `Connection` into
`PostgresDatasetStore(connection)`. The caller supplies a migrated schema and
correct search path and owns connection lifetime and commit/rollback; the adapter
does not connect or commit. For example, inside a caller-managed
`with engine.begin() as connection:` block, create the store, call `create`, and
save the returned ID. PostgreSQL `created_at` is the transaction timestamp, not
necessarily wall-clock insertion time. Invalid input is rejected before SQL;
duplicates use `ON CONFLICT DO NOTHING`, leaving the transaction usable. Other
database errors may abort the transaction: the caller must roll it back. These
errors are not claimed recoverable by the adapter.

`MemoryDatasetStore` is in-process and accepts injectable UUID factory and
timezone-aware clock. It does not model database transactions, rollback,
isolation, concurrent access, persistence, or PostgreSQL timestamp semantics.
It implements the metadata-only port, not the separate `PublicationStore` port,
so the coordinator rejects it before creating metadata or publishing a file. This
structural preflight does not verify the behavior of a custom store or commit callback.
The live contract exercises single-connection create/lookup, validation,
duplicate ID/key recovery, deleted-row reads, error sanitization, and caller
rollback. It does not prove concurrent behavior, crash recovery, file/DB
atomicity, or physical deletion semantics. The dataset routes use the PostgreSQL
adapter; no physical file deletion or real execution is implemented.

Alembic requires an explicitly supplied `DATABASE_URL` with PostgreSQL username,
database, and either a TCP host or an absolute Unix-socket directory. No default
URL/database is provided. Only `host` (socket directory) and `port` query
parameters are accepted; TLS/query configuration is not yet designed. Alembic
errors intentionally avoid displaying connection details, so check configuration
and server status separately. Never put credentials in repository files, command
history, logs or a checked-in URL. URLs in environment variables may be exposed
to privileged local processes; use appropriate secret handling. All inherited
`PG*` environment variables, including empty values and SSL settings, are rejected
before URL use in migrations (including offline SQL) and live tests. Unset them
in the invoking process; they are never silently stripped or displayed. This
restriction does not configure TLS: assess transport security and other libpq or
system configuration separately, and verify the target before any migration.

For disposable targets only, after explicitly provisioning an empty, isolated
PostgreSQL instance and setting `DATABASE_URL` securely:

```sh
# Inspect SQL without connecting; still requires an explicit DATABASE_URL.
python -m alembic upgrade head --sql
# This modifies the database identified by DATABASE_URL. Verify it first.
python -m alembic upgrade head
```

## PostgreSQL integration tests: explicit opt-in only

Normal `python -m pytest -q` is offline and skips live tests even if a database
URL happens to be present. Provision a **separate disposable PostgreSQL instance**
and empty database yourself first; never use a real, shared, or production DB.
For example a CI PostgreSQL service can use a dedicated empty database, or a
locally provisioned private PostgreSQL instance can use a socket directory
accessible only to its owner. Do not point tests at your ordinary local server.
The flag, explicit guard, and URL are all required:

```sh
unset PYTHONPATH PYTHONHOME
# Examples without passwords: use only with your own isolated instance.
# TCP:    export TEST_DATABASE_URL='postgresql+psycopg://kataai_test@127.0.0.1:55432/kataai_disposable'
# Socket: export TEST_DATABASE_URL='postgresql+psycopg://kataai_test@/kataai_disposable?host=/tmp/PRIVATE_SOCKET_DIR&port=55432'
export KATAAI_DISPOSABLE_DB=1
python -m pytest -q -m live_postgres --run-live-postgres
```

This exact CI command fails with a usage error when either guard or URL is
missing, rather than silently skipping. A connection or migration failure also
fails the suite. The suite generates uniquely named schemas and sets its
search path so application tables and `alembic_version` live there. Cleanup
uses transactional `RESTRICT` drops for `request_intents`, `datasets`,
`alembic_version` and the test schema.
External dependencies that block table removal or independent unexpected objects
in the test schema make cleanup fail and roll back. PostgreSQL can still remove
objects automatically dependent on a dropped table, such as its indexes and
triggers. A test also explicitly removes its own dependent view and separate
schema using `RESTRICT`. Cleanup never drops a database. A crash or cleanup failure
can leave test schemas behind; destroy the entire disposable instance using the
provisioning system after tests.
The opt-in guard is an operator assertion, **not a technical proof of
isolation**. The test user must have schema create/drop privileges only in the
intended disposable DB. Tests do not start, stop, or destroy PostgreSQL.
