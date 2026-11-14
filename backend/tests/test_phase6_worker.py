"""Phase 6 worker tests use synthetic sessions and never execute generated code."""
from uuid import uuid4

import pytest
from test_fake_worker import Connection, Database, Queue
from test_postgres_live import migrated_connection as migrated_connection  # noqa: F401
from test_request_queue import ready


def test_injected_processor_receives_claim_and_publishes_envelope():
    from app.fake_worker import run_once
    db = Database([{'id': uuid4(), 'status': 'queued'}])
    seen = []
    envelope = {'code': 'raise Exception("never run")', 'result': [1, None],
                'summary': None, 'warning': 'SUMMARY_UNAVAILABLE'}

    class ResultQueue(Queue):
        def complete_fake(self, request_id, token, result):
            assert token == self.db.rows[0]['token']
            self.db.rows[0]['result'] = result
            return super().complete_fake(request_id, token)

    def processor(claim):
        seen.append(claim.id)
        return envelope

    assert run_once(Connection(db), ResultQueue, processor=processor) == 'fake_completed'
    assert seen == [db.rows[0]['id']]
    assert db.rows[0]['result']['result'] == [1, None]
    assert db.rows[0]['result']['fake'] is True
    assert db.rows[0]['result']['metrics'] is None


def test_completion_is_one_fenced_update_with_result():
    from app.request_queue import RequestQueue
    class Reply:
        def one_or_none(self):
            return ('fake_completed',)
    class Recorder:
        def execute(self, statement, params):
            self.sql, self.params = str(statement), params
            return Reply()
    conn = Recorder()
    token, rid = uuid4(), uuid4()
    result = {'code': 'print(1)', 'result': {'n': 1}}
    assert RequestQueue(conn).complete_fake(rid, token, result) == 'fake_completed'
    assert 'claim_token=:token' in conn.sql
    assert "status='cancel_requested'" in conn.sql
    assert 'fake_result' in conn.sql
    assert conn.params['token'] == token


@pytest.mark.parametrize('value', [
    {'code': 'x', 'result': float('nan')},
    {'code': 'x', 'result': {'x': '\x00'}},
    {'code': 'x', 'result': 'a' * 32769},
    {'code': 'x' * 16385, 'result': None},
    {'code': 'x', 'result': None, 'metrics': 0},
    {'code': 'x', 'result': None, 'fake': False},
    {'code': 'x', 'result': None, 'extra': 'invalid'},
])
def test_invalid_envelopes_fail_before_database_access(value):
    from app.request_queue import InvalidRequest, RequestQueue
    with pytest.raises(InvalidRequest):
        RequestQueue(None).complete_fake(uuid4(), uuid4(), value)


def test_processor_exception_does_not_complete_or_retry():
    from app.fake_worker import run_once
    db = Database([{'id': uuid4(), 'status': 'queued'}])
    calls = []
    def processor(claim):
        calls.append(claim.id)
        raise RuntimeError('failed')
    with pytest.raises(RuntimeError):
        run_once(Connection(db), Queue, processor=processor)
    assert len(calls) == 1
    assert db.rows[0]['status'] == 'running'


def test_result_completion_commit_ack_lost_is_not_reported_as_success():
    from app.fake_worker import run_once
    db = Database([{'id': uuid4(), 'status': 'queued'}])
    class ResultQueue(Queue):
        def complete_fake(self, request_id, token, result):
            self.db.rows[0]['result'] = result
            return super().complete_fake(request_id, token)
    conn = Connection(db)
    conn.fail_commit = 4
    calls = []
    def processor(claim):
        calls.append(claim.id)
        return {'code': 'not run', 'result': None}
    with pytest.raises(RuntimeError):
        run_once(conn, ResultQueue, processor=processor)
    assert len(calls) == 1
    assert db.rows[0]['status'] == 'fake_completed'
    assert db.rows[0]['result']['result'] is None


@pytest.mark.live_postgres
def test_persist_result_cancel_and_stale_fences(request):
    from app.request_queue import RequestQueue
    queue_db, _ = request.getfixturevalue('migrated_connection')
    q = RequestQueue(queue_db)
    dataset = ready(queue_db)
    first, _ = q.create(uuid4(), dataset, 'first')
    queue_db.commit()
    token = uuid4()
    q.claim_next(token)
    queue_db.commit()
    result = {'code': 'not executed', 'result': [1, None], 'warning': 'SUMMARY_UNAVAILABLE'}
    assert not q.complete_fake(first.id, uuid4(), result)
    assert q.complete_fake(first.id, token, result) == 'fake_completed'
    queue_db.commit()
    assert q.get(first.id).fake_result['result'] == [1, None]
    assert q.history(10)[0].fake_result['fake'] is True
    second, _ = q.create(uuid4(), dataset, 'second')
    queue_db.commit()
    token = uuid4()
    q.claim_next(token)
    queue_db.commit()
    q.cancel(second.id)
    queue_db.commit()
    assert q.complete_fake(second.id, token, result) == 'cancelled'
    queue_db.commit()
    assert q.get(second.id).fake_result is None


@pytest.mark.live_postgres
def test_migration_refuses_to_drop_persisted_results(request):
    from alembic import command
    from sqlalchemy.exc import DBAPIError
    from app.request_queue import RequestQueue
    conn, config = request.getfixturevalue('migrated_connection')
    q = RequestQueue(conn)
    dataset = ready(conn)
    record, _ = q.create(uuid4(), dataset, 'example')
    conn.commit()
    token = uuid4()
    q.claim_next(token)
    conn.commit()
    q.complete_fake(record.id, token, {'code': 'inert', 'result': None})
    conn.commit()
    with pytest.raises(DBAPIError):
        command.downgrade(config, '0004_request_lifecycle')
    conn.rollback()
    assert q.get(record.id).fake_result['result'] is None
