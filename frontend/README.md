# KataAI frontend

Full setup, terminal commands and Kubernetes connection: [operator runbook](../docs/RUNBOOK.md).

React chat UI for the real FastAPI → PostgreSQL → local Qwen → remote Kata workflow.
See [the full application runbook](../docs/MVP_E2E.md) for native macOS, database,
model, scoped credentials, tunnel and worker setup. Generated Python executes only
through the approved executor; the UI never executes it.

## Run the integrated application

Use Node 26 or Node 22.22.2+/24.15+ and npm (the installed 24.14.1 also passed
this session's checks, with dependency engine warnings). From the repository root:

```zsh
cd frontend
npm ci
npm run build
cd ..
# Export DATABASE_URL and KATAAI_DATASET_ROOT as in docs/MVP_E2E.md.
KATAAI_API_PORT=8002 backend/scripts/run_mvp.zsh api
```

Open `http://127.0.0.1:8002/` using that exact loopback address and port. Start the
model and the explicitly authorized worker separately using the runbook. FastAPI
serves `frontend/dist`; rebuild and reload after edits. No CORS relaxation, Origin
rewriting or browser credentials for PostgreSQL/Kubernetes/model endpoints are used.
`npm run dev` is useful for UI work only; its separate origin has no API proxy.
Use the integrated server for submissions. Build **before** starting FastAPI so
its public assets mount exists.

Attach a CSV or select **Use Sample Data** (the bundled synthetic sales input),
then enter a question. Preview remains local in memory; submission uploads the
original File as multipart field `file`. Frontend intake currently accepts UTF-8
CSV up to 128 KiB, 100 columns, 10,000 rows; backend restrictions still apply.
Questions allow at most 4,096 UTF-16 code units.

The UI reports uploading, queued, processing and actual terminal states. It shows
backend answer/code/JSON/run ID when available. Completed execution with a missing
summary retains its result. Legacy fake results never count as real execution.
No stage percentages, kernel versions, Job IDs or resource consumption are inferred.

Local storage contains only session IDs, dataset/request IDs and the question
needed to retry an uncertain request with its original client UUID. It does not
contain CSV bytes, previews, generated code or results. Select saved analysis to
re-fetch its backend state. Local history deletion does not delete backend data.
Old simulated history is discarded. Restored sessions do not invent Files; ready
backend datasets can be reused, and unavailable datasets require original reupload.

## Failure handling

- Upload failure: outcome may be uncertain; no automatic upload retry. Reattach
  the original file and explicitly start a new analysis.
- Request creation failure: **Retry same request safely** reuses the exact
  dataset, question and client UUID, including after reload. No second upload.
- Polling/network failure: identity stays intact; polling/Refresh reconnects.
- Unknown execution: inspect/refresh that request; never automatically resubmit.
- Queued indefinitely: start the approved real worker; API alone never executes.
- `MODEL_GENERATION_FAILED`: check local llama.cpp and its context limits.
- Executor rejection: check approved scoped access, token expiry and tunnel/TLS.
  Renew credentials manually through the approved process; no local execution fallback.
- `FRONTEND_NOT_BUILT`: build the UI then restart the API.
- 403: use the exact configured `http://127.0.0.1:PORT`, never `localhost` or Vite
  for API submissions. Mutation requests require the existing security header.

## Verification

```zsh
npm test
npm run format:check
npm run build
npx playwright install chromium
npm run test:e2e
```

Default Playwright cases serve the compiled UI through FastAPI on 8010 and use
explicit test-only API route mocks. They cover real multipart transport, polling,
restoration and loopback security on desktop/mobile Chromium. They do not exercise
Qwen/Kata. The backend disposable PostgreSQL suite covers actual upload/storage,
idempotent creation and worker persistence with mocked model/executor boundaries.

For a **real**, already running backend/model/worker and approved remote Kata:

```zsh
KATAAI_LIVE_E2E_URL=http://127.0.0.1:8002 npm run test:e2e -- e2e/live.spec.ts --workers=1
```

This opt-in case has no API mocks and submits one synthetic CSV revenue question.
It checks the real answer (770 THB), generated code, run UUID and browser rendering.
It writes `/tmp/kataai-browser-live.json` and `/tmp/kataai-browser-live.png`. Review
PostgreSQL and executor journal/provider evidence separately; a passing browser
test alone does not establish cleanup or independent guest teardown.

Historical `evidence/` screenshots describe the earlier UI, not current acceptance.

## Execution timeline

New real requests include persisted stage timings: queue wait, dataset preparation,
LLM processing, code validation, dispatch, Kata container/VM startup, observed Kata
execution, result collection and LLM summarization. The active stage displays elapsed
latency as of the latest backend poll; ended stages display their recorded duration.
Only observed stages appear. A fast execution may finish between polls and omit
the running stage; historical requests without stage records stay without timings.

These are worker/provider observation boundaries, not exact guest Python or VM boot
instrumentation. Startup includes Kubernetes scheduling/container setup. A terminal
failure/unknown closes tracking with that outcome; it does not prove execution or
guest teardown ended. Timings survive reload and are never inferred from animation.
Apply migration `0007_execution_stages` with the existing `alembic upgrade head`
workflow and restart both API and worker when upgrading an existing installation.
