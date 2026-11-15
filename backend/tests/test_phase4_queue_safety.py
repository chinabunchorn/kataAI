"""Safety tests use synthetic rows in the explicitly disposable PostgreSQL fixture."""
from uuid import uuid4
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
import sqlalchemy as sa
from alembic import command

from app.request_queue import RequestQueue, RequestStorageError
from app.fake_worker import run_once
from test_postgres_live import migrated_connection as migrated_connection


@pytest.mark.live_postgres
def test_cancel_claim_is_acknowledged_with_fencing(request):
    conn, _ = request.getfixturevalue('migrated_connection')
    dataset_id = uuid4()
    conn.execute(sa.text("INSERT INTO datasets (id, display_name, storage_key, publication_state) VALUES (:id, 'fixture.csv', :key, 'ready')"), {'id': dataset_id, 'key': uuid4()})
    q = RequestQueue(conn)
    record, _ = q.create(uuid4(), dataset_id, 'Synthetic question')
    token = uuid4()
    assert q.claim_next(token).id == record.id
    assert q.cancel(record.id).status == 'cancel_requested'
    assert not q.complete_fake(record.id, uuid4())
    assert q.complete_fake(record.id, token) == 'cancelled'
    assert q.get(record.id).status == 'cancelled'


@pytest.mark.live_postgres
def test_retained_history_keyset_and_recovery(request):
    conn, _ = request.getfixturevalue('migrated_connection')
    dataset_id = uuid4()
    conn.execute(sa.text("INSERT INTO datasets (id, display_name, storage_key, publication_state) VALUES (:id, 'fixture.csv', :key, 'ready')"), {'id': dataset_id, 'key': uuid4()})
    q = RequestQueue(conn)
    keys = [uuid4() for _ in range(4)]
    records = [q.create(key, dataset_id, 'Synthetic')[0] for key in keys]
    timestamp = datetime(2020, 1, 1, tzinfo=timezone.utc)
    conn.execute(sa.text('UPDATE request_intents SET created_at=:timestamp'), {'timestamp': timestamp})
    pages = []
    before = None
    while True:
        page = q.history(2, before=before)
        if not page:
            break
        pages.extend(item.id for item in page)
        before = (page[-1].created_at, page[-1].id)
    assert pages == sorted([r.id for r in records], reverse=True)
    assert q.hide_history(records[0].id).status == 'queued'
    assert q.cancel(records[0].id).status == 'cancelled'
    assert q.hide_history(records[0].id).status == 'cancelled'
    assert q.get(records[0].id) is None
    assert records[0].id not in [r.id for r in q.history(100)]
    replay, created = q.create(keys[0], dataset_id, 'Synthetic')
    assert replay.id == records[0].id and not created
    assert q.get(records[0].id) is None
    token = uuid4()
    running = q.claim_next(token)
    assert q.cancel(running.id).status == 'cancel_requested'
    assert q.claim_next(uuid4()) is None
    assert q.mark_unknown_running() == 1
    assert q.get(running.id).status == 'unknown'
    assert q.hide_history(running.id).status == 'unknown'
    assert not q.complete_fake(running.id, token)


@pytest.mark.live_postgres
@pytest.mark.parametrize('cancel_first', [True, False])
def test_worker_finish_cancel_order_is_linearized(request, cancel_first):
    conn, _ = request.getfixturevalue('migrated_connection')
    schema = conn.execute(sa.text('SELECT current_schema()')).scalar_one()
    dataset_id = uuid4()
    conn.execute(sa.text("INSERT INTO datasets (id, display_name, storage_key, publication_state) VALUES (:id, 'fixture.csv', :key, 'ready')"), {'id': dataset_id, 'key': uuid4()})
    record, _ = RequestQueue(conn).create(uuid4(), dataset_id, 'Synthetic race')
    conn.commit()
    entered, release = Event(), Event()

    class PausedQueue(RequestQueue):
        def complete_fake(self, request_id, token):
            if cancel_first:
                entered.set()
                assert release.wait(10)
            result = super().complete_fake(request_id, token)
            if not cancel_first:
                entered.set()
                assert release.wait(10)
            return result

    def worker():
        with conn.engine.connect() as current:
            current.exec_driver_sql(f'SET search_path TO "{schema}"')
            current.commit()
            return run_once(current, PausedQueue)

    def cancel():
        with conn.engine.connect() as current:
            current.exec_driver_sql(f'SET search_path TO "{schema}"')
            current.commit()
            result = RequestQueue(current).cancel(record.id)
            current.commit()
            return result.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        work = pool.submit(worker)
        try:
            assert entered.wait(10)
            cancelling = pool.submit(cancel)
            if cancel_first:
                assert cancelling.result(timeout=10) == 'cancel_requested'
        finally:
            release.set()
        assert work.result(timeout=10) == ('cancelled' if cancel_first else 'fake_completed')
        assert cancelling.result(timeout=10) == ('cancel_requested' if cancel_first else 'fake_completed')


@pytest.mark.live_postgres
@pytest.mark.parametrize('apply_commit', [False, True])
def test_cancellation_commit_uncertainty_stops_and_recovers(request, apply_commit):
    conn, _ = request.getfixturevalue('migrated_connection')
    schema = conn.execute(sa.text('SELECT current_schema()')).scalar_one()
    dataset_id = uuid4()
    conn.execute(sa.text("INSERT INTO datasets (id, display_name, storage_key, publication_state) VALUES (:id, 'fixture.csv', :key, 'ready')"), {'id': dataset_id, 'key': uuid4()})
    record, _ = RequestQueue(conn).create(uuid4(), dataset_id, 'Synthetic uncertainty')
    conn.commit()

    class CancelBeforeFinish(RequestQueue):
        def complete_fake(self, request_id, token):
            with conn.engine.connect() as other:
                other.exec_driver_sql(f'SET search_path TO "{schema}"')
                assert RequestQueue(other).cancel(request_id).status == 'cancel_requested'
                other.commit()
            return super().complete_fake(request_id, token)

    class UncertainConnection:
        def __init__(self, connection):
            self.connection = connection
            self.commits = 0

        def execute(self, *args, **kwargs):
            return self.connection.execute(*args, **kwargs)

        def commit(self):
            self.commits += 1
            if self.commits == 4:
                if apply_commit:
                    self.connection.commit()
                raise RuntimeError('synthetic lost commit acknowledgement')
            self.connection.commit()

        def rollback(self):
            self.connection.rollback()

    with conn.engine.connect() as current:
        current.exec_driver_sql(f'SET search_path TO "{schema}"')
        current.commit()
        with pytest.raises(RuntimeError, match='synthetic lost commit acknowledgement'):
            run_once(UncertainConnection(current), CancelBeforeFinish)
    with conn.engine.connect() as replacement:
        replacement.exec_driver_sql(f'SET search_path TO "{schema}"')
        replacement.commit()
        assert run_once(replacement, RequestQueue) == 'idle'
        assert RequestQueue(replacement).get(record.id).status == ('cancelled' if apply_commit else 'unknown')


@pytest.mark.live_postgres
@pytest.mark.parametrize('state', ['cancelled', 'cancel_requested', 'hidden'])
def test_downgrade_refuses_to_discard_lifecycle_state(request, state):
    conn, config = request.getfixturevalue('migrated_connection')
    dataset_id = uuid4()
    conn.execute(sa.text("INSERT INTO datasets (id, display_name, storage_key, publication_state) VALUES (:id, 'fixture.csv', :key, 'ready')"), {'id': dataset_id, 'key': uuid4()})
    q = RequestQueue(conn)
    record, _ = q.create(uuid4(), dataset_id, 'Synthetic migration')
    if state == 'cancel_requested':
        assert q.claim_next(uuid4()).id == record.id
    q.cancel(record.id)
    if state == 'hidden':
        q.hide_history(record.id)
    conn.commit()
    with pytest.raises(sa.exc.DBAPIError):
        command.downgrade(config, '0003_request_intents')
    conn.rollback()
    row = conn.execute(sa.text('SELECT status, hidden_at FROM request_intents WHERE id=:id'), {'id': record.id}).one()
    assert row.status == ('cancel_requested' if state == 'cancel_requested' else 'cancelled')
    assert (row.hidden_at is not None) == (state == 'hidden')


@pytest.mark.live_postgres
def test_session_loss_after_cancellation_recovers_unknown(request):
    conn, _ = request.getfixturevalue('migrated_connection')
    schema = conn.execute(sa.text('SELECT current_schema()')).scalar_one()
    dataset_id = uuid4()
    conn.execute(sa.text("INSERT INTO datasets (id, display_name, storage_key, publication_state) VALUES (:id, 'fixture.csv', :key, 'ready')"), {'id': dataset_id, 'key': uuid4()})
    record, _ = RequestQueue(conn).create(uuid4(), dataset_id, 'Synthetic session loss')
    conn.commit()
    entered, release = Event(), Event()
    pids = []

    class PausedQueue(RequestQueue):
        def complete_fake(self, request_id, token):
            entered.set()
            assert release.wait(10)
            return super().complete_fake(request_id, token)

    def worker():
        with conn.engine.connect() as current:
            current.exec_driver_sql(f'SET search_path TO "{schema}"')
            pids.append(current.execute(sa.text('SELECT pg_backend_pid()')).scalar_one())
            current.commit()
            return run_once(current, PausedQueue)

    with ThreadPoolExecutor(max_workers=1) as pool:
        work = pool.submit(worker)
        try:
            assert entered.wait(10)
            assert RequestQueue(conn).cancel(record.id).status == 'cancel_requested'
            conn.commit()
            assert conn.execute(sa.text('SELECT pg_terminate_backend(:pid)'), {'pid': pids[0]}).scalar_one()
            conn.commit()
        finally:
            release.set()
        with pytest.raises((RequestStorageError, sa.exc.SQLAlchemyError)):
            work.result(timeout=10)
    with conn.engine.connect() as replacement:
        replacement.exec_driver_sql(f'SET search_path TO "{schema}"')
        replacement.commit()
        assert run_once(replacement, RequestQueue) == 'idle'
        assert RequestQueue(replacement).get(record.id).status == 'unknown'
