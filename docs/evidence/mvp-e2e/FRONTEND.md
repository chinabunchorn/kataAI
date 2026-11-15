# Browser integration verification — 2026-11-15

Frontend source `origin/frontend` at `e7f3648` was merged locally into
`integration/mvp-e2e` from `db53f69`, merge commit `eaa7b2b`. Main was not modified;
nothing was pushed. Integration changes preserve the backend worker/model and
all infrastructure source/tests unchanged from `db53f69`.

The React production build is served from the integrated FastAPI instance on
`http://127.0.0.1:8002/`. Existing model (8080), PostgreSQL demo database, single
real worker, scoped application kubeconfig/context and TLS-verified tunnel were
reused. No identity/permission/token/runtime/image changes were made. The worker
already had the required explicit experimental authorization. There are no mocks
in these live browser requests and no automatic replay or generated-code repair.

## Live attempts

| Request | Run | Outcome |
| --- | --- | --- |
| `2330b749-a4e3-4b61-9843-eda187342131` | `96e1ebbf-dd71-44f3-a8ae-a92fdb6191d4` | Real `SCRIPT_FAILED`; generated code used Decimal without importing it. UI displayed failure. |
| `82aa8333-4dec-4d99-99af-5f534cddcfa6` | `37b7e4f9-7e50-40ae-be20-7bb154d0ef5f` | Completed, actual `{"answer":770.0}`, actual generated code and Qwen explanation rendered in browser. |

The second was a separately identified, manually initiated supervised acceptance
attempt, not an automatic retry of the first execution. The model, prompts and
failed code were not changed. The successful Playwright test took 41.6 seconds.
The first test waited for Completed and failed after its deadline; the test now
recognizes all terminal outcomes promptly and still requires completed/770 for
acceptance. This is a real integration smoke pass, not a model accuracy guarantee.

The fixture arithmetic was independently computed from the existing synthetic
CSV using trusted Decimal arithmetic: 2×100 + 1×150 + 3×40 + 4×75 = **770 THB**.
Generated Python was never executed on the Mac or in the browser.

[Selected nonsecret verification](frontend-live-verification.json) contains fresh
HTTP records, exact matching PostgreSQL fields, source hashes, executor-recorded
provider Job/Pod/container IDs, observed pinned image IDs, submitted runtime class,
runner exit/result evidence and independently checked API resource absence for
both runs. It excludes full private journals, ConfigMaps and CSV bytes. There is
no separate live provider snapshot: attempted label-list observations could not
list Jobs/ConfigMaps under the scoped identity. Final cleanup checks correctly
used named Job/ConfigMap reads and scoped Pod listing; no RBAC was widened.

Both runs used `kata-qemu-runtime-rs` and the existing pinned Runner 0.1.1 image.
The successful runner reported script exit 0, result bytes `{"answer":770.0}`, and
a Succeeded provider Pod with the approved image identity. All correlated API
Jobs, Pods and ConfigMaps were independently absent after cleanup. Journal
`cleanup=pending`, `guest_teardown_verified=false` remains accurate: independent
node/sandbox teardown was **not verified**.

[Browser screenshot](frontend-live-browser.png) shows the real successful request
restored by its backend IDs after the final style fix, without another submission.

## Automated checks

- Backend including disposable PostgreSQL: **720 passed**, including actual HTTP
  multipart upload → private storage → idempotent request → worker → persisted GET,
  with model/executor mocked only inside that integration test.
- Frontend Vitest: **42 passed** (API bytes/headers, idempotency, terminal states,
  polling outage, duplicate prevention, restoration, failures and unavailable data).
- Runner unittest: **48 passed**. Executor unittest: **39 passed**.
- Deterministic Playwright: **4 passed** on desktop/mobile Chromium, using explicit
  test-only API route mocks with the real FastAPI static/security boundary.
- Separate opt-in real browser-to-Qwen/Kata test: **1 passed**, preceded by the
  retained real model-code failure above.
- TypeScript and Vite production build, Prettier, backend Ruff and diff whitespace:
  passed. Broad `ruff check backend infra tests` reports **48 existing findings**
  in unchanged infrastructure/historical test files; these were not suppressed or
  modified as part of the UI integration.

The first sandboxed backend run could not bind localhost sockets; an authorized
rerun passed. Initial npm installation also needed network/cache access. Pinned
Chromium was installed under `/tmp/kataai-playwright`. Initial browser attempts
failed for a missing pinned browser and then an output-directory collision from
concurrent live/default runs. Repeats used installed Chromium and separate output
paths and passed. Installed Node 24.14.1 produced engine warnings against the
frontend toolchain's declared 24.15+ range; build and tests nevertheless passed.
Use a supported Node version for reproducibility.

## Remaining limits

No independent guest teardown proof, general Qwen accuracy guarantee, Safari/
Firefox verification or multi-user support. The frontend retains its conservative
128 KiB CSV limit. Saved questions/identities stay in browser local storage for
safe recovery; CSV previews/code/results do not. Existing credentials still expire
at the time recorded in the runbook and require manual renewal; no automatic
permission grant or credential renewal was introduced.

Subsequent persisted execution-stage latency implementation and real verification
are recorded separately in [STAGES.md](STAGES.md).
