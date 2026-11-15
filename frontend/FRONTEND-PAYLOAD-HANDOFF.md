# Integrated API contract

The implemented backend is authoritative. The old metadata-only handoff is
superseded by `src/lib/api.ts` and [the frontend runbook](README.md).

1. `POST /v1/datasets`: original CSV File in multipart `file`; retain `dataset_id`.
2. `POST /v1/requests`: JSON `schema_version: "1.0"`, `client_request_id` (UUID),
   `dataset_id`, `question`. Reuse that exact identity and input on explicit retry.
3. `GET /v1/requests/{id}`: poll queued/running/cancel_requested; stop on terminal
   states. Unknown means execution may have occurred. Never automatically resubmit.
4. Display actual `answer`, `result`, `code`, `run_id`, `error_code`. Missing fields
   stay unavailable. `fake_completed` or `fake: true` never count as real execution.

Use same-origin FastAPI serving the built frontend. State-changing calls send
`X-KataAI-Request: 1`; the browser supplies its true Origin. Do not rewrite Origin
or weaken Host checks. No private infrastructure configuration goes to the browser.
