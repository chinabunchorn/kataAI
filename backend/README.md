# Backend: initial fake-only slice

This is a provisional, incomplete B1 prototype. `GET /health` reports process
health, not model, executor, or isolation readiness. There is no real model,
code execution, persistence, migration, or remote provider. Fake outcomes are
preset and are not computation or benchmark measurements. The in-process
example wires provisional ports, but is not exposed as an HTTP execution
endpoint. No generated code is evaluated.

## Provisional request validation (not a frontend agreement)

`POST /v1/requests` accepts a JSON object with exactly these required fields:

- `schema_version`: the string `"1.0"` only.
- `client_request_id`: a UUID expressed as a string, for correlation only.
- `dataset_id`: an opaque string, 1–256 Unicode code points, containing at
  least one non-whitespace character. Existence is not checked.
- `question`: a string, 1–4,096 Unicode code points, containing at least one
  non-whitespace character. English and Thai are accepted.

These limits, field names, and error codes are local provisional decisions, not
an agreed frontend contract. Unknown fields (including infrastructure settings)
are rejected. Malformed JSON, invalid types, unsupported versions, and other
validation failures return HTTP 422 with `{"error":{"code":"INVALID_REQUEST",
"message":"Invalid request."}}`. Valid inputs always return HTTP 503 with
`{"error":{"code":"EXECUTION_UNAVAILABLE","message":"Request processing is
unavailable."}}`. Neither response echoes input. No request is queued, stored,
assigned a durable ID, submitted, or sent to a model or executor. Repeating a
request does not establish idempotency or promise eventual processing.

The provisional transport limit for `POST /v1/requests` is 65,536 body bytes,
inclusive, counted from the ASGI stream before JSON parsing rather than trusting
`Content-Length`. Larger bodies return HTTP 413 with
`{"error":{"code":"REQUEST_TOO_LARGE","message":"Request body is too large."}}`.
This bounds application accumulation per request, not the size of an individual
chunk already delivered by the ASGI server, server/proxy buffering, parsing
overhead, concurrent requests, or request duration. It is not a global memory or
denial-of-service limit; deployment still needs server/proxy limits, timeouts,
and concurrency controls.

**Prototype-only, local-only:** Do not expose this endpoint to untrusted
traffic. Loopback binding alone does not protect against malicious browser
origins; browser-origin/CSRF defenses must be designed before enabling any
state-changing endpoint.

The provisional proposal input is a list with exactly one object containing only
`name` and `arguments`; `name` must be `run_python`, and `arguments` must contain
only a non-whitespace `code` string of at most 16,384 UTF-8 bytes. This shape and
limit are local test decisions, not an agreed external contract. Error names are
likewise provisional. Do not treat this validator as a sandbox.

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
