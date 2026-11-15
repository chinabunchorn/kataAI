"""Phase 6 whole-app integration: synthetic CSV and disposable PostgreSQL only."""
from concurrent.futures import ThreadPoolExecutor
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
def test_fake_flow_upload_queue_worker_history_and_hiding(request, tmp_path):
    from app.fake_worker import run_once
    from app.phase6_processor import process_claim
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
        csv = 'สินค้า,ยอด\nชา,3\n'.encode()
        upload = client.post('/v1/datasets', files={'file': ('sales.csv', csv, 'text/csv')}, headers=headers)
        assert upload.status_code == 201
        payload = {'schema_version': '1.0', 'client_request_id': str(uuid4()),
                   'dataset_id': upload.json()['dataset_id'], 'question': 'ยอดชาทั้งหมดเท่าไร?'}
        created = client.post('/v1/requests', json=payload, headers=headers)
        assert created.status_code == 201
        request_id = created.json()['id']
        assert client.get(f'/v1/requests/{request_id}').json()['status'] == 'queued'
        with isolated_connection() as worker_connection:
            outcome = run_once(worker_connection, RequestQueue,
                               processor=lambda claim: process_claim(worker_connection, tmp_path, claim))
        assert outcome == 'fake_completed'
        detail = client.get(f'/v1/requests/{request_id}')
        assert detail.status_code == 200 and detail.headers['cache-control'] == 'no-store'
        body = detail.json()
        assert body['status'] == 'fake_completed' and body['fake'] is True
        result = body['fake_result']
        assert result['fake'] is True and result['result'] == {'example': [1, 2]}
        assert result['metrics'] is None and isinstance(result['code'], str)
        assert result['warning'] == 'SUMMARY_UNAVAILABLE'
        assert client.post(f'/v1/requests/{request_id}/cancel', headers=headers).status_code == 409
        assert client.get(f'/v1/requests/{request_id}').json()['fake_result'] == result
        history = client.get('/v1/requests').json()['requests']
        assert next(item for item in history if item['id'] == request_id)['fake_result'] == result
        assert client.delete(f'/v1/requests/{request_id}', headers=headers).status_code == 204
        assert client.get(f'/v1/requests/{request_id}').status_code == 404
        replay = client.post('/v1/requests', json=payload, headers=headers)
        assert replay.status_code == 200 and replay.json()['id'] == request_id
    finally:
        app.dependency_overrides.pop(get_dataset_runtime, None)


@pytest.mark.live_postgres
def test_cancel_during_fake_processing_cannot_publish_a_fake_result(request):
    from app.fake_worker import run_once
    from app.request_queue import RequestQueue
    from test_request_queue import ready

    conn, _ = request.getfixturevalue('migrated_connection')
    schema = conn.execute(sa.text('SELECT current_schema()')).scalar_one()
    dataset_id = ready(conn)
    record, _ = RequestQueue(conn).create(uuid4(), dataset_id, 'Synthetic')
    conn.commit()
    entered, release = Event(), Event()

    def processor(claim):
        entered.set()
        assert release.wait(10)
        return {'fake': True, 'code': '# inert', 'result': {'preset': 1},
                'summary': None, 'warning': None, 'metrics': None}

    def worker():
        with conn.engine.connect() as current:
            current.exec_driver_sql(f'SET search_path TO "{schema}"')
            current.commit()
            return run_once(current, RequestQueue, processor=processor)

    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(worker)
        try:
            assert entered.wait(10)
            cancelled = RequestQueue(conn).cancel(record.id)
            assert cancelled.status == 'cancel_requested'
            conn.commit()
        finally:
            release.set()
        assert task.result(timeout=10) == 'cancelled'
    observed = RequestQueue(conn).get(record.id)
    assert observed.status == 'cancelled' and observed.fake_result is None
