# Backend: initial fake-only slice

This is a provisional, incomplete B1 starting point. The only HTTP endpoint is
`GET /health`; it reports process health, not model, executor, or isolation
readiness. There is no real model, code execution, persistence, migration, or
remote provider. Fake outcomes are preset and are not computation or benchmark
measurements. The in-process example wires provisional ports, but is not exposed
as an HTTP execution endpoint. No generated code is evaluated.

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
unset PYTHONPATH
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
