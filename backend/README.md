# Backend: provisional B1 slices

This is a provisional, incomplete B1 prototype. `GET /health` reports process
health, not model, executor, or isolation readiness. There is no real model,
code execution, wired application persistence, or remote provider. An isolated
metadata storage adapter and migration exist, but HTTP does not use them. Fake outcomes are
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
caller owns connection and source lifetimes. This is not wired to HTTP.

**Critical: `active` is a lifecycle value, not file readiness.** `publication_state`
is separately `unknown`, `pending`, or `ready`. Legacy rows and direct SQL inserts
default to `unknown`; adapter-created rows start `pending`. The conditional ready
update requires matching ID, storage key, active lifecycle, and pending state; only
the coordinator may use it after successful publication. The store primitive cannot
itself prove publication; trusted callers must respect this contract. A successful
coordinator return means the ready transaction's commit returned successfully.
No cross-resource atomicity, endpoint serving, integrity audit, or automated
reconciliation is implemented. This is not B2 upload readiness.

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
No upload, retrieval, or deletion HTTP endpoint or browser capability is added. Valid
`/v1/requests` still returns 503.

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
transaction, lifecycle/deletion protocol, or safe automated retry here. Those
and browser-origin/transport protections require explicit design and integration
before exposure. Do not treat this slice as upload or execution readiness.

## Provisional B2 CSV intake core (not wired to HTTP)

`app.csv_intake.validate_csv(source, limits)` consumes a caller-owned binary
file-like object or iterable of byte chunks once and returns immutable
`CsvMetadata(columns, byte_size, row_count)` only after successful EOF. It does
not close the stream, use filenames or client hints, retain rows, persist files,
connect to a database, call a model, or execute CSV text. It does not implement
an upload endpoint. Valid `/v1/requests` still returns 503. Header names are
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
block indefinitely and the byte limit is not a duration limit. Future transport
wiring must enforce those controls separately. More than 1,024 total empty
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

This foundation is **not B2**: there are no upload/download/delete endpoints,
HTTP filesystem operations, queue, or history wiring.
`/v1/requests` still returns 503 for valid input. The provisional `datasets`
table contains a caller-supplied UUID primary key, a separately generated unique
UUID storage key (never a path), a bounded display name, creation time, and an
`active`/`deleted` tombstone with a matching deletion timestamp. Producers must
generate opaque IDs and sanitize display names before insertion; constraints are
only a defensive minimum, not HTML escaping or a complete Unicode/confusable
policy. The deleted row can eventually be referenced by retained history; no
history schema, deletion semantics, file/DB atomicity, complete race protection, or
automatic cleanup is implemented. Downgrading revision 0002 drops readiness
information; re-upgrading assigns `unknown` to existing rows, requiring manual
reconciliation. Downgrading to base also removes the table and its data. Neither
is a safe production rollback strategy. Schema, policies and API are provisional.

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
atomicity, or deletion semantics. Nothing here wires a storage adapter to HTTP or
implements a deletion service, queue, or execution.

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
