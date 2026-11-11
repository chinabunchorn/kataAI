from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from test_postgres_live import migrated_connection as migrated_connection  # shared fixture


@pytest.fixture(params=['fake', pytest.param('postgres', marks=pytest.mark.live_postgres)])
def store_factory(request):
    from app.dataset_store import MemoryDatasetStore, PostgresDatasetStore

    def make(ids):
        sequence = iter(ids)
        if request.param == 'fake':
            return MemoryDatasetStore(id_factory=lambda: next(sequence),
                                      clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
        conn, _ = request.getfixturevalue('migrated_connection')
        return PostgresDatasetStore(conn, id_factory=lambda: next(sequence))
    return make


@pytest.mark.parametrize('name', ['ข้อมูล.csv', "x'); DROP TABLE datasets;--.csv"])
def test_create_and_lookup_metadata(store_factory, name):
    dataset_id = UUID('11111111-1111-4111-8111-111111111111')
    key = UUID('22222222-2222-4222-8222-222222222222')
    store = store_factory([dataset_id, key])
    record = store.create(name)
    assert record.id == dataset_id and record.storage_key == key
    assert record.display_name == name
    assert record.lifecycle == 'active' and record.deleted_at is None
    assert record.created_at.tzinfo is not None
    assert store.get(dataset_id) == record


@pytest.mark.parametrize('name', ['', ' x ', '.', '..', 'a/b', 'a\\b', 'x\n', '\x00', '\ud800', 'x' * 256, None, 1])
def test_rejects_invalid_names(store_factory, name):
    from app.dataset_store import InvalidDatasetMetadata
    store = store_factory([uuid4(), uuid4()])
    with pytest.raises(InvalidDatasetMetadata, match='INVALID_DATASET_METADATA'):
        store.create(name)


def test_missing_and_invalid_lookup(store_factory):
    from app.dataset_store import DatasetNotFound, InvalidDatasetMetadata
    store = store_factory([])
    with pytest.raises(DatasetNotFound, match='DATASET_NOT_FOUND'):
        store.get(uuid4())
    with pytest.raises(InvalidDatasetMetadata, match='INVALID_DATASET_METADATA'):
        store.get('not-a-uuid')


@pytest.mark.parametrize('collision', ['id', 'key'])
def test_duplicate_is_stable_and_preserves_original(store_factory, collision):
    from app.dataset_store import DuplicateDatasetMetadata
    first_id, first_key, second_id, second_key = (uuid4() for _ in range(4))
    if collision == 'id':
        second_id = first_id
    else:
        second_key = first_key
    store = store_factory([first_id, first_key, second_id, second_key])
    original = store.create('first.csv')
    with pytest.raises(DuplicateDatasetMetadata, match='DUPLICATE_DATASET_METADATA'):
        store.create('second.csv')
    assert store.get(first_id) == original


@pytest.mark.live_postgres
def test_lookup_preserves_deleted_row(request):
    import sqlalchemy as sa
    from app.dataset_store import PostgresDatasetStore
    conn, _ = request.getfixturevalue('migrated_connection')
    dataset_id, key = uuid4(), uuid4()
    conn.execute(sa.text("INSERT INTO datasets (id, display_name, storage_key, lifecycle, deleted_at) "
                         "VALUES (:id, :name, :key, 'deleted', now())"),
                 {'id': dataset_id, 'name': 'old.csv', 'key': key})
    record = PostgresDatasetStore(conn).get(dataset_id)
    assert record.lifecycle == 'deleted' and record.deleted_at is not None
    assert record.storage_key == key and record.created_at.tzinfo is not None


def test_generator_must_return_uuids(store_factory):
    from app.dataset_store import InvalidDatasetMetadata
    store = store_factory(['not-a-uuid', uuid4()])
    with pytest.raises(InvalidDatasetMetadata):
        store.create('valid.csv')


@pytest.mark.parametrize('clock_value', [None, datetime(2026, 1, 1), 'not-a-time'])
def test_fake_rejects_invalid_clock(clock_value):
    from app.dataset_store import InvalidDatasetMetadata, MemoryDatasetStore
    store = MemoryDatasetStore(clock=lambda: clock_value)
    with pytest.raises(InvalidDatasetMetadata):
        store.create('valid.csv')


@pytest.mark.live_postgres
def test_database_error_is_sanitized(request):
    import traceback
    import sqlalchemy as sa
    from app.dataset_store import DatasetStorageError, PostgresDatasetStore
    conn, _ = request.getfixturevalue('migrated_connection')
    # An intentionally missing relation generates a real SQLAlchemy DBAPIError.
    conn.execute(sa.text('ALTER TABLE datasets RENAME TO missing_for_test'))
    try:
        with pytest.raises(DatasetStorageError) as exc:
            PostgresDatasetStore(conn).get(uuid4())
        rendered = ''.join(traceback.format_exception(exc.value))
        assert str(exc.value) == 'DATASET_STORAGE_ERROR'
        assert 'SELECT' not in rendered and 'psycopg' not in rendered
    finally:
        conn.rollback()


@pytest.mark.live_postgres
def test_caller_can_rollback_create(request):
    from app.dataset_store import DatasetNotFound, PostgresDatasetStore
    conn, _ = request.getfixturevalue('migrated_connection')
    store = PostgresDatasetStore(conn)
    record = store.create('rollback.csv')
    conn.rollback()
    with pytest.raises(DatasetNotFound):
        store.get(record.id)
