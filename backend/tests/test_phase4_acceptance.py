"""Phase 4 end-to-end checks: synthetic data and explicitly disposable PostgreSQL only."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from contextlib import contextmanager
from threading import Event
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.dataset_lookup_api import get_dataset_runtime
from app.main import app
from test_postgres_live import migrated_connection as migrated_connection  # noqa: F401


@pytest.mark.live_postgres
def test_request_cancellation_history_hiding_and_logical_dataset_deletion(request, tmp_path):
    conn, _ = request.getfixturevalue('migrated_connection')
    schema = conn.execute(sa.text('SELECT current_schema()')).scalar_one()
    conn.commit()
    tmp_path.chmod(0o700)

    class Runtime:
        root = tmp_path

        @contextmanager
        def connection(self):
            with conn.engine.connect() as current:
                current.exec_driver_sql(f'SET search_path TO "{schema}"')
                current.commit()
                yield current

    app.dependency_overrides[get_dataset_runtime] = lambda: Runtime()
    headers = {'origin': 'http://127.0.0.1:8000', 'x-kataai-request': '1'}
    try:
        client = TestClient(app, base_url='http://127.0.0.1:8000')
        csv = 'สินค้า,ยอด\nชา,3\n'.encode()
        upload = client.post('/v1/datasets', files={'file': ('sales.csv', csv, 'text/csv')}, headers=headers)
        assert upload.status_code == 201
        dataset_id = upload.json()['dataset_id']
        denied = client.delete(f'/v1/datasets/{dataset_id}',
                               headers={'origin': 'http://evil.invalid', 'x-kataai-request': '1'})
        assert denied.status_code == 403
        assert client.get(f'/v1/datasets/{dataset_id}').status_code == 200
        payload = {'schema_version': '1.0', 'client_request_id': str(uuid4()),
                   'dataset_id': dataset_id, 'question': 'ยอดชาทั้งหมด?'}
        first = client.post('/v1/requests', json=payload, headers=headers)
        assert first.status_code == 201
        first_id = first.json()['id']
        second = client.post('/v1/requests', json={**payload, 'client_request_id': str(uuid4())}, headers=headers)
        assert second.status_code == 201
        second_id = second.json()['id']
        blocked = client.delete(f'/v1/datasets/{dataset_id}', headers=headers)
        assert blocked.status_code == 409
        cancelled = client.post(f'/v1/requests/{first_id}/cancel', headers=headers)
        assert cancelled.status_code == 200 and cancelled.json()['status'] == 'cancelled'
        assert client.delete(f'/v1/requests/{first_id}', headers=headers).status_code == 204
        assert client.get(f'/v1/requests/{first_id}').status_code == 404
        assert all(entry['id'] != first_id for entry in client.get('/v1/requests').json()['requests'])
        replay = client.post('/v1/requests', json=payload, headers=headers)
        assert replay.status_code == 200 and replay.json()['id'] == first_id
        assert client.post(f'/v1/requests/{second_id}/cancel', headers=headers).json()['status'] == 'cancelled'
        files = [p for p in tmp_path.iterdir() if p.name != '.upload-admission.lock']
        assert len(files) == 1 and files[0].read_bytes() == csv
        deleted = client.delete(f'/v1/datasets/{dataset_id}', headers=headers)
        assert deleted.status_code == 200 and deleted.json()['file_cleanup'] == 'not_attempted'
        assert client.get(f'/v1/datasets/{dataset_id}').status_code == 404
        assert files[0].read_bytes() == csv
        assert conn.execute(sa.text('SELECT count(*) FROM request_intents')).scalar_one() == 2
    finally:
        app.dependency_overrides.pop(get_dataset_runtime, None)


@pytest.mark.live_postgres
def test_running_cancellation_requires_worker_acknowledgement(request):
    from app.fake_worker import run_once
    from app.request_queue import RequestQueue

    conn, _ = request.getfixturevalue('migrated_connection')
    schema = conn.execute(sa.text('SELECT current_schema()')).scalar_one()
    dataset_id = uuid4()
    conn.execute(sa.text("INSERT INTO datasets (id, display_name, storage_key, publication_state) "
                         "VALUES (:id, 'fixture.csv', :key, 'ready')"),
                 {'id': dataset_id, 'key': uuid4()})
    first, _ = RequestQueue(conn).create(uuid4(), dataset_id, 'First question')
    conn.commit()
    second, _ = RequestQueue(conn).create(uuid4(), dataset_id, 'Second question')
    conn.commit()
    engine = conn.engine
    entered, release = Event(), Event()

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

    def work(queue_class):
        with new_connection() as current:
            return run_once(current, queue_class)

    with ThreadPoolExecutor(max_workers=2) as pool:
        worker = pool.submit(work, PausedQueue)
        try:
            assert entered.wait(10)
            result = RequestQueue(conn).cancel(first.id)
            conn.commit()
            assert result is not None and result.status == 'cancel_requested'
            assert pool.submit(work, RequestQueue).result(timeout=10) == 'busy'
            assert RequestQueue(conn).claim_next(uuid4()) is None
            conn.commit()
        finally:
            release.set()
        assert worker.result(timeout=10) == 'cancelled'

    first_state = RequestQueue(conn).get(first.id)
    second_state = RequestQueue(conn).get(second.id)
    assert first_state is not None and first_state.status == 'cancelled'
    assert second_state is not None and second_state.status == 'queued'
    conn.rollback()
    assert work(RequestQueue) == 'fake_completed'
    terminal = RequestQueue(conn).cancel(second.id)
    assert terminal is not None and terminal.status == 'fake_completed'


@pytest.mark.live_postgres
def test_delete_cannot_race_a_live_http_publisher(request, tmp_path, monkeypatch):
    import app.dataset_publication as publication

    conn, _ = request.getfixturevalue('migrated_connection')
    schema = conn.execute(sa.text('SELECT current_schema()')).scalar_one()
    conn.commit()
    tmp_path.chmod(0o700)
    entered, release = Event(), Event()
    original = publication.publish_csv

    class Runtime:
        root = tmp_path

        @contextmanager
        def connection(self):
            with conn.engine.connect() as current:
                current.exec_driver_sql(f'SET search_path TO "{schema}"')
                current.commit()
                yield current

    def paused_publish(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(publication, 'publish_csv', paused_publish)
    app.dependency_overrides[get_dataset_runtime] = lambda: Runtime()
    headers = {'origin': 'http://127.0.0.1:8000', 'x-kataai-request': '1'}
    csv = b'name,value\nexample,2\n'

    def upload():
        client = TestClient(app, base_url='http://127.0.0.1:8000')
        return client.post('/v1/datasets', files={'file': ('example.csv', csv, 'text/csv')}, headers=headers)

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            running_upload = pool.submit(upload)
            try:
                assert entered.wait(10)
                row = conn.execute(sa.text('SELECT id, publication_state FROM datasets')).one()
                assert row.publication_state == 'pending'
                conn.rollback()
                client = TestClient(app, base_url='http://127.0.0.1:8000')
                assert client.delete(f'/v1/datasets/{row.id}', headers=headers).status_code == 503
                assert conn.execute(sa.text('SELECT lifecycle FROM datasets WHERE id=:id'),
                                    {'id': row.id}).scalar_one() == 'active'
                conn.rollback()
            finally:
                release.set()
            assert running_upload.result(timeout=10).status_code == 201
        deleted = client.delete(f'/v1/datasets/{row.id}', headers=headers)
        assert deleted.status_code == 200 and deleted.json()['file_cleanup'] == 'not_attempted'
        assert client.get(f'/v1/datasets/{row.id}').status_code == 404
        files = [path for path in tmp_path.iterdir() if path.name != '.upload-admission.lock']
        assert len(files) == 1 and files[0].read_bytes() == csv
    finally:
        app.dependency_overrides.pop(get_dataset_runtime, None)


@pytest.mark.live_postgres
@pytest.mark.parametrize('first', ['cancel', 'claim'])
def test_cancel_and_claim_serialize_in_both_orders(request, first):
    from app.request_queue import RequestQueue

    conn, _ = request.getfixturevalue('migrated_connection')
    schema = conn.execute(sa.text('SELECT current_schema()')).scalar_one()
    dataset_id, token = uuid4(), uuid4()
    conn.execute(sa.text("INSERT INTO datasets (id, display_name, storage_key, publication_state) "
                         "VALUES (:id, 'fixture.csv', :key, 'ready')"),
                 {'id': dataset_id, 'key': uuid4()})
    record, _ = RequestQueue(conn).create(uuid4(), dataset_id, 'Synthetic claim race')
    conn.commit()
    engine = conn.engine
    locked, started, release = Event(), Event(), Event()

    def run_operation(operation, pause):
        with engine.connect() as current:
            current.exec_driver_sql(f'SET search_path TO "{schema}"')
            current.commit()
            if not pause:
                started.set()
            queue = RequestQueue(current)
            result = queue.cancel(record.id) if operation == 'cancel' else queue.claim_next(token)
            if pause:
                locked.set()
                assert release.wait(10)
            current.commit()
            return result

    other = 'claim' if first == 'cancel' else 'cancel'
    with ThreadPoolExecutor(max_workers=2) as pool:
        winner = pool.submit(run_operation, first, True)
        try:
            assert locked.wait(10)
            loser = pool.submit(run_operation, other, False)
            assert started.wait(10)
            with pytest.raises(FutureTimeout):
                loser.result(timeout=0.1)
        finally:
            release.set()
        first_result = winner.result(timeout=10)
        second_result = loser.result(timeout=10)

    if first == 'cancel':
        assert first_result is not None and first_result.status == 'cancelled'
        assert second_result is None
    else:
        assert first_result is not None and first_result.status == 'running'
        assert second_result is not None and second_result.status == 'cancel_requested'
        assert RequestQueue(conn).complete_fake(record.id, token) == 'cancelled'
    state = RequestQueue(conn).get(record.id)
    assert state is not None and state.status == 'cancelled'
