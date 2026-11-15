"""Explicit local adapter journal, independent of the backend request database."""

from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3


class SQLiteRunStore:
    """Single-host journal; use a private local directory, never a network share.

    A separate SQLite transaction serializes whole adapter operations across
    processes. Journal checkpoints commit independently before remote effects.
    Process death releases the operation lock without rolling back checkpoints.
    No database, directory or migration is created until explicitly constructed.
    """

    def __init__(self, path):
        self.path = str(Path(path).resolve())
        if str(path) == ":memory:" or not Path(self.path).parent.is_dir():
            raise ValueError("persistent journal in an existing private directory required")
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, record TEXT NOT NULL)")
        with closing(sqlite3.connect(self.path + ".lock")) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS operation_lock (id INTEGER PRIMARY KEY)")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def operation(self):
        with closing(sqlite3.connect(self.path + ".lock", timeout=5)) as guard, guard:
            guard.execute("BEGIN IMMEDIATE")
            yield

    def get(self, run_id):
        with self._connect() as db:
            row = db.execute("SELECT record FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save(self, record):
        raw = json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        with self._connect() as db:
            db.execute("INSERT INTO runs VALUES (?, ?) ON CONFLICT(run_id) DO UPDATE SET record=excluded.record",
                       (record["run_id"], raw))

    def pending(self):
        """Durable identities for a caller-owned startup/periodic reconciler."""
        with self._connect() as db:
            rows = db.execute("SELECT record FROM runs ORDER BY run_id").fetchall()
        return [r for row in rows if (r := json.loads(row[0]))["cleanup"] != "confirmed"]
