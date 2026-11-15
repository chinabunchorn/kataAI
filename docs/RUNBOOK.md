# KataAI operator runbook

Run the integrated React → FastAPI → PostgreSQL → local Qwen → remote Kubernetes/Kata
application on native macOS ARM64. Commands use **zsh** and this checkout:
`/Users/akaradech/Projects/kataAI`. Replace that path if your checkout is elsewhere.

This runbook uses the existing approved Kubernetes lab; it does not install a new
cluster, change RBAC, rebuild the runner, or renew credentials automatically.
Generated Python executes only in the approved remote Kata runtime.

## 1. Services and ports

| Component                             | Runs on                      | Address / configuration                                   |
| ------------------------------------- | ---------------------------- | --------------------------------------------------------- |
| React production UI + FastAPI         | Mac                          | `http://127.0.0.1:8002/`                                  |
| PostgreSQL 16                         | Mac                          | Unix socket `/tmp`, database `kataai_mvp_demo`            |
| Qwen 3.5 9B through llama.cpp / Metal | Mac                          | `http://127.0.0.1:8080`                                   |
| Real worker                           | Mac                          | One process; PostgreSQL queue; persistent local journal   |
| SSH Kubernetes tunnel                 | Mac → approved VM            | `127.0.0.1:16443` → VM `127.0.0.1:6443`                   |
| Kubernetes / Kata                     | Existing OpenStack Ubuntu VM | Namespace `kata-lab`, RuntimeClass `kata-qemu-runtime-rs` |
| Runner                                | Remote Kata, linux/amd64     | Pinned Runner 0.1.1 image below                           |

```text
docker.io/kataai/runner@sha256:6a682ed00f47fc27c18eb3abd9e3448960133433265ec6442339c9484d246bf9
```

The frontend is served by FastAPI. There is **no separate Vite process** in the
normal workflow. Model calls, database access and Kubernetes credentials remain
on the Mac, outside the browser. The API alone does not process queued requests.

## 2. One-time prerequisites

### 2.1 Obtain the correct checkout

For the current machine:

```zsh
cd /Users/akaradech/Projects/kataAI
git branch --show-current
git status --short
```

Use `integration/mvp-e2e`. If needed, switch with a clean working tree:

```zsh
git switch integration/mvp-e2e
```

The frontend integration and timing changes were committed locally and have not
been pushed as part of this work. A fresh clone from GitHub may therefore lack
these changes until publication is separately approved. Use this checkout or an
approved transfer of the same revision. Confirm these files exist:

```zsh
test -f frontend/src/lib/api.ts
test -f backend/app/kata_demo_worker.py
test -f backend/migrations/versions/0007_execution_stages.py
```

### 2.2 Install or select native tools

Required: Homebrew (if using the install commands below), Git, SSH, OpenSSL with
`-verify_ip`, `uv`, Python 3.12, PostgreSQL 16, llama.cpp with Qwen3.5/Metal support,
kubectl, and Node/npm. The frontend declares Node **26+**, **24.15+ within 24.x**,
or **22.22.2+ within 22.x**.

On a machine with Homebrew already configured:

```zsh
brew install uv postgresql@16 llama.cpp kubernetes-cli
export PATH="$(brew --prefix postgresql@16)/bin:$PATH"
uv python install 3.12
```

Use your existing Node version manager to select a supported version. For example,
if `fnm` is already installed:

```zsh
fnm install 26
fnm use 26
```

Verify the selected tools:

```zsh
uname -sm                       # expected: Darwin arm64
uv --version
node --version
npm --version
psql --version
kubectl version --client
openssl version
llama-server --version
llama-server --list-devices      # expected Metal device, e.g. MTL0: Apple M2
```

The startup script rejects non-ARM64 macOS and Python other than 3.12. An older
llama.cpp build may not support the Qwen3.5 model/template even if it launches.

### 2.3 Install Python and frontend dependencies

From the repository root, create the environment only if it does not already exist:

```zsh
cd /Users/akaradech/Projects/kataAI
# First setup only:
uv venv --python 3.12 .venv

# First setup and whenever backend dependencies change:
uv pip install --python .venv/bin/python -e 'backend[dev]'
.venv/bin/python --version

# First setup and whenever package-lock.json changes:
npm --prefix frontend ci
```

No virtualenv activation is needed; commands use `.venv/bin/python` explicitly.

### 2.4 Provision the model and existing infrastructure access

Obtain the approved model weights through your model provisioning process and
place them at the configured path, for example:

```text
$HOME/Models/Qwen3.5-9B-Q4_K_M.gguf
```

Weights are not included in Git. The tested GGUF is about 5.68 GB. The startup
configuration uses a 4096-token context and one slot on the 16 GB MacBook Air.
Do not rebuild the remote linux/amd64 runner for Apple Silicon.

Obtain these existing access artifacts through the approved infrastructure process:

- SSH access to the lab VM, normally the existing `katavm` SSH alias.
- Application-scoped kubeconfig, normally `$HOME/.kube/kataai-mvp.yaml`, context
  `kataai-mvp`, authenticated as `system:serviceaccount:kata-lab:kataai-mvp`.
- The real cluster CA certificate, normally `$HOME/.kube/katavm-ca.crt`.
- An unexpired application token and permission to run the private experimental demo.

If the SSH alias is absent, configure it in your personal `~/.ssh/config` using
values supplied by your operator. Example structure (replace every placeholder):

```sshconfig
Host katavm
    HostName <approved-vm-address>
    User <approved-ssh-user>
    IdentityFile <path-to-existing-private-key>
    IdentitiesOnly yes
```

Verify the VM host key through the normal trusted process. Check SSH connectivity:

```zsh
ssh -o BatchMode=yes katavm true
```

The application kubeconfig must select `https://127.0.0.1:16443`, retain the real
CA, and use a valid matching server certificate. The recorded lab certificate
includes `127.0.0.1` and `katavm`. Never substitute the VM public address for TLS
verification unless its certificate actually includes that address.

The application identity needs create/get/delete Jobs and ConfigMaps, get/list/delete
Pods, get/list Events, and the scoped runtime/namespace/network-policy reads used by
preflight. It does not need cluster-admin or Secrets access. Exact approved rules:
[RBAC evidence](evidence/mvp-e2e/rbac.json). Missing access must be resolved through
the operator; do not grant yourself permissions or fall back to an admin context.

## 3. Create a private local configuration

The project does not automatically load `.env`. These instructions create an
explicitly sourced, ignored zsh configuration under `.mvp-demo/`.

```zsh
cd /Users/akaradech/Projects/kataAI
umask 077
mkdir -p .mvp-demo/datasets .mvp-demo/state
chmod 700 .mvp-demo .mvp-demo/datasets .mvp-demo/state

# Create once; on later runs edit the existing file rather than overwrite it.
cat > .mvp-demo/env.zsh <<'ENV'
# Source only after cd to the repository root.
export KATAAI_REPO="$PWD"
export PATH="$(brew --prefix postgresql@16)/bin:$PATH"
export PYTHONPATH="$KATAAI_REPO/backend:$KATAAI_REPO"
export DATABASE_URL="postgresql+psycopg://$USER@/kataai_mvp_demo?host=/tmp"
export KATAAI_DATASET_ROOT="$KATAAI_REPO/.mvp-demo/datasets"
export KATAAI_JOURNAL="$KATAAI_REPO/.mvp-demo/state/kata-runs.sqlite3"
export KATAAI_API_PORT=8002
export KATAAI_MODEL_PATH="$HOME/Models/Qwen3.5-9B-Q4_K_M.gguf"
export KATAAI_KUBECONFIG="$HOME/.kube/kataai-mvp.yaml"
export KATAAI_KUBE_CONTEXT=kataai-mvp
export KATAAI_CLUSTER_CA="$HOME/.kube/katavm-ca.crt"
umask 077
ENV
chmod 600 .mvp-demo/env.zsh
source .mvp-demo/env.zsh
```

Adjust the database role/socket, model path, approved kubeconfig/context and CA
path to your actual installation. This example uses local socket authentication
as your macOS user; it does not create a database role or assume a password.
Keep credentials out of commands committed to Git. The application rejects all
inherited `PG*` variables, even empty ones; identify conflicting variable **names**
without printing their values:

```zsh
.venv/bin/python - <<'PY'
import os
print('\n'.join(sorted(name for name in os.environ if name.startswith('PG'))))
PY
```

Unset only the conflicting variables in this shell, or use a clean terminal, and
keep connection configuration explicit in `DATABASE_URL`.

Preserve the same dataset directory and executor journal across restarts. The
journal contains code, input data and execution evidence; do not delete it to
recover an uncertain request. Existing journal files must be private regular files
owned by your user. Neither `.mvp-demo/` nor kubeconfigs/weights belong in Git.

## 4. PostgreSQL and schema

Start the existing Homebrew PostgreSQL service if it is not already running:

```zsh
cd /Users/akaradech/Projects/kataAI
source .mvp-demo/env.zsh
brew services list
# Only if the intended PostgreSQL 16 service is stopped:
brew services start postgresql@16
pg_isready -h /tmp -p 5432
```

On first setup, create the dedicated demo database once:

```zsh
createdb -h /tmp -U "$USER" kataai_mvp_demo
```

If it already exists, reuse it. Do not recreate or drop it. Inspect the target
before migration, then apply the current schema:

```zsh
psql -h /tmp -U "$USER" -d kataai_mvp_demo \
  -c 'SELECT current_database(), current_user;'
(cd backend && ../.venv/bin/python -m alembic current)
(cd backend && ../.venv/bin/python -m alembic upgrade head)
(cd backend && ../.venv/bin/python -m alembic current)
```

Current head is `0007_execution_stages`. It follows `0006_real_results` and adds
persisted stage timings. For an upgrade, first let the existing worker finish and
stop it; restart both API and worker after migration. Keep the existing database,
datasets and journal. No migration or credential provisioning runs automatically
when FastAPI starts.

## 5. Build the frontend

Build **before starting FastAPI**; the API mounts the compiled public assets at startup:

```zsh
cd /Users/akaradech/Projects/kataAI
source .mvp-demo/env.zsh
npm --prefix frontend run build
```

The output is `frontend/dist/`. FastAPI serves it on the same origin as `/v1/*`.
After frontend edits, rebuild and reload the browser. If the API started before
assets existed, restart it after building.

## 6. Daily startup: four terminals

First check for existing listeners and processes so you do not launch duplicates:

```zsh
lsof -nP -iTCP:8002 -sTCP:LISTEN
lsof -nP -iTCP:8080 -sTCP:LISTEN
lsof -nP -iTCP:16443 -sTCP:LISTEN
ps -axo pid,command | rg 'app.kata_demo_worker|uvicorn app.main|llama-server'
```

Reuse known, correctly configured services. A listening port alone does not prove
it belongs to the right service. Do not stop another application to free a port.
Only one real worker should run, with the same database/root/journal configuration.
Do not run `fake_worker` or `qwen_demo_worker` alongside it.

### Terminal 1 — Kubernetes SSH tunnel

```zsh
cd /Users/akaradech/Projects/kataAI
source .mvp-demo/env.zsh
ssh -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -N -L 127.0.0.1:16443:127.0.0.1:6443 katavm
```

Keep this terminal running. If the correct existing tunnel already owns 16443,
reuse it. The bind is loopback-only; no public API exposure is needed.

### Terminal 2 — local Qwen model

```zsh
cd /Users/akaradech/Projects/kataAI
source .mvp-demo/env.zsh
test -f "$KATAAI_MODEL_PATH"
backend/scripts/run_mvp.zsh model
```

The launcher selects `MTL0`, offloads layers, uses one slot/4096 tokens, enables
Jinja tool parsing and binds `127.0.0.1:8080`. The worker defaults to
`http://127.0.0.1:8080/v1/chat/completions`. Avoid verbose prompt logs for private
data. Model generation and summarization each have the adapter's 120-second bound.

### Terminal 3 — integrated frontend and FastAPI

```zsh
cd /Users/akaradech/Projects/kataAI
source .mvp-demo/env.zsh
backend/scripts/run_mvp.zsh api
```

Open `http://127.0.0.1:8002/` (or the exact port in `KATAAI_API_PORT`). Use literal
`127.0.0.1`, not `localhost`, the VM address or a separate Vite origin. Keep the API
bound to loopback. Host/Origin checks and `X-KataAI-Request: 1` remain enforced.

### Terminal 4 — connection checks, then real worker

```zsh
cd /Users/akaradech/Projects/kataAI
source .mvp-demo/env.zsh
curl --fail-with-body --noproxy '*' "http://127.0.0.1:$KATAAI_API_PORT/health"
curl --fail-with-body --noproxy '*' http://127.0.0.1:8080/health
```

Verify the tunnel's certificate and selected Kubernetes context:

```zsh
test -r "$KATAAI_KUBECONFIG"
test -r "$KATAAI_CLUSTER_CA"
chmod 600 "$KATAAI_KUBECONFIG"
openssl s_client -connect 127.0.0.1:16443 \
  -CAfile "$KATAAI_CLUSTER_CA" -verify_ip 127.0.0.1 \
  -verify_return_error </dev/null

kubectl --kubeconfig "$KATAAI_KUBECONFIG" --context "$KATAAI_KUBE_CONTEXT" \
  config view --minify -o jsonpath='{.clusters[0].cluster.server}{"\n"}'
kubectl --kubeconfig "$KATAAI_KUBECONFIG" --context "$KATAAI_KUBE_CONTEXT" \
  --request-timeout=20s get namespace kata-lab -o name
kubectl --kubeconfig "$KATAAI_KUBECONFIG" --context "$KATAAI_KUBE_CONTEXT" \
  --request-timeout=20s get runtimeclass kata-qemu-runtime-rs \
  -o jsonpath='{.handler}{"\n"}'
kubectl --kubeconfig "$KATAAI_KUBECONFIG" --context "$KATAAI_KUBE_CONTEXT" \
  auth can-i create jobs.batch -n kata-lab
kubectl --kubeconfig "$KATAAI_KUBECONFIG" --context "$KATAAI_KUBE_CONTEXT" \
  auth can-i create configmaps -n kata-lab
kubectl --kubeconfig "$KATAAI_KUBECONFIG" --context "$KATAAI_KUBE_CONTEXT" \
  --request-timeout=20s get networkpolicy default-deny -n kata-lab -o yaml
```

Expected: certificate verification succeeds; server is `https://127.0.0.1:16443`;
namespace exists; handler is `kata-qemu-runtime-rs`; both creation checks return
`yes`; default-deny policy is present. The worker additionally checks the full
Kubernetes/Calico policy evidence on dispatch. A failed check blocks execution;
do not bypass CA verification or widen policy/RBAC.

For a first setup or changed connection, perform the trusted smoke in section 7
**before** starting the worker. On an already verified setup, start the worker
only when private experimental execution is authorized:

```zsh
export KATAAI_PRIVATE_EXPERIMENTAL_DEMO=1
backend/scripts/run_mvp.zsh worker --loop
```

Keep this terminal running. To process at most one queued request instead:

```zsh
# Alternative to --loop, not a second worker:
backend/scripts/run_mvp.zsh worker --once
```

Setting the flag is the operator's explicit opt-in; it is not in the shared config
or enabled by API startup. If approval/access is absent, leave the flag unset and
the worker stopped. No local Python execution fallback exists.

## 7. First-connection trusted Kata smoke

Run with API/tunnel available, the real worker **stopped**, and no queued/running/
cancel-requested requests. This is a separate fixed, hand-written synthetic probe;
it is not a model-result fallback.

```zsh
cd /Users/akaradech/Projects/kataAI
source .mvp-demo/env.zsh
psql -h /tmp -U "$USER" -d kataai_mvp_demo -c \
  "SELECT id,status FROM request_intents WHERE status IN ('queued','running','cancel_requested');"

curl --fail-with-body --noproxy '*' \
  -H "Origin: http://127.0.0.1:$KATAAI_API_PORT" \
  -H 'X-KataAI-Request: 1' \
  -F 'file=@backend/tests/fixtures/qwen_mvp/sales.csv;type=text/csv' \
  "http://127.0.0.1:$KATAAI_API_PORT/v1/datasets" \
  -o .mvp-demo/state/smoke-upload.json

KATAAI_SMOKE_DATASET_ID="$(.venv/bin/python -c \
  'import json; print(json.load(open(".mvp-demo/state/smoke-upload.json"))["dataset_id"])')"

KATAAI_PRIVATE_EXPERIMENTAL_DEMO=1 .venv/bin/python -m app.kata_smoke \
  --dataset-id "$KATAAI_SMOKE_DATASET_ID" \
  --kubeconfig "$KATAAI_KUBECONFIG" --context "$KATAAI_KUBE_CONTEXT" \
  --journal "$KATAAI_JOURNAL"
```

Stop if upload fails; do not parse a stale previous response. Keep the printed
request UUID and inspect it as in section 9. Expected result: four rows and the
columns `order_id`, `region`, `quantity`, `unit_price_thb`. Its summary is deliberately
unavailable (`SUMMARY_UNAVAILABLE`); that does not mean execution failed. The smoke
refuses a busy queue. After it succeeds, start the real worker in Terminal 4.

## 8. Use the browser

1. Open `http://127.0.0.1:8002/`.
2. Attach a real UTF-8 CSV or choose **Use Sample Data** (clearly synthetic input).
3. Optionally use **Preview CSV**.
4. Ask: `What is total revenue in THB, defined as the sum of quantity times unit_price_thb for all orders?`
5. Observe the real status and timing timeline: queue, dataset preparation, LLM
   processing, validation, dispatch, Kata startup, observed execution, collection,
   and summarization.
6. Review actual generated Python, validated JSON, answer, request ID and run ID.

The bundled synthetic fixture's independent answer is **770 THB**. East-region
quantity is **6**. These are acceptance expectations, never production fallbacks.
Qwen can generate incorrect or failing code; preserve failures rather than editing
its code or relabeling the result as successful.

Active time is sampled at the latest backend poll. Startup/execution durations
are Kubernetes observation spans, not exact VM boot or Python CPU timings. Fast
unobserved stages are omitted. Saved analysis reloads backend states; it never
reconstructs a user's file from sample bytes. Missing datasets require reupload.
Local storage keeps identifiers/questions for recovery, not CSV previews/code/results.

Frontend intake is currently 128 KiB, UTF-8, at most 100 columns/10,000 rows; backend
restrictions also apply. Runner caps include CSV 512 KiB, code 16 KiB, result JSON
2048 bytes, script 30 seconds, and an independent Job deadline of 120 seconds.

## 9. CLI/API submission and request inspection

### 9.1 One-command real upload, submission and polling

With the real worker running, use another terminal:

```zsh
cd /Users/akaradech/Projects/kataAI
source .mvp-demo/env.zsh
.venv/bin/python -m app.demo_cli \
  backend/tests/fixtures/qwen_mvp/sales.csv \
  'What is total revenue in THB, defined as the sum of quantity times unit_price_thb for all orders?' \
  --base-url "http://127.0.0.1:$KATAAI_API_PORT"
```

Each invocation creates a **new logical request**. Do not rerun this command to
recover a timeout or unknown outcome. Keep its printed request/dataset UUIDs.

### 9.2 Inspect the same request repeatedly

Replace the placeholder with the saved request UUID:

```zsh
KATAAI_REQUEST_ID='<saved-request-uuid>'
curl --fail-with-body --noproxy '*' \
  "http://127.0.0.1:$KATAAI_API_PORT/v1/requests/$KATAAI_REQUEST_ID" \
  -o .mvp-demo/state/request-detail.json
.venv/bin/python -m json.tool .mvp-demo/state/request-detail.json
```

GET is read-only and may be repeated. The response includes actual `status`,
`answer`, `result`, `code`, `run_id`, `error_code`, and recorded `execution_stages`
when available. Queued/running/cancel_requested are pending. `completed`, `failed`,
`needs_clarification`, `cancelled`, `unknown` and legacy `fake_completed` are terminal
for frontend polling. A fake response is never a real execution pass.

A completed request with `SUMMARY_UNAVAILABLE` retains its real JSON. An unknown
request may have executed; preserve its IDs/journal and investigate without
resubmitting. On uncertain browser creation, **Retry same request safely** retains
its original client UUID and exact input. Uploads are not automatically retried.

### 9.3 Manual API protocol and explicit idempotent retry

If you need to call the endpoints yourself, upload the original bytes:

```zsh
curl --fail-with-body --noproxy '*' \
  -H "Origin: http://127.0.0.1:$KATAAI_API_PORT" \
  -H 'X-KataAI-Request: 1' \
  -F 'file=@backend/tests/fixtures/qwen_mvp/sales.csv;type=text/csv' \
  "http://127.0.0.1:$KATAAI_API_PORT/v1/datasets" \
  -o .mvp-demo/state/manual-upload.json
```

Only after that succeeds, create the payload **once per new logical request**:

```zsh
.venv/bin/python - <<'PY'
import json
from pathlib import Path
from uuid import uuid4
payload_path = Path('.mvp-demo/state/manual-request.json')
if payload_path.exists():
    raise SystemExit('Payload already exists; inspect/reuse its identity, do not overwrite it.')
dataset = json.loads(Path('.mvp-demo/state/manual-upload.json').read_text())
payload = {'schema_version': '1.0', 'client_request_id': str(uuid4()),
           'dataset_id': dataset['dataset_id'],
           'question': 'What is total revenue in THB, defined as the sum of quantity times unit_price_thb for all orders?'}
with payload_path.open('x') as stream:
    json.dump(payload, stream)
PY

curl --fail-with-body --noproxy '*' \
  -H "Origin: http://127.0.0.1:$KATAAI_API_PORT" \
  -H 'X-KataAI-Request: 1' -H 'Content-Type: application/json' \
  --data-binary @.mvp-demo/state/manual-request.json \
  "http://127.0.0.1:$KATAAI_API_PORT/v1/requests"
```

If this POST's response is lost, explicitly repeat **only that same curl POST with
the same saved payload**. Do not regenerate its UUID/question/dataset. HTTP 201
means created; HTTP 200 can mean the same idempotent request already existed.
Neither means execution completed. Preserve the returned `id` and poll it.
For a separate analysis, use a separately named payload file; retain old evidence.

## 10. Inspect Kubernetes and cleanup evidence

Read the actual `run_id` from the request response. Job names are `ka-` followed
by that UUID without hyphens. Do not invent a Job identifier from UI timing.

```zsh
KATAAI_RUN_ID='<actual-run-uuid>'
KATAAI_RUN_NAME="ka-${KATAAI_RUN_ID//-/}"

kubectl --kubeconfig "$KATAAI_KUBECONFIG" --context "$KATAAI_KUBE_CONTEXT" \
  --request-timeout=20s get job "$KATAAI_RUN_NAME" -n kata-lab \
  --ignore-not-found -o json
kubectl --kubeconfig "$KATAAI_KUBECONFIG" --context "$KATAAI_KUBE_CONTEXT" \
  --request-timeout=20s get pods -n kata-lab \
  -l "kataai-m3-run=$KATAAI_RUN_NAME" -o json
kubectl --kubeconfig "$KATAAI_KUBECONFIG" --context "$KATAAI_KUBE_CONTEXT" \
  --request-timeout=20s get configmap "$KATAAI_RUN_NAME-inputs" -n kata-lab \
  --ignore-not-found -o name
```

Inspect the actual Job runtime class and Pod container image identity when present.
After cleanup, named Job/ConfigMap reads should print nothing; Pods should have an
empty `items` list. The scoped identity need not be allowed to list all Jobs or
ConfigMaps; use the named reads above. Do not print input ConfigMap data.

Read selected local journal fields without modifying it or dumping staged CSV/code:

```zsh
export KATAAI_RUN_ID
.venv/bin/python - <<'PY'
import json, os, sqlite3
from pathlib import Path
journal = Path(os.environ['KATAAI_JOURNAL']).resolve()
with sqlite3.connect(journal.as_uri() + '?mode=ro', uri=True) as connection:
    row = connection.execute('SELECT record FROM runs WHERE run_id=?',
                             (os.environ['KATAAI_RUN_ID'],)).fetchone()
if row is None:
    raise SystemExit('Run not found in this journal; preserve the request identity.')
record = json.loads(row[0])
print(json.dumps({key: record.get(key) for key in (
    'request_id', 'run_id', 'state', 'job_uid', 'image', 'api_absent',
    'cleanup', 'guest_teardown_verified', 'last_error')}, indent=2))
PY
```

API absence is **not** independent sandbox/VM teardown proof. Without the separate
node observer, `cleanup=pending` and `guest_teardown_verified=false` are expected,
even after resources disappear. Retain evidence; do not delete the namespace,
journal, unrelated resources, or manually replay an unknown run. Reconciliation
requires the existing journal/identity and deliberate operator investigation; see
[executor recovery](../infra/executor/README.md#persistence-recovery-and-cancellation).

## 11. Credential expiry and manual renewal

Check current credentials before dispatch. The expiration recorded in earlier
evidence is historical; do not assume it still describes the current kubeconfig.
The following check supports the existing **JSON-form kubeconfig** (JSON is valid
YAML), reads only its selected token privately, and prints only expiry/status:

```zsh
.venv/bin/python - <<'PY'
import base64, datetime, json, os
from pathlib import Path
from zoneinfo import ZoneInfo
try:
    cfg = json.loads(Path(os.environ['KATAAI_KUBECONFIG']).read_text())
    context = next(c['context'] for c in cfg['contexts'] if c['name'] == os.environ['KATAAI_KUBE_CONTEXT'])
    user = next(u['user'] for u in cfg['users'] if u['name'] == context['user'])
    token = user['token']
    claims = json.loads(base64.urlsafe_b64decode(token.split('.')[1] + '==='))
    assert claims['sub'] == 'system:serviceaccount:kata-lab:kataai-mvp'
    expires = datetime.datetime.fromtimestamp(claims['exp'], datetime.timezone.utc)
except Exception:
    raise SystemExit('Cannot inspect this credential format; use the approved credential process.') from None
print('Expiry Asia/Bangkok:', expires.astimezone(ZoneInfo('Asia/Bangkok')).isoformat())
print('Expired:', expires <= datetime.datetime.now(datetime.timezone.utc))
PY
```

Decoding JWT claims is a local expiry check, not authentication; actual TLS-verified
Kubernetes requests still validate the credential. For YAML/exec-plugin credentials,
use the operator's supported inspection/renewal process rather than rewriting them.

Stop the worker before expiry/renewal. Only an authorized operator with the existing
approved administrative SSH access may use this manual renewal procedure for the
existing JSON-form kubeconfig. It issues a token for the existing identity; it does
not create identities, RBAC or a persistent token Secret:

```zsh
.venv/bin/python - <<'PY'
import base64, datetime, json, os, subprocess, tempfile
from pathlib import Path
from zoneinfo import ZoneInfo
path = Path(os.environ['KATAAI_KUBECONFIG'])
try:
    cfg = json.loads(path.read_text())
    context = next(c['context'] for c in cfg['contexts'] if c['name'] == os.environ['KATAAI_KUBE_CONTEXT'])
    selected = next(u for u in cfg['users'] if u['name'] == context['user'])
    response = subprocess.run(['ssh', '-o', 'BatchMode=yes', 'katavm',
        'kubectl create token kataai-mvp -n kata-lab --duration=8h'],
        capture_output=True, text=True, timeout=30)
    if response.returncode:
        raise ValueError()
    token = response.stdout.strip()
    claims = json.loads(base64.urlsafe_b64decode(token.split('.')[1] + '==='))
    assert claims['sub'] == 'system:serviceaccount:kata-lab:kataai-mvp'
    assert claims['exp'] > datetime.datetime.now(datetime.timezone.utc).timestamp()
    selected['user'] = {'token': token}
except Exception:
    raise SystemExit('Renewal failed; credential output suppressed.') from None
fd, name = tempfile.mkstemp(dir=path.parent, prefix='.kataai-token-')
try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(cfg, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(name, path)
finally:
    if os.path.exists(name):
        os.unlink(name)
expires = datetime.datetime.fromtimestamp(claims['exp'], datetime.timezone.utc)
print('New expiry Asia/Bangkok:', expires.astimezone(ZoneInfo('Asia/Bangkok')).isoformat())
PY
```

Then repeat the TLS/context/permission checks and, with an idle queue, the trusted
smoke before restarting the real worker. Never print a token, use `config view
--raw` for troubleshooting output, copy admin kubeconfigs to the Mac, or place
credentials in frontend configuration. If renewal is unauthorized or fails, keep
dispatch stopped and obtain access through the approved process.

## 12. Tests and verification commands

### 12.1 Frontend unit tests, formatting and production build

```zsh
cd /Users/akaradech/Projects/kataAI
source .mvp-demo/env.zsh
npm --prefix frontend test
npm --prefix frontend run format:check
npm --prefix frontend run build
```

### 12.2 Backend and infrastructure unit tests

```zsh
.venv/bin/python -m pytest backend/tests -q
.venv/bin/python -B -m unittest discover -s tests/unit/runner -v
.venv/bin/python -B -m unittest discover -s tests/unit/executor -v
.venv/bin/python -m ruff check backend
zsh -n backend/scripts/run_mvp.zsh
git diff --check
```

The default backend run skips explicit disposable-PostgreSQL tests. Runner/executor
unit tests do not dispatch generated code or require the live lab. Broad
`ruff check backend infra tests` also scans historical infrastructure/test files;
48 pre-existing findings were recorded separately from the clean backend check.

### 12.3 Disposable PostgreSQL integration tests

Create a separate test database once, never use the demo database here:

```zsh
createdb -h /tmp -U "$USER" kataai_mvp_test   # first setup only
export TEST_DATABASE_URL="postgresql+psycopg://$USER@/kataai_mvp_test?host=/tmp"
export KATAAI_DISPOSABLE_DB=1
.venv/bin/python -m pytest backend/tests -q --run-live-postgres
unset KATAAI_DISPOSABLE_DB TEST_DATABASE_URL
```

The suite creates/removes only its generated schemas with RESTRICT cleanup; it
does not drop the database. It includes actual multipart/API/storage/queue/worker
persistence with explicitly mocked model/executor boundaries. That is distinct
from live Qwen/Kata acceptance.

### 12.4 Deterministic desktop/mobile browser tests

```zsh
(cd frontend && npx playwright install chromium)
npm --prefix frontend run build
npm --prefix frontend run test:e2e -- e2e/workspace.spec.ts
```

This starts a temporary FastAPI static/security server on **8010**, serving the
compiled UI. API responses are explicitly mocked in the test suite. Keep port
8010 free. These tests do not require the worker/model/remote cluster.

Optional: place browser downloads outside the default cache by exporting
`PLAYWRIGHT_BROWSERS_PATH=/tmp/kataai-playwright` **both during install and tests**.
Concurrent Playwright invocations need different `--output` directories.

### 12.5 Real browser-to-Kata acceptance

With all real services and approved credentials running:

```zsh
KATAAI_LIVE_E2E_URL="http://127.0.0.1:$KATAAI_API_PORT" \
  npm --prefix frontend run test:e2e -- e2e/live.spec.ts --workers=1 \
  --output=/tmp/kataai-live-acceptance
```

This creates one real synthetic request, checks 770 THB, actual generated code,
real run identity and persisted stage timings. No API/model/executor mocks are
used. The test saves `/tmp/kataai-browser-live.json` and
`/tmp/kataai-browser-live.png`. Each invocation is a new execution, not recovery.
Inspect cleanup separately using section 10. Keep failed outcomes as evidence.
Recorded real frontend and timing verification: [FRONTEND.md](evidence/mvp-e2e/FRONTEND.md)
and [STAGES.md](evidence/mvp-e2e/STAGES.md).

## 13. Frontend-only development

For isolated UI editing:

```zsh
npm --prefix frontend run dev -- --port 5173
```

This Vite origin has **no backend proxy**. Submissions require the integrated
FastAPI origin. To test real submissions after editing, run:

```zsh
npm --prefix frontend run build
# Start/restart FastAPI only if needed, then reload http://127.0.0.1:8002/.
```

Do not rewrite Origin headers or relax backend Host checks to connect Vite.
`npm run preview` is likewise a standalone frontend preview, not the integrated app.

## 14. Shutdown and next startup

1. Stop accepting new submissions; inspect current pending work:

   ```zsh
   psql -h /tmp -U "$USER" -d kataai_mvp_demo -c \
     "SELECT id,status,run_id FROM request_intents WHERE status IN ('queued','running','cancel_requested');"
   ```

2. Let active work finish and inspect its result/cleanup. For an intentional
   cancellation, retain the request ID and send the supported cooperative request:

   ```zsh
   curl --fail-with-body --noproxy '*' \
     -H "Origin: http://127.0.0.1:$KATAAI_API_PORT" -H 'X-KataAI-Request: 1' \
     -X POST "http://127.0.0.1:$KATAAI_API_PORT/v1/requests/$KATAAI_REQUEST_ID/cancel"
   ```

   Cancellation may remain pending or become unknown; do not infer guest teardown
   from the response. Preserve PostgreSQL/journal evidence and inspect the same run.

3. With the queue idle, press **Ctrl+C in the worker terminal**. Then:

   ```zsh
   unset KATAAI_PRIVATE_EXPERIMENTAL_DEMO
   ```

4. Press **Ctrl+C** in the API and model terminals you started.
5. Stop the SSH tunnel last, after resource/cleanup inspection, with **Ctrl+C**.
6. Leave shared PostgreSQL running. If this PostgreSQL service is exclusively for
   this project and all clients are stopped, optionally run:

   ```zsh
   brew services stop postgresql@16
   ```

Do not use broad `pkill`, delete cluster resources by namespace, or remove the
journal/database/datasets as a shutdown step. A forced worker interruption can
leave a running request; its replacement marks abandoned work unknown and closes
its observation timeline. It never silently replays it.

For the next startup: source the existing config in each terminal, check ports,
start PostgreSQL if needed, check token expiry, build if changed, then follow
section 6. Dependencies and database creation are not daily steps. After code
updates, install changed dependencies, migrate deliberately with the worker
stopped, rebuild, and restart the API/worker.

## 15. Troubleshooting

| Symptom                                              | Check / action                                                                                                                                                   |
| ---------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `FRONTEND_NOT_BUILT`, missing JS assets              | Build `frontend/dist` before API startup, restart API if assets were absent, reload.                                                                             |
| Browser/API 403                                      | Exact `http://127.0.0.1:PORT`, matching `KATAAI_API_PORT`; curl mutation needs Origin and `X-KataAI-Request: 1`. Do not use Vite/localhost or weaken middleware. |
| `/health` succeeds but upload/request is 503         | Health only establishes API liveness. Check explicit DB URL, DB availability/schema, owner-private dataset root and inherited `PG*` names.                       |
| Schema/column missing                                | Confirm intended demo database; stop idle worker, run `alembic upgrade head`, restart API and worker.                                                            |
| `DATASET_CONFIGURATION_ERROR` / `UPLOAD_UNAVAILABLE` | Absolute dataset root, directory exists, correct owner, mode 0700; local DB socket/role available. Do not use a symlink or shared directory.                     |
| CSV rejected                                         | UTF-8 `.csv`, valid unique headers/row widths; frontend max 128 KiB. Backend upload/runner restrictions remain authoritative.                                    |
| Request remains queued                               | Check real worker process, matching DB/root/journal and explicit opt-in. API alone cannot execute.                                                               |
| `MODEL_GENERATION_FAILED`                            | Check model `/health`, Metal/model support, tool template, context size and adapter timeout. Do not execute generated code locally to diagnose.                  |
| `SCRIPT_FAILED`                                      | Actual generated code failed in Kata. Inspect saved code/error; retain this failure. No automatic repair/replay.                                                 |
| `SUMMARY_UNAVAILABLE` with completed                 | Actual execution succeeded; inspect the retained JSON. Check model availability/context for the summary separately.                                              |
| Tunnel bind fails                                    | Inspect existing 16443 listener. Reuse only the known correct tunnel; do not stop unrelated processes.                                                           |
| TLS verification fails                               | Check tunnel destination, trusted real CA and certificate SAN. Do not use `-k` or insecure-skip-tls-verify.                                                      |
| Unauthorized / token expired                         | Stop dispatch; use approved manual renewal, then repeat connection checks. No admin credential fallback.                                                         |
| Forbidden / missing policy evidence                  | Check scoped identity and exact policy read rights with the operator. Do not grant permissions or change default-deny for a demo.                                |
| Job/ConfigMap listing Forbidden                      | Listing may intentionally be disallowed. Use exact named reads and scoped Pod listing from section 10.                                                           |
| `unknown` / network failure after POST               | Keep request/client/run IDs; re-fetch/reconcile the same identity. Browser safe retry reuses its original payload. Never rerun CLI to recover.                   |
| No timing on old history                             | Historical terminal records were not instrumented. Do not backfill fabricated durations.                                                                         |
| Running stage missing                                | The task may finish between provider polls. Only observed stages are recorded.                                                                                   |
| Cleanup pending, API resources absent                | Independent guest teardown observer is absent. Keep pending evidence; API absence alone is insufficient.                                                         |
| Browser test cannot launch                           | Install Chromium for the pinned Playwright version; use the same browser-cache path for install and test.                                                        |
| Node engine warnings                                 | Select a version supported by `frontend/package.json`, then reinstall pinned dependencies with `npm ci`.                                                         |

For architectural details and historical evidence, see [MVP_E2E.md](MVP_E2E.md).
