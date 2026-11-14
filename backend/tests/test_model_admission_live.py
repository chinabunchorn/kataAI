"""Real HTTP admission against an explicitly provisioned disposable PostgreSQL DB.

No model or worker is run. The migrated fixture owns and drops only its isolated
schema; the dataset root is a private per-test temporary directory.
"""
import json
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.dataset_lookup_api import get_dataset_runtime
from app.main import app
from test_postgres_live import migrated_connection as migrated_connection


pytestmark = pytest.mark.live_postgres
HEADERS = {'origin': 'http://127.0.0.1:8000', 'x-kataai-request': '1'}


@pytest.fixture
def admission(request, tmp_path):
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

    old_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_dataset_runtime] = lambda: Runtime()
    try:
        with TestClient(app, base_url='http://127.0.0.1:8000', headers=HEADERS) as client:
            yield client, conn, tmp_path
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(old_overrides)


def upload(client, columns):
    # Header-only CSV is valid, and distinct names are required at intake.
    response = client.post('/v1/datasets', files={
        'file': ('synthetic.csv', (','.join(columns) + '\n').encode('utf-8'), 'text/csv')})
    assert response.status_code == 201, response.text
    return response.json()['dataset_id']


def payload(dataset_id, question):
    return {'schema_version': '1.0', 'client_request_id': str(uuid4()),
            'dataset_id': dataset_id, 'question': question}


def count_requests(conn):
    count = conn.execute(sa.text('SELECT count(*) FROM request_intents')).scalar_one()
    conn.rollback()
    return count


def file_path(conn, root, dataset_id):
    key = conn.execute(sa.text('SELECT storage_key FROM datasets WHERE id=:id'),
                       {'id': UUID(dataset_id)}).scalar_one()
    conn.rollback()
    return root / str(key)


def assert_sanitized(response, *secrets):
    assert response.json()['error']['code'] == 'MODEL_INPUT_INCOMPATIBLE'
    for secret in secrets:
        assert secret not in response.text


def test_uploaded_oversize_column_rejected_before_queue(admission):
    client, conn, _ = admission
    column = 'PRIVATE_COLUMN_' + 'x' * (1025 - len('PRIVATE_COLUMN_'))
    assert len(column.encode('utf-8')) == 1025
    dataset_id = upload(client, [column])
    question = 'PRIVATE_QUESTION_do_not_echo'
    response = client.post('/v1/requests', json=payload(dataset_id, question))
    assert response.status_code == 422
    assert_sanitized(response, 'PRIVATE_COLUMN_', question)
    assert count_requests(conn) == 0


def test_encoded_aggregate_limit_and_valid_inputs(admission):
    client, conn, _ = admission
    # All columns satisfy the individual 1024-byte limit, but their combined
    # compact UTF-8 JSON with the question can cross the 32768-byte limit.
    columns = [f'COL{i:02d}_' + 'x' * 994 for i in range(32)]
    assert all(len(c.encode('utf-8')) == 1000 for c in columns)
    dataset_id = upload(client, columns)
    base = len(json.dumps({'question': '', 'columns': columns}, ensure_ascii=False,
                          separators=(',', ':')).encode('utf-8'))
    question = 'q' * (32768 - base)
    assert 1 <= len(question) < 4096
    assert len(json.dumps({'question': question, 'columns': columns}, ensure_ascii=False,
                          separators=(',', ':')).encode('utf-8')) == 32768

    oversized_question = question + 'S'
    rejected = client.post('/v1/requests', json=payload(dataset_id, oversized_question))
    assert rejected.status_code == 422
    assert_sanitized(rejected, columns[0], oversized_question)
    assert count_requests(conn) == 0

    boundary = client.post('/v1/requests', json=payload(dataset_id, question))
    assert boundary.status_code == 201
    assert boundary.json()['status'] == 'queued'
    assert count_requests(conn) == 1

    short_dataset = upload(client, ['product', 'amount'])
    short = client.post('/v1/requests', json=payload(short_dataset, 'What is the total?'))
    assert short.status_code == 201
    assert short.json()['status'] == 'queued'
    assert count_requests(conn) == 2


@pytest.mark.parametrize('unavailable', ['deleted', 'missing_file'])
def test_replay_and_conflict_precede_dataset_readiness(admission, unavailable):
    client, conn, root = admission
    dataset_id = upload(client, ['product', 'amount'])
    original = payload(dataset_id, 'PRIVATE_ORIGINAL_question')
    created = client.post('/v1/requests', json=original)
    assert created.status_code == 201
    assert created.json()['status'] == 'queued'
    if unavailable == 'deleted':
        conn.execute(sa.text("UPDATE datasets SET lifecycle='deleted', deleted_at=clock_timestamp() WHERE id=:id"),
                     {'id': UUID(dataset_id)})
        conn.commit()
    else:
        file_path(conn, root, dataset_id).unlink()

    replay = client.post('/v1/requests', json=original)
    assert replay.status_code == 200
    assert replay.json() == created.json()
    conflict_question = 'PRIVATE_CONFLICT_question'
    conflict = client.post('/v1/requests', json={**original, 'question': conflict_question})
    assert conflict.status_code == 409
    assert conflict.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    assert original['question'] not in conflict.text
    assert conflict_question not in conflict.text
    assert count_requests(conn) == 1


def test_delete_cannot_pass_an_inflight_admission_lock(admission, monkeypatch):
    from app import dataset_columns
    from app.dataset_lifecycle import DatasetDeletionConflict, delete_dataset
    from sqlalchemy.exc import OperationalError

    client, conn, root = admission
    dataset_id = upload(client, ['product', 'amount'])
    entered, release = Event(), Event()
    original_read = dataset_columns.read_dataset_columns

    def paused_read(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original_read(*args, **kwargs)

    monkeypatch.setattr(dataset_columns, 'read_dataset_columns', paused_read)
    schema = conn.execute(sa.text('SELECT current_schema()')).scalar_one()
    conn.commit()

    @contextmanager
    def delete_connection():
        with conn.engine.connect() as current:
            current.exec_driver_sql(f'SET search_path TO "{schema}"')
            current.exec_driver_sql("SET lock_timeout TO '300ms'")
            current.commit()
            yield current

    class DeleteRuntime:
        connection = staticmethod(delete_connection)

        def __init__(self, dataset_root):
            self.root = dataset_root

    runtime = DeleteRuntime(root)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, '/v1/requests', json=payload(dataset_id, 'total?'))
        try:
            assert entered.wait(5)
            with pytest.raises(OperationalError):
                delete_dataset(runtime, UUID(dataset_id))
        finally:
            release.set()
        assert future.result(timeout=10).status_code == 201
    with pytest.raises(DatasetDeletionConflict):
        delete_dataset(runtime, UUID(dataset_id))
    assert count_requests(conn) == 1


def test_missing_dataset_file_returns_unavailable_without_queue(admission):
    client, conn, root = admission
    dataset_id = upload(client, ['PRIVATE_COLUMN', 'amount'])
    file_path(conn, root, dataset_id).unlink()
    question = 'PRIVATE_QUESTION_do_not_echo'
    response = client.post('/v1/requests', json=payload(dataset_id, question))
    assert response.status_code == 503
    assert 'PRIVATE_COLUMN' not in response.text
    assert question not in response.text
    assert str(root) not in response.text
    assert count_requests(conn) == 0
