"""Logical deletion uses only explicitly opted-in disposable PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from test_dataset_lifecycle import Runtime, client_for
from test_postgres_live import migrated_connection as migrated_connection  # noqa: F401
from test_request_queue import ready


@pytest.fixture
def deletion_db(request):
    conn, _ = request.getfixturevalue('migrated_connection')
    yield conn
    conn.rollback()


def test_unavailable_runtime_is_sanitized():
    from app.dataset_lifecycle_api import create_dataset_lifecycle_router
    app = FastAPI()
    app.include_router(create_dataset_lifecycle_router(lambda: None))
    response = TestClient(app).delete(f'/v1/datasets/{uuid4()}')
    assert response.status_code == 503
    assert response.json() == {'error': {'code': 'DATASET_UNAVAILABLE', 'message': 'Dataset unavailable.'}}


@pytest.mark.live_postgres
@pytest.mark.parametrize('publication_state', ['pending', 'unknown'])
def test_missing_pending_and_lock_contention(deletion_db, tmp_path, publication_state):
    from app.dataset_upload_api import _acquire
    import os
    dataset = ready(deletion_db)
    client = client_for(Runtime(deletion_db, tmp_path))
    assert client.delete(f'/v1/datasets/{uuid4()}').status_code == 404
    deletion_db.execute(sa.text('UPDATE datasets SET publication_state=:state WHERE id=:id'),
                        {'state': publication_state, 'id': dataset})
    deletion_db.commit()
    assert client.delete(f'/v1/datasets/{dataset}').status_code == 409
    fd = _acquire(tmp_path)
    try:
        response = client.delete(f'/v1/datasets/{dataset}')
        assert response.status_code == 503
        assert str(tmp_path) not in response.text
    finally:
        os.close(fd)


@pytest.mark.live_postgres
@pytest.mark.parametrize('state,expected', [('queued', 409), ('running', 409),
    ('cancel_requested', 409), ('unknown', 409), ('cancelled', 200), ('fake_completed', 200)])
def test_request_states_and_file_retention(deletion_db, tmp_path, state, expected):
    from app.request_queue import RequestQueue
    dataset = ready(deletion_db)
    request, _ = RequestQueue(deletion_db).create(uuid4(), dataset, 'secret question')
    deletion_db.commit()
    token = uuid4() if state in ('running', 'cancel_requested') else None
    deletion_db.execute(sa.text('UPDATE request_intents SET status=:state, claim_token=:token WHERE id=:id'),
                     {'state': state, 'token': token, 'id': request.id})
    deletion_db.commit()
    path = tmp_path / 'retained.csv'
    path.write_bytes(b'private,csv\n1,2\n')
    before = path.stat()
    response = client_for(Runtime(deletion_db, tmp_path)).delete(f'/v1/datasets/{dataset}')
    assert response.status_code == expected
    assert 'secret question' not in response.text and str(tmp_path) not in response.text
    assert path.read_bytes() == b'private,csv\n1,2\n'
    after = path.stat()
    assert (before.st_ino, before.st_mode, before.st_size) == (after.st_ino, after.st_mode, after.st_size)
    assert deletion_db.execute(sa.text('SELECT count(*) FROM request_intents WHERE id=:id'), {'id': request.id}).scalar_one() == 1


@pytest.mark.live_postgres
def test_commit_failure_is_unknown_and_sanitized(deletion_db, tmp_path):
    dataset = ready(deletion_db)
    base = Runtime(deletion_db, tmp_path)
    class RuntimeWithUnknownCommit:
        root = tmp_path
        @contextmanager
        def connection(self):
            with base.connection() as conn:
                class Wrapper:
                    execute = conn.execute
                    def commit(self):
                        conn.commit()
                        raise RuntimeError('sensitive commit error')
                yield Wrapper()
    client = client_for(RuntimeWithUnknownCommit())
    response = client.delete(f'/v1/datasets/{dataset}')
    assert response.status_code == 503 and 'sensitive' not in response.text
    assert client.delete(f'/v1/datasets/{dataset}').json()['file_cleanup'] == 'not_attempted'


@pytest.mark.live_postgres
@pytest.mark.parametrize('first', ['create', 'delete'])
def test_create_delete_serialization(deletion_db, tmp_path, first):
    from app.dataset_store import DatasetNotFound
    from app.request_queue import RequestQueue
    dataset = ready(deletion_db)
    runtime = Runtime(deletion_db, tmp_path)
    client = client_for(runtime)
    locked, release = Event(), Event()
    def create():
        with runtime.connection() as conn:
            try:
                result = RequestQueue(conn).create(uuid4(), dataset, 'hello')
                if first == 'create':
                    locked.set()
                    assert release.wait(10)
                conn.commit()
                return result
            except DatasetNotFound:
                return 'not_found'
    def delete():
        return client.delete(f'/v1/datasets/{dataset}')
    if first == 'create':
        with ThreadPoolExecutor(max_workers=2) as pool:
            creating = pool.submit(create)
            assert locked.wait(10)
            deleting = pool.submit(delete)
            release.set()
            assert creating.result(timeout=10)[1]
            assert deleting.result(timeout=10).status_code == 409
    else:
        class PausedRuntime:
            root = tmp_path
            @contextmanager
            def connection(self):
                with runtime.connection() as conn:
                    class Wrapper:
                        def execute(self, statement, *args, **kwargs):
                            result = conn.execute(statement, *args, **kwargs)
                            if 'FROM datasets WHERE id=' in str(statement) and 'FOR UPDATE' in str(statement):
                                locked.set()
                                assert release.wait(10)
                            return result
                        commit = conn.commit
                    yield Wrapper()
        paused_client = client_for(PausedRuntime())
        with ThreadPoolExecutor(max_workers=2) as pool:
            deleting = pool.submit(paused_client.delete, f'/v1/datasets/{dataset}')
            assert locked.wait(10)
            # Hold deletion after the row lock, not merely the claim lock.
            # Creating after commit must not admit work against the tombstone.
            creating = pool.submit(create)
            release.set()
            assert deleting.result(timeout=10).status_code == 200
            assert creating.result(timeout=10) == 'not_found'


@pytest.mark.live_postgres
def test_claim_delete_serialization(deletion_db, tmp_path):
    from app.request_queue import RequestQueue
    dataset = ready(deletion_db)
    record, _ = RequestQueue(deletion_db).create(uuid4(), dataset, 'question')
    deletion_db.commit()
    runtime = Runtime(deletion_db, tmp_path)
    client = client_for(runtime)
    token = uuid4()
    with runtime.connection() as conn:
        assert RequestQueue(conn).claim_next(token).id == record.id
        with ThreadPoolExecutor(max_workers=1) as pool:
            deleting = pool.submit(client.delete, f'/v1/datasets/{dataset}')
            conn.commit()
            assert deleting.result(timeout=10).status_code == 409
    with runtime.connection() as conn:
        assert RequestQueue(conn).complete_fake(record.id, token)
        pending, _ = RequestQueue(conn).create(uuid4(), dataset, 'next')
        conn.commit()
    locked, release, claim_started = Event(), Event(), Event()
    class PausedRuntime:
        root = tmp_path
        @contextmanager
        def connection(self):
            with runtime.connection() as conn:
                class Wrapper:
                    def execute(self, statement, *args, **kwargs):
                        result = conn.execute(statement, *args, **kwargs)
                        if 'pg_advisory_xact_lock(1262571873' in str(statement):
                            locked.set()
                            assert release.wait(10)
                        return result
                    commit = conn.commit
                yield Wrapper()
    def claim():
        with runtime.connection() as conn:
            claim_started.set()
            result = RequestQueue(conn).claim_next(uuid4())
            conn.commit()
            return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        deleting = pool.submit(client_for(PausedRuntime()).delete, f'/v1/datasets/{dataset}')
        assert locked.wait(10)
        claiming = pool.submit(claim)
        assert claim_started.wait(10)
        release.set()
        assert deleting.result(timeout=10).status_code == 409
        assert claiming.result(timeout=10).id == pending.id
