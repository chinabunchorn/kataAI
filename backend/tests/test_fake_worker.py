"""Offline worker tests: synthetic sessions only; never an operator database."""
from types import SimpleNamespace
from uuid import uuid4

import pytest


class Result:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


class Database:
    def __init__(self, rows=()):
        self.rows = [dict(row) for row in rows]
        self.owner = None
        self.claimed = []


class Connection:
    def __init__(self, db):
        self.db = db
        self.commits = 0
        self.fail_commit = None
        self.lost = False

    def execute(self, statement, params):
        sql = str(statement)
        if 'pg_try_advisory_lock' in sql:
            assert 'pg_try_advisory_lock(:namespace, :worker)' in sql
            acquired = self.db.owner is None
            if acquired:
                self.db.owner = self
            return Result(acquired)
        if 'pg_locks' in sql:
            return Result(self.db.owner is self and not self.lost)
        if 'pg_advisory_unlock' in sql:
            if self.db.owner is self:
                self.db.owner = None
                return Result(True)
            return Result(False)
        raise AssertionError(sql)

    def commit(self):
        self.commits += 1
        if self.commits == self.fail_commit:
            raise RuntimeError('secret question must never be printed')

    def rollback(self):
        pass


class Queue:
    def __init__(self, connection):
        self.db = connection.db

    def mark_unknown_running(self):
        count = 0
        for row in self.db.rows:
            if row['status'] == 'running':
                row['status'] = 'unknown'
                count += 1
        return count

    def claim_next(self, token):
        for row in self.db.rows:
            if row['status'] == 'queued':
                row.update(status='running', token=token)
                self.db.claimed.append(row['id'])
                return SimpleNamespace(id=row['id'])
        return None

    def complete_fake(self, request_id, token):
        for row in self.db.rows:
            if row['id'] == request_id and row['status'] == 'running' and row['token'] == token:
                row['status'] = 'fake_completed'
                return True
        return False


def test_busy_worker_does_not_touch_queue():
    from app.fake_worker import run_once
    db = Database()
    db.owner = object()
    def no_queue(_connection):
        raise AssertionError('a busy worker must not touch the queue')
    assert run_once(Connection(db), no_queue) == 'busy'


def test_crash_recovery_does_not_redispatch_and_claims_new_work():
    from app.fake_worker import run_once
    old, new = uuid4(), uuid4()
    db = Database([{'id': old, 'status': 'running'}, {'id': new, 'status': 'queued'}])
    assert run_once(Connection(db), Queue) == 'fake_completed'
    assert [r['status'] for r in db.rows] == ['unknown', 'fake_completed']
    assert db.claimed == [new]
    assert db.owner is None


def test_stale_token_cannot_finish():
    from app.fake_worker import run_once
    db = Database([{'id': uuid4(), 'status': 'queued'}])
    class StaleQueue(Queue):
        def complete_fake(self, request_id, token):
            self.db.rows[0]['token'] = uuid4()
            return super().complete_fake(request_id, token)
    assert run_once(Connection(db), StaleQueue) == 'stale'
    assert db.rows[0]['status'] == 'running'


@pytest.mark.parametrize('commit_number,expected_status,claims', [
    (2, 'queued', 0), (3, 'running', 1), (4, 'fake_completed', 1),
])
def test_uncertain_commit_stops_without_retry(commit_number, expected_status, claims):
    from app.fake_worker import run_once
    db = Database([{'id': uuid4(), 'status': 'queued'}])
    conn = Connection(db)
    conn.fail_commit = commit_number
    with pytest.raises(RuntimeError):
        run_once(conn, Queue)
    # This synthetic DB models the dangerous case: commit applied but ack lost.
    assert db.rows[0]['status'] == expected_status
    assert len(db.claimed) == claims
    assert db.owner is None


def test_lost_session_ownership_stops_before_completion():
    from app.fake_worker import run_once, OwnershipLost
    db = Database([{'id': uuid4(), 'status': 'queued'}])
    class LostConnection(Connection):
        def commit(self):
            super().commit()
            if self.commits == 3:
                self.lost = True
    with pytest.raises(OwnershipLost):
        run_once(LostConnection(db), Queue)
    assert db.rows[0]['status'] == 'running'


def test_concurrent_worker_is_busy_during_claim():
    from app.fake_worker import run_once
    from threading import Event, Thread
    entered, release = Event(), Event()
    db = Database([{'id': uuid4(), 'status': 'queued'}])
    class BlockingQueue(Queue):
        def claim_next(self, token):
            entered.set()
            assert release.wait(5)
            return super().claim_next(token)
    results = []
    thread = Thread(target=lambda: results.append(run_once(Connection(db), BlockingQueue)))
    thread.start()
    try:
        assert entered.wait(5)
        assert run_once(Connection(db), Queue) == 'busy'
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    assert results == ['fake_completed']
    assert len(db.claimed) == 1


def test_unlock_ownership_loss_is_not_reported_as_success():
    from app.fake_worker import run_once, OwnershipLost
    db = Database([{'id': uuid4(), 'status': 'queued'}])
    class LostOnUnlock(Connection):
        def execute(self, statement, params):
            if 'pg_advisory_unlock' in str(statement):
                self.db.owner = None
                return Result(False)
            return super().execute(statement, params)
    with pytest.raises(OwnershipLost):
        run_once(LostOnUnlock(db), Queue)


def test_next_owner_marks_uncertain_claim_unknown_not_retried():
    from app.fake_worker import run_once
    db = Database([{'id': uuid4(), 'status': 'queued'}])
    conn = Connection(db)
    conn.fail_commit = 3
    with pytest.raises(RuntimeError):
        run_once(conn, Queue)
    assert run_once(Connection(db), Queue) == 'idle'
    assert db.rows[0]['status'] == 'unknown'
    assert len(db.claimed) == 1


def test_cli_redacts_exception(monkeypatch, capsys):
    from app.fake_worker import main
    import app.dataset_runtime as runtime
    def fail():
        raise ValueError('secret question and database credentials')
    monkeypatch.setattr(runtime, 'load_dataset_runtime', fail)
    assert main(['--once']) == 1
    output = capsys.readouterr()
    assert 'secret' not in output.out + output.err
    assert 'uncertain' in output.err
