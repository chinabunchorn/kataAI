from uuid import uuid4

import pytest

from test_postgres_live import migrated_connection as migrated_connection


def test_pending_dataset_is_not_usable():
    from app.dataset_store import MemoryDatasetStore
    from app.ready_dataset import DatasetUnavailable, get_ready_dataset

    store = MemoryDatasetStore()
    record = store.create('pending.csv')
    with pytest.raises(DatasetUnavailable, match='DATASET_UNAVAILABLE'):
        get_ready_dataset(store, record.id)


def test_ready_result_contains_only_safe_metadata():
    from dataclasses import asdict, replace
    from app.dataset_store import MemoryDatasetStore
    from app.ready_dataset import get_ready_dataset

    store = MemoryDatasetStore()
    record = store.create('ข้อมูล.csv')
    store._records[record.id] = replace(record, publication_state='ready')
    result = get_ready_dataset(store, record.id)
    assert asdict(result) == {'dataset_id': record.id, 'display_name': 'ข้อมูล.csv', 'state': 'ready'}


@pytest.mark.parametrize('state', ['unknown', 'pending'])
def test_incomplete_records_are_unavailable(state):
    from dataclasses import replace
    from app.dataset_store import MemoryDatasetStore
    from app.ready_dataset import DatasetUnavailable, get_ready_dataset

    store = MemoryDatasetStore()
    record = store.create('incomplete.csv')
    store._records[record.id] = replace(record, publication_state=state)
    with pytest.raises(DatasetUnavailable):
        get_ready_dataset(store, record.id)


def test_deleted_record_is_not_found_even_if_ready():
    from dataclasses import replace
    from app.dataset_store import DatasetNotFound, MemoryDatasetStore
    from app.ready_dataset import get_ready_dataset

    store = MemoryDatasetStore()
    record = store.create('deleted.csv')
    store._records[record.id] = replace(record, lifecycle='deleted', publication_state='ready')
    with pytest.raises(DatasetNotFound):
        get_ready_dataset(store, record.id)


def test_absent_and_invalid_ids_propagate_sanitized_errors():
    from app.dataset_store import DatasetNotFound, InvalidDatasetMetadata, MemoryDatasetStore
    from app.ready_dataset import get_ready_dataset

    store = MemoryDatasetStore()
    with pytest.raises(DatasetNotFound):
        get_ready_dataset(store, uuid4())
    with pytest.raises(InvalidDatasetMetadata):
        get_ready_dataset(store, 'not-a-uuid-secret')


@pytest.mark.live_postgres
def test_published_file_is_ready_on_fresh_postgres_connection(request, tmp_path):
    import io
    from app.dataset_publication import publish_dataset_on_connection
    from app.dataset_store import PostgresDatasetStore
    from app.ready_dataset import get_ready_dataset
    import sqlalchemy as sa

    conn, _ = request.getfixturevalue('migrated_connection')
    schema = conn.execute(sa.text('SELECT current_schema()')).scalar_one()
    conn.commit()
    root = tmp_path / 'private'
    root.mkdir(mode=0o700)
    content = '\ufeffชื่อ,จำนวน\nชา,2\n'.encode()
    result = publish_dataset_on_connection(conn, root, 'ข้อมูล.csv', io.BytesIO(content))
    assert (root / str(result.dataset.storage_key)).read_bytes() == content
    with conn.engine.connect() as fresh:
        fresh.exec_driver_sql(f'SET search_path TO "{schema}"')
        ready = get_ready_dataset(PostgresDatasetStore(fresh), result.dataset.id)
    assert ready.dataset_id == result.dataset.id
    assert ready.display_name == 'ข้อมูล.csv'
    assert ready.state == 'ready'
