from contextlib import contextmanager
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from test_postgres_live import migrated_connection as migrated_connection


def test_runtime_rejects_missing_configuration(monkeypatch):
    from app.dataset_runtime import load_dataset_runtime

    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.delenv('KATAAI_DATASET_ROOT', raising=False)
    with pytest.raises(ValueError, match='DATASET_CONFIGURATION_ERROR'):
        load_dataset_runtime()


def test_ready_dataset_http_returns_only_safe_fields(monkeypatch):
    from app import dataset_lookup_api
    from app.dataset_store import MemoryDatasetStore

    store = MemoryDatasetStore()
    record = store.create('ข้อมูล.csv')
    store._records[record.id] = replace(record, publication_state='ready')

    class Runtime:
        @contextmanager
        def connection(self):
            yield object()

    monkeypatch.setattr(dataset_lookup_api, 'PostgresDatasetStore', lambda connection: store)
    app = FastAPI()
    app.include_router(dataset_lookup_api.router)
    app.dependency_overrides[dataset_lookup_api.get_dataset_runtime] = lambda: Runtime()
    response = TestClient(app).get(f'/v1/datasets/{record.id}')
    assert response.status_code == 200
    assert response.json() == {'dataset_id': str(record.id), 'display_name': 'ข้อมูล.csv', 'state': 'ready'}
    assert str(record.storage_key) not in response.text


@pytest.mark.parametrize('url', [
    'postgresql://user:secret@database.example/test',
    'postgresql://user:secret@192.0.2.1/test',
    'postgresql://user:secret@localhost/test',
    'postgresql://user:secret@127.0.0.1/test?hostaddr=192.0.2.1',
    'sqlite:///secret',
])
def test_remote_or_invalid_database_rejected_without_secret(monkeypatch, tmp_path, url):
    from app.dataset_runtime import load_dataset_runtime

    monkeypatch.setenv('DATABASE_URL', url)
    monkeypatch.setenv('KATAAI_DATASET_ROOT', str(tmp_path))
    with pytest.raises(ValueError) as exc:
        load_dataset_runtime()
    assert str(exc.value) == 'DATASET_CONFIGURATION_ERROR'


def test_connect_timeout_on_lazy_engine(monkeypatch, tmp_path):
    import sqlalchemy as sa
    from sqlalchemy.pool import NullPool
    from app.dataset_runtime import load_dataset_runtime

    monkeypatch.setenv('DATABASE_URL', 'postgresql://user:secret@127.0.0.1/test')
    monkeypatch.setenv('KATAAI_DATASET_ROOT', str(tmp_path))
    captured = {}
    original = sa.create_engine

    def capture(*args, **kwargs):
        captured.update(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(sa, 'create_engine', capture)
    runtime = load_dataset_runtime()
    assert not captured
    engine = runtime.engine
    try:
        assert isinstance(engine.pool, NullPool)
        assert engine.hide_parameters
        assert captured['connect_args'] == {'connect_timeout': 5}
    finally:
        engine.dispose()


@pytest.mark.parametrize('url', [
    'postgresql://user:secret@127.0.0.1/test',
    'postgresql://user:secret@[::1]/test',
    'postgresql://user:secret@/test?host=/tmp/socket',
])
def test_local_database_configuration_accepted(monkeypatch, tmp_path, url):
    from app.dataset_runtime import load_dataset_runtime

    monkeypatch.setenv('DATABASE_URL', url)
    monkeypatch.setenv('KATAAI_DATASET_ROOT', str(tmp_path))
    runtime = load_dataset_runtime()
    assert runtime.root == tmp_path
    assert 'secret' not in repr(runtime)


@pytest.mark.parametrize('kind', ['missing', 'relative', 'file', 'symlink', 'symlink-slash', 'public'])
def test_invalid_root_is_rejected_without_changes(monkeypatch, tmp_path, kind):
    from app.dataset_runtime import load_dataset_runtime

    monkeypatch.setenv('DATABASE_URL', 'postgresql://user@127.0.0.1/test')
    root = tmp_path / 'root'
    if kind == 'relative':
        value = 'relative'
    else:
        value = str(root)
        if kind == 'file':
            root.touch()
        elif kind in ('symlink', 'symlink-slash'):
            root.symlink_to(tmp_path, target_is_directory=True)
            if kind == 'symlink-slash':
                value += '/'
        elif kind == 'public':
            root.mkdir(mode=0o755)
            root.chmod(0o755)
    monkeypatch.setenv('KATAAI_DATASET_ROOT', value)
    with pytest.raises(ValueError, match='DATASET_CONFIGURATION_ERROR'):
        load_dataset_runtime()
    if kind == 'missing':
        assert not root.exists()
    if kind == 'public':
        assert root.stat().st_mode & 0o777 == 0o755


def test_inherited_pg_redirection_is_rejected(monkeypatch, tmp_path):
    from app.dataset_runtime import load_dataset_runtime

    monkeypatch.setenv('DATABASE_URL', 'postgresql://user@127.0.0.1/test')
    monkeypatch.setenv('KATAAI_DATASET_ROOT', str(tmp_path))
    monkeypatch.setenv('PGHOSTADDR', '192.0.2.1')
    with pytest.raises(ValueError, match='DATASET_CONFIGURATION_ERROR'):
        load_dataset_runtime()


def test_http_fail_closed_and_does_not_expose_errors(monkeypatch, caplog):
    from app import dataset_lookup_api as api
    from app.dataset_store import MemoryDatasetStore

    store = MemoryDatasetStore()
    pending = store.create('pending.csv')
    unknown = store.create('unknown.csv')
    deleted = store.create('deleted.csv')
    store._records[unknown.id] = replace(unknown, publication_state='unknown')
    store._records[deleted.id] = replace(deleted, lifecycle='deleted', publication_state='ready')

    class Runtime:
        @contextmanager
        def connection(self):
            yield object()

    monkeypatch.setattr(api, 'PostgresDatasetStore', lambda connection: store)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_dataset_runtime] = lambda: Runtime()
    client = TestClient(app)
    responses = [client.get(f'/v1/datasets/{item.id}') for item in (pending, unknown, deleted)]
    assert [r.status_code for r in responses] == [503, 503, 404]
    assert responses[0].json() == responses[1].json()
    assert client.get(f'/v1/datasets/{uuid4()}').json() == responses[2].json()
    for bad in ('bad-secret', str(pending.id).upper(), pending.id.hex):
        response = client.get(f'/v1/datasets/{bad}')
        assert response.status_code == 422
        assert bad not in response.text
    assert 'access-control-allow-origin' not in responses[0].headers

    class Broken:
        @contextmanager
        def connection(self):
            raise RuntimeError('secret sql path password')
            yield

    app.dependency_overrides[api.get_dataset_runtime] = lambda: Broken()
    response = client.get(f'/v1/datasets/{pending.id}')
    assert response.status_code == 503
    assert response.json() == responses[0].json()
    assert 'secret' not in response.text + caplog.text


def test_http_invalid_configuration_is_sanitized(monkeypatch):
    from app.dataset_lookup_api import router

    monkeypatch.setenv('DATABASE_URL', 'postgresql://user:secret@remote.example/test')
    monkeypatch.delenv('KATAAI_DATASET_ROOT', raising=False)
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).get(f'/v1/datasets/{uuid4()}')
    assert response.status_code == 503
    assert 'secret' not in response.text


@pytest.mark.live_postgres
def test_lookup_fresh_postgres_connection(request, tmp_path):
    import sqlalchemy as sa
    from app import dataset_lookup_api as api
    from app.dataset_store import PostgresDatasetStore

    conn, _ = request.getfixturevalue('migrated_connection')
    schema = conn.execute(sa.text('SELECT current_schema()')).scalar_one()
    store = PostgresDatasetStore(conn)
    ready = store.create('ready.csv')
    pending = store.create('pending.csv')
    deleted = store.create('deleted.csv')
    store.mark_ready(ready)
    conn.execute(sa.text("UPDATE datasets SET lifecycle='deleted', deleted_at=now() WHERE id=:id"),
                 {'id': deleted.id})
    unknown_id = uuid4()
    conn.execute(sa.text("INSERT INTO datasets (id, display_name, storage_key) "
                         "VALUES (:id, 'legacy.csv', :key)"), {'id': unknown_id, 'key': uuid4()})
    conn.commit()

    class Runtime:
        root = tmp_path

        @contextmanager
        def connection(self):
            with conn.engine.connect() as fresh:
                fresh.exec_driver_sql(f'SET search_path TO "{schema}"')
                yield fresh

    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_dataset_runtime] = lambda: Runtime()
    client = TestClient(app)
    result = client.get(f'/v1/datasets/{ready.id}')
    assert result.json() == {'dataset_id': str(ready.id), 'display_name': 'ready.csv', 'state': 'ready'}
    assert str(ready.storage_key) not in result.text
    assert client.get(f'/v1/datasets/{pending.id}').status_code == 503
    assert client.get(f'/v1/datasets/{unknown_id}').status_code == 503
    assert client.get(f'/v1/datasets/{deleted.id}').status_code == 404
    assert client.get(f'/v1/datasets/{uuid4()}').status_code == 404
