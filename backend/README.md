# Backend: initial fake-only slice

This is a provisional, incomplete B1 prototype. `GET /health` reports process
health, not model, executor, or isolation readiness. There is no real model,
code execution, application persistence, or remote provider. A provisional
metadata-only migration exists, but the application does not use it. Fake outcomes are
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

## Provisional database migration foundation

This migration is **not B2**: there are no upload/download/delete endpoints,
filesystem operations, database-backed repositories, queue, or history wiring.
`/v1/requests` still returns 503 for valid input. The provisional `datasets`
table contains a caller-supplied UUID primary key, a separately generated unique
UUID storage key (never a path), a bounded display name, creation time, and an
`active`/`deleted` tombstone with a matching deletion timestamp. Producers must
generate opaque IDs and sanitize display names before insertion; constraints are
only a defensive minimum, not HTML escaping or a complete Unicode/confusable
policy. The deleted row can eventually be referenced by retained history; no
history schema, deletion semantics, file/DB atomicity, race protection, or
automatic cleanup is implemented. Downgrades remove the table and its data and
are not a production rollback strategy. Schema, policies and API are provisional.

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
search path so both application tables and `alembic_version` live there. Cleanup
uses transactional `RESTRICT` drops for those known tables and the test schema.
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
