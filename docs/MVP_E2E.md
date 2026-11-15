# Native macOS research MVP

For the consolidated step-by-step commands, use the [operator runbook](RUNBOOK.md).

This integration has **passed the live Mac → Qwen → remote Kata → JSON → Qwen → HTTP workflow**
for the two synthetic positive cases and both negative controls. Kubernetes API
resources are absent after cleanup; independent guest teardown remains pending.
See [recorded verification and blockers](evidence/mvp-e2e/README.md).
The approved runner/runtime are unchanged. No release or merge to main is part of this work.
This is an explicitly opted-in private research demonstration, not M4/M5/M6/M8 approval.

## Architecture and contracts

The MacBook Air M2 hosts native ARM64 Python 3.12, FastAPI, PostgreSQL, private
CSV storage, one worker, llama.cpp/Metal and the executor SQLite journal. The
existing OpenStack VM hosts Kubernetes, containerd and Kata; its Runner image
stays **linux/amd64**. React is built locally and served from FastAPI at the same loopback origin. No WSL, backend Linux VM, Docker backend or broker.

`POST /v1/datasets` → existing multipart upload/storage → `POST /v1/requests` →
PostgreSQL queue → `app.kata_demo_worker` → local `LocalModelAdapter` → validated
`run_python` proposal → persisted real UUID/code → `KataExecutor` / `KubectlAPI` →
remote Kata Job → collected JSON → local Qwen summary → PostgreSQL real outcome →
`GET /v1/requests/{id}`. Expensive model calls happen only in the worker.

The prompt requires Python 3.12 standard library, `/inputs/data.csv` opened with
`utf-8-sig`, and explicitly writing `/tmp/result.json`. Code remains capped at
16 KiB, CSV at 524288 bytes (reject, never truncate), result at 2048 bytes with
object/array roots, and script time at 30 seconds. The calculation `answer` key
is a prompt convention; the backend also accepts other runner object/array roots.
No pandas, variable capture, generated templates, local execution or repair/retry.
A text-only response becomes `needs_clarification` with bounded text and no Job.
Text classification does not guarantee the content is a useful clarification.

The pinned runner is:

```text
docker.io/kataai/runner@sha256:6a682ed00f47fc27c18eb3abd9e3448960133433265ec6442339c9484d246bf9
```

Image verification compares actual provider `containerStatuses[].imageID` with
that manifest or the release's independently recorded linux/amd64 config digest
`sha256:19e8bd4750d918f4c21daaea258434eeec3f080a61ae3821181cc1925245af12`.
Guest JSON never decides provider status, image provenance or resource metrics.
RuntimeClass `kata-qemu-runtime-rs`, non-root/read-only inputs, CPU/memory/deadline,
network default-deny and TLS checks remain in the existing executor unchanged.

## Native prerequisites

Install or use native ARM64 Python 3.12, `uv`, PostgreSQL, llama.cpp with Metal,
macOS kubectl, SSH and OpenSSL. The tested machine already had these installed;
weights were already at `$HOME/Models/Qwen3.5-9B-Q4_K_M.gguf` (about 5.68 GB).
Do not rebuild the remote runner for Apple Silicon.

From the repository root in zsh:

```zsh
uname -sm                     # Darwin arm64
uv venv --python 3.12 .venv    # only if no suitable .venv exists
uv pip install --python .venv/bin/python -e 'backend[dev]'
.venv/bin/python --version
llama-server --version
llama-server --list-devices    # MTL0: Apple M2
```

The existing POSIX storage works natively: `fcntl.flock`, `dir_fd` open/link/unlink,
`O_DIRECTORY`, `O_NOFOLLOW`, `O_NONBLOCK`, `os.geteuid`, ownership/mode validation,
private temporary files, atomic publication and directory fsync were exercised
on macOS. No filesystem protection was disabled. The real CSV resolver also
rejects symlinks, nonregular files, wrong owner, nonprivate permissions, hardlinks
and files exceeding the runner cap. Root ancestors, ACLs and same-UID processes
remain trusted as in the existing backend.

## PostgreSQL and private directories

Use your existing native PostgreSQL service. Provision a dedicated local demo
database owned by your local role, for example:

```zsh
pg_isready
createdb kataai_mvp_demo        # once; use your own chosen demo database
export DATABASE_URL="postgresql+psycopg://$USER@/kataai_mvp_demo?host=/tmp"
umask 077
mkdir -p "$PWD/.mvp-demo/datasets" "$PWD/.mvp-demo/state"
chmod 700 "$PWD/.mvp-demo" "$PWD/.mvp-demo/datasets" "$PWD/.mvp-demo/state"
export KATAAI_DATASET_ROOT="$PWD/.mvp-demo/datasets"
export KATAAI_JOURNAL="$PWD/.mvp-demo/state/kata-runs.sqlite3"
export PYTHONPATH="$PWD/backend:$PWD"
(cd backend && ../.venv/bin/python -m alembic upgrade head)
```

Choose the correct socket directory/role for your installation; do not copy
credentials into the repository. Existing database configuration rejects all
inherited `PG*` variables and requires explicit local connection configuration.
Inspect the selected database before migrating. Migration `0006_real_results`
follows `0005_fake_results`; historical migrations and fake results remain intact.
It adds run UUID, result JSON, generated code, answer and error/warning fields,
and real terminal states. Downgrade refuses to erase real execution evidence.

Journal parent must be an existing owner-private directory; existing journal
files must be private regular files. Preserve this same journal across runs.
It contains code/CSV/results; `.mvp-demo/` is ignored by Git.

## llama.cpp on Metal

In its own terminal, from the root:

```zsh
export KATAAI_MODEL_PATH="$HOME/Models/Qwen3.5-9B-Q4_K_M.gguf"
backend/scripts/run_mvp.zsh model
```

This selects `MTL0`, offloads layers, binds **127.0.0.1:8080**, uses one slot and
4096 tokens. Start here on the 16 GB Air; do not use the model's maximum context.
The worker uses `/v1/chat/completions`, the existing strict IPv4-loopback endpoint.
The actual installed build supports Qwen3.5 and `--jinja` tool parsing. Capture
verbose logs only for synthetic probes because they may contain prompts/results.
Generation/summarization each have the adapter's 120-second bound. Summaries explicitly disable thinking using the loaded template
parameter `chat_template_kwargs.enable_thinking=false` and request one sentence.
This prevents reasoning from consuming the summary output budget; generation
still uses the existing sampling and template defaults. The 4096-token
context is suitable for this small fixture, not every admitted 16 KiB result/code
or header configuration; excess context requests fail visibly rather than retry.

Reproduce a generation-only benchmark (never executes model code):

```zsh
PYTHONPATH=backend:. .venv/bin/python backend/scripts/benchmark_qwen.py \
  --output /tmp/qwen-metal.json
```

Inspect actual tool envelopes, generated arithmetic/filtering, text-only responses,
finish reasons and timings. The saved raw responses include server token timings.
Structural validity is not a computation pass; superseded failures are documented.

## Approved Kubernetes access and verified TLS

Obtain the **existing approved application** kubeconfig/context through your
infrastructure credential process. Application startup never provisions identities or changes RBAC. A dedicated
identity was provisioned during this session with explicit operator authorization;
see the renewal section below. No admin execution fallback is available. Historical `kata-client-readonly` cannot submit this flow.
The application identity needs the exact permissions described in
[the executor access contract](../infra/executor/README.md#transport-and-access):
Jobs/ConfigMaps create/get/delete, Pods get/list/delete, Events get/list,
RuntimeClass/namespace and Kubernetes/Calico policy reads. Missing policy evidence
fails closed. Retain the existing default-deny policy; do not widen it for a demo.

Example tunnel using the already configured private SSH alias:

```zsh
ssh -o ExitOnForwardFailure=yes -N \
  -L 127.0.0.1:16443:127.0.0.1:6443 katavm
```

If this port is already occupied by the correct tunnel, reuse it. Configure the
approved application's cluster server as `https://127.0.0.1:16443`, retain the
actual cluster CA, and use a certificate SAN matching the endpoint. This server
certificate includes `127.0.0.1` and `katavm`; its public SSH address is not a SAN.
Do not set `insecure-skip-tls-verify`, replace the CA or ignore a hostname failure.

```zsh
openssl s_client -connect 127.0.0.1:16443 \
  -CAfile "$HOME/.kube/katavm-ca.crt" -verify_ip 127.0.0.1 \
  -verify_return_error </dev/null
export KATAAI_KUBECONFIG="$HOME/.kube/kataai-mvp.yaml"
export KATAAI_KUBE_CONTEXT='kataai-mvp'
kubectl --kubeconfig "$KATAAI_KUBECONFIG" --context "$KATAAI_KUBE_CONTEXT" config get-contexts
kubectl --kubeconfig "$KATAAI_KUBECONFIG" --context "$KATAAI_KUBE_CONTEXT" \
  auth can-i create jobs.batch -n kata-lab
```

`KubectlAPI` rechecks HTTPS/CA configuration for every operation and kubectl
verifies the actual server connection. The observed tunnel's TLS verified with
return code 0. The dedicated `kataai-mvp` identity passed all required permission checks and
denied unrelated administrative actions. The cluster-admin credential remains
on the VM; application dispatch uses only the dedicated ServiceAccount token.

## API, hand-written smoke, then real worker

Export database/root variables in each relevant terminal. Start the API:

```zsh
export KATAAI_API_PORT=8000
backend/scripts/run_mvp.zsh api
```

If port 8000 is occupied, use `KATAAI_API_PORT=8001` and use that same port in all
client Host/Origin/base URLs. This is a strict loopback port override, not public
binding support. The default checks remain unchanged.

First upload the synthetic fixture through the existing API:

```zsh
curl --fail-with-body -H "Origin: http://127.0.0.1:$KATAAI_API_PORT" \
  -H 'X-KataAI-Request: 1' \
  -F 'file=@backend/tests/fixtures/qwen_mvp/sales.csv;type=text/csv' \
  "http://127.0.0.1:$KATAAI_API_PORT/v1/datasets"
```

With an idle queue and approved application credentials, run the separate,
hand-written synthetic CSV smoke before model-generated execution:

```zsh
export KATAAI_PRIVATE_EXPERIMENTAL_DEMO=1
PYTHONPATH=backend:. .venv/bin/python -m app.kata_smoke \
  --dataset-id '<uploaded dataset UUID>' --kubeconfig "$KATAAI_KUBECONFIG" \
  --context "$KATAAI_KUBE_CONTEXT" --journal "$KATAAI_JOURNAL"
```

The fixed **smoke probe only** counts CSV rows/columns in remote Kata, persisting
its request/run UUID and actual result. For sales.csv expect rows=4 and the four
column names. It intentionally has no Qwen summary (`SUMMARY_UNAVAILABLE`). It is
never used as a substitute for a failed model proposal. Inspect its provider Job,
image, runtime and collected result before continuing.

After that succeeds, start the real worker in another terminal:

```zsh
export KATAAI_PRIVATE_EXPERIMENTAL_DEMO=1
backend/scripts/run_mvp.zsh worker --loop
# Or process at most one queued request:
backend/scripts/run_mvp.zsh worker --once
```

Only this explicit flag authorizes experimental generated dispatch; unset/default
rejects it. FastAPI alone never dispatches. Do not run multiple workers or the fake
worker alongside the demo. The shared session advisory lock and existing claim
logic ensure one cooperating worker/request is active. No Redis or new service.

Submit/poll through the CLI from the root:

```zsh
PYTHONPATH=backend:. .venv/bin/python -m app.demo_cli \
  backend/tests/fixtures/qwen_mvp/sales.csv \
  'What is total revenue in THB, defined as the sum of quantity times unit_price_thb for all orders?' \
  --base-url "http://127.0.0.1:$KATAAI_API_PORT"
PYTHONPATH=backend:. .venv/bin/python -m app.demo_cli \
  backend/tests/fixtures/qwen_mvp/sales.csv \
  'จำนวนสินค้าที่ขายในภูมิภาค East รวมทั้งหมดกี่ชิ้น (รวม quantity)?' \
  --base-url "http://127.0.0.1:$KATAAI_API_PORT"
```

The CLI sends multipart field `file`, `schema_version: "1.0"`, fresh client UUID,
Host, Origin and `X-KataAI-Request: 1`; it reports request/dataset UUIDs, polls and
prints the persisted answer/result/code. It never automatically reuploads or
resubmits on uncertainty. `httpx` is included by the documented dev install.

Successful response shape (actual request IDs, code and answers are in the
[recorded HTTP evidence](evidence/mvp-e2e/README.md)):

```json
{"id":"<request UUID>","status":"completed","fake":false,"run_id":"<run UUID>",
 "result":{"answer":770},"answer":"<actual Qwen explanation>","error_code":null}
```

The recorded revenue result was `{"answer":770.0}` (preserved unchanged); the
Thai result was `{"answer":6}`. Inspect code and collected
JSON before calling either a pass. Test negative questions `What is the total
profit?` and `What is the total?`: expect useful `needs_clarification`, no Job,
no fabricated result. One generation attempt per request; malformed code surfaces
as a failure, never a repaired or preset answer.

## Persistence, cleanup and limitations

Terminal statuses include `completed`, `failed`, `needs_clarification`, `unknown`;
`fake_completed` remains exclusive to fake runs. Successful actual JSON is kept
if summary fails (`SUMMARY_UNAVAILABLE`, answer null). Unknown execution retains
its UUID; do not resubmit it under another identity. GET detail includes actual
result/answer/error and generated code for review. CSV/model summaries remain
untrusted content, not verified natural-language claims.

The worker commits UUID/code before dispatch and terminal outcome before API
cleanup. Timeout/uncertain submissions are persisted as unknown and cancellation
is requested before cleanup. Existing executor journal retains provider identity,
image, host-owned result status and cleanup evidence separately from guest JSON.
Inspect the journal's `api_absent`, `cleanup`, `last_error` and
`guest_teardown_verified`. No independent node observer is configured: API
resources can be deleted, but guest teardown stays **pending**, never invented.
`executor.reconcile()` can reobserve pending resources with the same journal;
it never dispatches code or proves node teardown. Preserve evidence before any
manual reconciliation and use approved access only.

Crash recovery is intentionally minimal. A replacement worker marks abandoned
running requests unknown, does not retry them, and preserves the executor journal.
There is no attempt history, automatic replay or durable cleanup scheduler. If
cleanup fails or the process dies, inspect PostgreSQL and the journal and explicitly
reconcile the existing run; do not delete the journal or silently create a new run.
Cancellation during model generation and races at completion are not production
orchestration. Logical history hiding/deletion APIs retain their earlier scope.
No multi-user authentication, large datasets, streaming or dashboards. The React chat UI uses the same HTTP workflow.

## Tests

```zsh
PYTHONPATH=backend:. .venv/bin/python -m pytest backend/tests -q
PYTHONPATH=backend:. .venv/bin/python -B -m unittest discover -s tests/unit/runner -v
PYTHONPATH=backend:. .venv/bin/python -B -m unittest discover -s tests/unit/executor -v
```

For live database tests, provision a separate disposable DB, then opt in explicitly:

```zsh
createdb kataai_mvp_test
export TEST_DATABASE_URL="postgresql+psycopg://$USER@/kataai_mvp_test?host=/tmp"
export KATAAI_DISPOSABLE_DB=1
PYTHONPATH=backend:. .venv/bin/python -m pytest backend/tests -q --run-live-postgres
```

The suite creates/removes only its generated schemas with RESTRICT cleanup. It
does not drop the database. Existing fake-worker, upload, security, migrations,
runner/executor tests are preserved; new tests cover real persistence/fencing,
actual API serialization, worker flow with mocked model/executor, result bounds,
summary failure, timeout/cancel ordering, no dispatch on text-only response,
image checks, private CSV reads and the demo CLI's existing HTTP protocol.

## Dedicated Mac identity and manual token renewal

With explicit operator authorization, this session provisioned `kataai-mvp` in
`kata-lab`, its namespaced Role/RoleBinding, and `kataai-mvp-reader`
ClusterRole/ClusterRoleBinding. The nonsecret exact rules are in
[evidence/rbac.json](evidence/mvp-e2e/rbac.json). Cluster-scoped reads are limited
to the named RuntimeClass, named namespace and listing Calico global policies.
The administrator identity was used on the VM only for provisioning. Its
credentials were never copied to the Mac. All execution uses
`$HOME/.kube/kataai-mvp.yaml`, context `kataai-mvp`, mode 0600, through the existing
verified tunnel. No existing identities or runtime settings were changed.

The requested 8-hour TokenRequest expires **2026-11-16 02:00:46 Asia/Bangkok**
(**2026-11-15 19:00:46 UTC**), as decoded from its actual `exp` claim. Renewal is
manual; no token rotation service or persistent ServiceAccount token Secret was
created. Stop dispatch before expiry. While approved admin SSH access is available,
run this locally to issue a fresh eight-hour token without printing it:

```zsh
.venv/bin/python - <<'PY'
import base64, datetime, json, os, subprocess, tempfile
from pathlib import Path
p = Path.home() / '.kube/kataai-mvp.yaml'
# This session created JSON-form kubeconfig; JSON is valid YAML.
cfg = json.loads(p.read_text())
r = subprocess.run(['ssh', '-o', 'BatchMode=yes', 'katavm',
    'kubectl create token kataai-mvp -n kata-lab --duration=8h'],
    capture_output=True, text=True)
if r.returncode:
    raise SystemExit('Token renewal failed; credential output suppressed')
token = r.stdout.strip()
claims = json.loads(base64.urlsafe_b64decode(token.split('.')[1] + '==='))
if claims['sub'] != 'system:serviceaccount:kata-lab:kataai-mvp':
    raise SystemExit('Unexpected token identity')
next(u for u in cfg['users'] if u['name'] == 'kataai-mvp')['user'] = {'token': token}
fd, name = tempfile.mkstemp(dir=p.parent, prefix='.kataai-mvp-')
try:
    with os.fdopen(fd, 'w') as f:
        json.dump(cfg, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(name, p)
finally:
    if os.path.exists(name):
        os.unlink(name)
print('New token expiry UTC:', datetime.datetime.fromtimestamp(
    claims['exp'], datetime.timezone.utc).isoformat())
PY
```

Then repeat the recorded allow/deny checks and a trusted smoke with an idle queue.
Do not show the kubeconfig with `--raw`, print the token, check it into Git or
export it through model/debug logs. The kubeconfig is outside the repository.

## Integrated browser UI

Before launching the API, build the frontend:

```zsh
(cd frontend && npm ci && npm run build)
```

Open `http://127.0.0.1:$KATAAI_API_PORT/` at the exact configured port. API startup
mounts only the public compiled assets, behind the unchanged loopback middleware.
Start model and explicitly authorized worker in separate terminals as above.
CSV bytes are uploaded before idempotent request creation. Saved history stores
identities and the question for retry, never reconstructed sample Files/results.
See [frontend instructions](../frontend/README.md) for browser tests, failure
handling, privacy details and the opt-in real browser acceptance command.

## Persisted execution-stage timings

Migration `0007_execution_stages` adds a bounded JSONB observation timeline to
requests. Upgrade using the migration command above, then restart API and worker.
Stage updates are claim-token fenced and committed before blocking model/executor
operations. GET details expose additive `execution_stages` and `observed_at` fields.
Each stage has `name`, `started_at`, `finished_at`, `duration_ms`, `elapsed_ms` and,
when ended, `outcome`. PostgreSQL timestamps define stage boundaries. Queue wait
uses persisted creation time. Active `elapsed_ms` is sampled by the backend on GET.

The UI displays LLM generation, validation, dispatch, startup, observed container
execution, collection and summarization with actual latencies. Pod Pending/Running
observations approximate startup/execution; no exact VM boot or guest Python
instrumentation is claimed. Unobserved fast stages are omitted. Recovery closes
abandoned stage tracking as unknown, preserving history without replay. Historical
terminal requests have no retroactively fabricated timing. Cleanup still uses the
existing independent executor evidence, outside the answer latency timeline.
