"""Admission tests use synthetic files and a scripted connection, never a user DB."""
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.dataset_lookup_api import get_dataset_runtime
from app.main import app


class Result:
    def __init__(self, row=None):
        self.row = row

    def one_or_none(self):
        return self.row


class Connection:
    def __init__(self, dataset_id, key):
        self.dataset_id, self.key = dataset_id, key
        self.records = {}
        self.events = []
        self.lifecycle = 'active'
        self.publication_state = 'ready'

    def execute(self, statement, params):
        sql = str(statement)
        if 'pg_advisory_xact_lock' in sql:
            self.events.append('advisory')
            return Result()
        if sql.startswith('SELECT') and 'FROM request_intents' in sql:
            self.events.append('existing')
            return Result(self.records.get(params['key']))
        if 'FROM datasets' in sql:
            assert 'FOR SHARE' in sql
            self.events.append('dataset_lock')
            if params['id'] != self.dataset_id:
                return Result()
            return Result(SimpleNamespace(lifecycle=self.lifecycle, publication_state=self.publication_state, storage_key=self.key))
        if sql.startswith('INSERT INTO request_intents'):
            self.events.append('insert')
            now = datetime.now(timezone.utc)
            row = (params['id'], params['key'], params['dataset'], params['question'], 'queued', None, now, now, None)
            self.records[params['key']] = row
            return Result(row)
        raise AssertionError(sql)

    def commit(self):
        self.events.append('commit')


class Runtime:
    def __init__(self, root, connection):
        self.root, self.conn = root, connection

    @contextmanager
    def connection(self):
        yield self.conn


def setup_request(tmp_path, header):
    tmp_path.chmod(0o700)
    dataset, key = uuid4(), uuid4()
    (tmp_path / str(key)).write_text(header + '\n', encoding='utf-8')
    conn = Connection(dataset, key)
    app.dependency_overrides[get_dataset_runtime] = lambda: Runtime(tmp_path, conn)
    client = TestClient(app, base_url='http://127.0.0.1:8000', headers={
        'origin': 'http://127.0.0.1:8000', 'x-kataai-request': '1'})
    payload = {'schema_version': '1.0', 'client_request_id': str(uuid4()),
               'dataset_id': str(dataset), 'question': 'private question'}
    return client, conn, payload


def test_oversized_header_is_rejected_before_insert(tmp_path):
    client, conn, payload = setup_request(tmp_path, 'private' + 'x' * 1024)
    try:
        response = client.post('/v1/requests', json=payload)
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'MODEL_INPUT_INCOMPATIBLE'
    assert 'private' not in response.text
    assert conn.events == ['advisory', 'existing', 'dataset_lock']
    assert not conn.records


def test_same_key_survives_deleted_dataset_and_missing_file(tmp_path):
    client, conn, payload = setup_request(tmp_path, 'amount')
    try:
        first = client.post('/v1/requests', json=payload)
        assert first.status_code == 201
        (tmp_path / str(conn.key)).unlink()
        conn.lifecycle = 'deleted'
        conn.events.clear()
        second = client.post('/v1/requests', json=payload)
        assert second.status_code == 200
        assert second.json() == first.json()
        assert conn.events == ['advisory', 'existing']
        conn.events.clear()
        conflict = client.post('/v1/requests', json={**payload, 'question': 'different'})
        assert conflict.status_code == 409
        assert conn.events == ['advisory', 'existing']
    finally:
        app.dependency_overrides.clear()


def test_existing_key_ignores_newly_incompatible_file(tmp_path):
    client, conn, payload = setup_request(tmp_path, 'amount')
    try:
        first = client.post('/v1/requests', json=payload)
        assert first.status_code == 201
        (tmp_path / str(conn.key)).write_text('private' + 'x' * 1024 + '\n')
        conn.events.clear()
        second = client.post('/v1/requests', json=payload)
        assert second.status_code == 200
        assert second.json() == first.json()
        assert conn.events == ['advisory', 'existing']
        conn.events.clear()
        conflict = client.post('/v1/requests', json={**payload, 'dataset_id': str(uuid4())})
        assert conflict.status_code == 409
        assert conn.events == ['advisory', 'existing']
    finally:
        app.dependency_overrides.clear()


def test_unreadable_dataset_is_unavailable_without_insert(tmp_path):
    client, conn, payload = setup_request(tmp_path, 'amount')
    (tmp_path / str(conn.key)).unlink()
    try:
        response = client.post('/v1/requests', json=payload)
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    assert 'private' not in response.text
    assert conn.events == ['advisory', 'existing', 'dataset_lock']
    assert not conn.records


def test_combined_input_byte_limit_rejected_without_insert(tmp_path):
    # Each header is under the per-column limit but their combined JSON is not.
    header = ','.join(f'{i:03d}' + 'x' * 997 for i in range(34))
    client, conn, payload = setup_request(tmp_path, header)
    try:
        response = client.post('/v1/requests', json=payload)
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'MODEL_INPUT_INCOMPATIBLE'
    assert conn.events == ['advisory', 'existing', 'dataset_lock']
    assert not conn.records
