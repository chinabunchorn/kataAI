"""Full-app acceptance with synthetic CSV and a disposable PostgreSQL schema."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier, Event
import time
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.dataset_lookup_api import get_dataset_runtime
from app.main import app
from test_postgres_live import migrated_connection as migrated_connection


@pytest.mark.live_postgres
def test_upload_submit_deduplicate_and_fake_worker(request, tmp_path):
    from app.fake_worker import run_once
    from app.request_queue import RequestQueue

    conn, _ = request.getfixturevalue('migrated_connection')
    schema = conn.execute(sa.text('SELECT current_schema()')).scalar_one()
    conn.commit()
    tmp_path.chmod(0o700)

    @contextmanager
    def isolated_connection():
        with conn.engine.connect() as current:
            current.exec_driver_sql(f'SET search_path TO "{schema}"')
            current.commit()
            yield current

    class Runtime:
        root = tmp_path
        connection = staticmethod(isolated_connection)

    app.dependency_overrides[get_dataset_runtime] = lambda: Runtime()
    try:
        client = TestClient(app, base_url='http://127.0.0.1:8000')
        headers = {'origin': 'http://127.0.0.1:8000', 'x-kataai-request': '1'}
        csv = b'\xef\xbb\xbf' + 'สินค้า,ยอด\nชา,3\n'.encode()
        upload = client.post('/v1/datasets', files={'file': ('sales.csv', csv, 'text/csv')}, headers=headers)
        assert upload.status_code == 201
        payload = {'schema_version': '1.0', 'client_request_id': str(uuid4()),
                   'dataset_id': upload.json()['dataset_id'], 'question': 'ยอดชาทั้งหมดเท่าไร?'}
        created = client.post('/v1/requests', json=payload, headers=headers)
        assert created.status_code == 201
        assert created.json()['status'] == 'queued'
        request_id = created.json()['id']
        repeated = client.post('/v1/requests', json=payload, headers=headers)
        assert repeated.status_code == 200 and repeated.json()['id'] == request_id
        conflict = client.post('/v1/requests', json={**payload, 'question': 'Different?'}, headers=headers)
        assert conflict.status_code == 409
        assert client.get(f'/v1/requests/{request_id}').json()['status'] == 'queued'
        assert conn.execute(sa.text('SELECT count(*) FROM request_intents')).scalar_one() == 1
        conn.rollback()

        with isolated_connection() as worker_connection:
            outcome = run_once(worker_connection, RequestQueue)
        assert outcome == 'fake_completed'
        completed = client.get(f'/v1/requests/{request_id}')
        assert completed.status_code == 200 and completed.json()['status'] == 'fake_completed'
        assert completed.json()['fake'] is True
        history = client.get('/v1/requests')
        assert history.status_code == 200
        items = [item for item in history.json()['requests'] if item['id'] == request_id]
        assert len(items) == 1
        assert items[0]['question'] == payload['question']
        assert items[0]['dataset_id'] == payload['dataset_id']
        assert items[0]['created_at']
    finally:
        app.dependency_overrides.pop(get_dataset_runtime, None)


@pytest.mark.live_postgres
def test_simultaneous_duplicate_submission_and_competing_workers(request):
    from app.fake_worker import run_once
    from app.request_queue import IdempotencyConflict, RequestQueue

    conn, _ = request.getfixturevalue('migrated_connection')
    schema = conn.execute(sa.text('SELECT current_schema()')).scalar_one()
    dataset_id = uuid4()
    conn.execute(sa.text("INSERT INTO datasets (id, display_name, storage_key, publication_state) "
                         "VALUES (:id, 'fixture.csv', :key, 'ready')"),
                 {'id': dataset_id, 'key': uuid4()})
    conn.commit()
    engine = conn.engine

    @contextmanager
    def new_connection():
        with engine.connect() as current:
            current.exec_driver_sql(f'SET search_path TO "{schema}"')
            current.commit()
            yield current

    key = uuid4()
    gate = Barrier(6)

    def submit_same(_index):
        with new_connection() as current:
            gate.wait(timeout=10)
            record, created = RequestQueue(current).create(key, dataset_id, 'Identical synthetic question')
            current.commit()
            return record.id, created

    with ThreadPoolExecutor(max_workers=6) as pool:
        submitted = list(pool.map(submit_same, range(6)))
    assert len({identity for identity, _ in submitted}) == 1
    assert sum(created for _, created in submitted) == 1
    request_id = submitted[0][0]
    assert conn.execute(sa.text('SELECT count(*) FROM request_intents')).scalar_one() == 1
    conn.rollback()

    conflict_key = uuid4()
    gate = Barrier(2)

    def submit_different(question):
        with new_connection() as current:
            gate.wait(timeout=10)
            try:
                record, created = RequestQueue(current).create(conflict_key, dataset_id, question)
                current.commit()
                return record.id, created
            except IdempotencyConflict:
                current.rollback()
                return None, False

    with ThreadPoolExecutor(max_workers=2) as pool:
        divergent = list(pool.map(submit_different, ('question one', 'question two')))
    assert sum(created for _, created in divergent) == 1
    assert sum(identity is None for identity, _ in divergent) == 1

    entered, release = Event(), Event()

    class PausedQueue(RequestQueue):
        def complete_fake(self, request_id, token):
            entered.set()
            assert release.wait(10)
            return super().complete_fake(request_id, token)

    def work(queue_class):
        with new_connection() as current:
            return run_once(current, queue_class)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(work, PausedQueue)
        try:
            assert entered.wait(10)
            second = pool.submit(work, RequestQueue)
            assert second.result(timeout=10) == 'busy'
        finally:
            release.set()
        assert first.result(timeout=10) == 'fake_completed'

    with new_connection() as current:
        q = RequestQueue(current)
        completed_record = q.get(request_id)
        assert completed_record is not None and completed_record.status == 'fake_completed'
        token = uuid4()
        claimed = q.claim_next(token)
        assert claimed is not None and claimed.status == 'running'
        current.commit()
    # Simulate a crashed owner: the running row remains, but no session lock is held.
    with new_connection() as current:
        assert run_once(current, RequestQueue) == 'idle'
        q = RequestQueue(current)
        recovered_record = q.get(claimed.id)
        assert recovered_record is not None and recovered_record.status == 'unknown'
        assert not q.complete_fake(claimed.id, token)


@pytest.mark.live_postgres
def test_lost_worker_database_session_never_redelivers_or_finishes_stale(request):
    from app.fake_worker import run_once
    from app.request_queue import RequestQueue, RequestStorageError

    conn, _ = request.getfixturevalue('migrated_connection')
    schema = conn.execute(sa.text('SELECT current_schema()')).scalar_one()
    dataset_id = uuid4()
    conn.execute(sa.text("INSERT INTO datasets (id, display_name, storage_key, publication_state) "
                         "VALUES (:id, 'session.csv', :key, 'ready')"),
                 {'id': dataset_id, 'key': uuid4()})
    record, _ = RequestQueue(conn).create(uuid4(), dataset_id, 'Synthetic session loss')
    conn.commit()
    engine = conn.engine
    entered, release = Event(), Event()
    backend_pid = []

    @contextmanager
    def new_connection():
        with engine.connect() as current:
            current.exec_driver_sql(f'SET search_path TO "{schema}"')
            current.commit()
            yield current

    class PausedQueue(RequestQueue):
        def complete_fake(self, request_id, token):
            entered.set()
            assert release.wait(10)
            return super().complete_fake(request_id, token)

    def work():
        with new_connection() as current:
            backend_pid.append(current.execute(sa.text('SELECT pg_backend_pid()')).scalar_one())
            current.commit()
            return run_once(current, PausedQueue)

    with ThreadPoolExecutor(max_workers=1) as pool:
        old_worker = pool.submit(work)
        try:
            assert entered.wait(10) and len(backend_pid) == 1
            assert conn.execute(sa.text('SELECT pg_terminate_backend(:pid)'),
                                {'pid': backend_pid[0]}).scalar_one() is True
            conn.commit()
            deadline = time.monotonic() + 5
            while True:
                active = conn.execute(sa.text('SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE pid=:pid)'),
                                      {'pid': backend_pid[0]}).scalar_one()
                conn.commit()
                if not active:
                    break
                assert time.monotonic() < deadline
                time.sleep(0.01)
            with new_connection() as replacement:
                assert run_once(replacement, RequestQueue) == 'idle'
                observed = RequestQueue(replacement).get(record.id)
                assert observed is not None and observed.status == 'unknown'
        finally:
            release.set()
        with pytest.raises((RequestStorageError, sa.exc.SQLAlchemyError)):
            old_worker.result(timeout=10)

    with new_connection() as current:
        observed = RequestQueue(current).get(record.id)
        assert observed is not None and observed.status == 'unknown'
        assert current.execute(sa.text('SELECT count(*) FROM request_intents')).scalar_one() == 1
