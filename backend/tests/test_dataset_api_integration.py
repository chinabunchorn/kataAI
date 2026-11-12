import asyncio
from contextlib import contextmanager
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.main import app
from test_postgres_live import migrated_connection as migrated_connection


HOST = 'http://127.0.0.1:8000'
HEADERS = {'origin': HOST, 'x-kataai-request': '1'}


def test_dataset_routes_fail_closed_without_explicit_configuration(monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.delenv('KATAAI_DATASET_ROOT', raising=False)
    client = TestClient(app, base_url=HOST)
    assert client.get(f'/v1/datasets/{uuid4()}').status_code == 503
    response = client.post('/v1/datasets', content=b'not read', headers={
        **HEADERS, 'content-type': 'multipart/form-data; boundary=abc',
    })
    assert response.status_code == 503
    assert 'not read' not in response.text


def test_unconfigured_upload_does_not_consume_body(monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.delenv('KATAAI_DATASET_ROOT', raising=False)
    sent = []
    reads = []

    async def receive():
        reads.append(True)
        return {'type': 'http.request', 'body': b'private payload', 'more_body': False}

    async def send(message):
        sent.append(message)

    scope = {
        'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
        'method': 'POST', 'scheme': 'http', 'path': '/v1/datasets',
        'raw_path': b'/v1/datasets', 'query_string': b'', 'root_path': '',
        'server': ('127.0.0.1', 8000), 'client': ('127.0.0.1', 1234),
        'headers': [(b'host', b'127.0.0.1:8000'), (b'origin', b'http://127.0.0.1:8000'),
                    (b'x-kataai-request', b'1'), (b'content-type', b'multipart/form-data; boundary=abc')],
    }
    asyncio.run(app(scope, receive, send))
    assert sent[0]['status'] == 503
    assert not reads
    assert b'private payload' not in str(sent).encode()


@pytest.mark.live_postgres
def test_real_app_upload_and_lookup_with_disposable_postgres(request, tmp_path):
    from app.dataset_lookup_api import get_dataset_runtime
    from app.dataset_store import PostgresDatasetStore

    conn, _ = request.getfixturevalue('migrated_connection')
    schema = conn.execute(sa.text('SELECT current_schema()')).scalar_one()
    tmp_path.chmod(0o700)

    class Runtime:
        root = tmp_path

        @contextmanager
        def connection(self):
            with conn.engine.connect() as fresh:
                fresh.exec_driver_sql(f'SET search_path TO "{schema}"')
                yield fresh

    app.dependency_overrides[get_dataset_runtime] = lambda: Runtime()
    try:
        client = TestClient(app, base_url=HOST)
        csv = b'\xef\xbb\xbf' + 'สินค้า,ยอด\nชา,3\n'.encode()
        denied = client.post('/v1/datasets', files={'file': ('sales.csv', csv, 'text/csv')},
                             headers={'origin': 'http://evil.invalid', 'x-kataai-request': '1'})
        assert denied.status_code == 403
        assert conn.execute(sa.text('SELECT count(*) FROM datasets')).scalar_one() == 0
        conn.rollback()
        assert not list(tmp_path.iterdir())

        for bad_csv in (b'a,b\n1\n', b'header\n\xff'):
            invalid = client.post('/v1/datasets', files={'file': ('bad.csv', bad_csv, 'text/csv')},
                                  headers=HEADERS)
            assert invalid.status_code == 422
            assert conn.execute(sa.text('SELECT count(*) FROM datasets')).scalar_one() == 0
            conn.rollback()
            assert {item.name for item in tmp_path.iterdir()} == {'.upload-admission.lock'}

        uploaded = client.post('/v1/datasets', files={'file': ('sales.csv', csv, 'text/csv')}, headers=HEADERS)
        assert uploaded.status_code == 201
        payload = uploaded.json()
        assert set(payload) == {'dataset_id', 'display_name', 'state'}
        assert payload['display_name'] == 'sales.csv' and payload['state'] == 'ready'
        record = PostgresDatasetStore(conn).get(UUID(payload['dataset_id']))
        assert record.lifecycle == 'active' and record.publication_state == 'ready'
        assert (tmp_path / str(record.storage_key)).read_bytes() == csv
        assert str(record.storage_key) not in uploaded.text and str(tmp_path) not in uploaded.text
        assert client.get(f"/v1/datasets/{payload['dataset_id']}").json() == payload
        assert {item.name for item in tmp_path.iterdir()} == {str(record.storage_key), '.upload-admission.lock'}
    finally:
        app.dependency_overrides.pop(get_dataset_runtime, None)
