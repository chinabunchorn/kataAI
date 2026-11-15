"""Explicitly opted-in tests; the caller must provision a disposable database."""
import os
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError

from app.database_config import database_url


BACKEND = Path(__file__).resolve().parents[1]


def cleanup_test_schema(conn, schema):
    # Only generated fixture schemas are accepted; all cleanup is one transaction.
    import re

    if not re.fullmatch(r'kataai_test_[0-9a-f]{32}', schema):
        raise ValueError('Refusing to clean up a non-test schema')
    conn.rollback()
    with conn.begin():
        conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{schema}"."request_intents" RESTRICT')
        conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{schema}"."datasets" RESTRICT')
        conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{schema}"."alembic_version" RESTRICT')
        conn.exec_driver_sql(f'DROP SCHEMA "{schema}" RESTRICT')


@pytest.fixture
def migrated_connection(monkeypatch):
    try:
        url = database_url(os.environ['TEST_DATABASE_URL'])
    except ValueError as exc:
        pytest.fail(str(exc), pytrace=False)
    monkeypatch.setenv('DATABASE_URL', os.environ['TEST_DATABASE_URL'])
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool, hide_parameters=True)
    schema = 'kataai_test_' + uuid4().hex
    with engine.connect() as conn:
        # Only this freshly generated schema is ever dropped; never the database.
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        conn.commit()
        try:
            conn.exec_driver_sql(f'SET search_path TO "{schema}"')
            conn.commit()
            config = Config(str(BACKEND / 'alembic.ini'))
            config.attributes['connection'] = conn
            command.upgrade(config, 'head')
            conn.commit()
            yield conn, config
        finally:
            cleanup_test_schema(conn, schema)
    engine.dispose()


def test_cleanup_uses_only_restrict_for_known_objects():
    from unittest.mock import MagicMock

    conn = MagicMock()
    schema = 'kataai_test_' + 'a' * 32
    cleanup_test_schema(conn, schema)
    statements = [call.args[0] for call in conn.exec_driver_sql.call_args_list]
    assert statements == [
        f'DROP TABLE IF EXISTS "{schema}"."request_intents" RESTRICT',
        f'DROP TABLE IF EXISTS "{schema}"."datasets" RESTRICT',
        f'DROP TABLE IF EXISTS "{schema}"."alembic_version" RESTRICT',
        f'DROP SCHEMA "{schema}" RESTRICT',
    ]


@pytest.mark.live_postgres
def test_cleanup_preserves_external_dependent_view(migrated_connection):
    conn, _ = migrated_connection
    schema = conn.execute(sa.text('SELECT current_schema()')).scalar_one()
    external = 'kataai_test_external_' + uuid4().hex
    conn.exec_driver_sql(f'CREATE SCHEMA "{external}"')
    conn.commit()
    try:
        conn.exec_driver_sql(f'CREATE VIEW "{external}"."dependent" AS '
                             f'SELECT id FROM "{schema}"."datasets"')
        conn.commit()
        with pytest.raises(sa.exc.DBAPIError):
            cleanup_test_schema(conn, schema)
        assert conn.execute(sa.text('SELECT to_regclass(:name)'),
                            {'name': f'{external}.dependent'}).scalar_one() is not None
        assert conn.execute(sa.text('SELECT to_regclass(:name)'),
                            {'name': f'{schema}.datasets'}).scalar_one() is not None
    finally:
        conn.rollback()
        with conn.begin():
            conn.exec_driver_sql(f'DROP VIEW IF EXISTS "{external}"."dependent" RESTRICT')
            conn.exec_driver_sql(f'DROP SCHEMA "{external}" RESTRICT')


@pytest.mark.live_postgres
def test_cleanup_preserves_schema_with_unexpected_object(migrated_connection):
    conn, _ = migrated_connection
    schema = conn.execute(sa.text('SELECT current_schema()')).scalar_one()
    conn.exec_driver_sql(f'CREATE TABLE "{schema}"."unexpected" (id integer)')
    conn.commit()
    try:
        with pytest.raises(sa.exc.DBAPIError):
            cleanup_test_schema(conn, schema)
        for table in ('datasets', 'alembic_version', 'unexpected'):
            assert conn.execute(sa.text('SELECT to_regclass(:name)'),
                                {'name': f'{schema}.{table}'}).scalar_one() is not None
    finally:
        conn.rollback()
        with conn.begin():
            conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{schema}"."unexpected" RESTRICT')


@pytest.mark.live_postgres
def test_ready_compare_and_swap_concurrent_and_tombstone(migrated_connection):
    from concurrent.futures import ThreadPoolExecutor
    from dataclasses import replace
    from threading import Barrier

    from app.dataset_store import DatasetPublicationConflict, PostgresDatasetStore

    conn, _ = migrated_connection
    schema = conn.execute(sa.text('SELECT current_schema()')).scalar_one()
    store = PostgresDatasetStore(conn)
    record = store.create('race.csv')
    tombstone = store.create('deleted.csv')
    conn.execute(sa.text("UPDATE datasets SET lifecycle='deleted', deleted_at=now() WHERE id=:id"),
                 {'id': tombstone.id})
    conn.commit()
    with pytest.raises(DatasetPublicationConflict):
        store.mark_ready(tombstone)
    with pytest.raises(DatasetPublicationConflict):
        store.mark_ready(replace(record, storage_key=uuid4()))
    conn.rollback()
    gate = Barrier(2)

    def contend():
        with conn.engine.connect() as other:
            other.exec_driver_sql(f'SET search_path TO "{schema}"')
            other.commit()
            gate.wait(timeout=5)
            try:
                PostgresDatasetStore(other).mark_ready(record)
                other.commit()
                return 'ready'
            except DatasetPublicationConflict:
                other.rollback()
                return 'conflict'

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(lambda _: contend(), range(2))) == ['conflict', 'ready']
    assert store.get(record.id).publication_state == 'ready'
    assert store.get(tombstone.id).publication_state == 'pending'


@pytest.mark.live_postgres
def test_incomplete_listing_is_read_only_and_includes_legacy(migrated_connection):
    from app.dataset_store import PostgresDatasetStore

    conn, _ = migrated_connection
    store = PostgresDatasetStore(conn)
    pending = store.create('pending.csv')
    legacy_id = uuid4()
    conn.execute(sa.text("INSERT INTO datasets (id, display_name, storage_key) "
                         "VALUES (:id, 'old.csv', :key)"), {'id': legacy_id, 'key': uuid4()})
    conn.commit()
    first = store.list_incomplete(limit=1)
    assert len(first) == 1
    found = first + store.list_incomplete(limit=1, after=(first[0].created_at, first[0].id))
    assert {row.id for row in found} == {pending.id, legacy_id}
    with pytest.raises(ValueError):
        store.list_incomplete(limit=1001)
    conn.rollback()
    assert store.get(pending.id).publication_state == 'pending'


@pytest.mark.live_postgres
def test_upgrade_preserves_legacy_rows_as_unknown(migrated_connection):
    from app.dataset_store import PostgresDatasetStore

    conn, config = migrated_connection
    command.downgrade(config, '0001_datasets')
    dataset_id, key = uuid4(), uuid4()
    conn.execute(sa.text('INSERT INTO datasets (id, display_name, storage_key) '
                         "VALUES (:id, 'legacy.csv', :key)"), {'id': dataset_id, 'key': key})
    conn.commit()
    command.upgrade(config, 'head')
    conn.commit()
    record = PostgresDatasetStore(conn).get(dataset_id)
    assert record.publication_state == 'unknown'
    assert record.lifecycle == 'active' and record.storage_key == key
    pending = PostgresDatasetStore(conn).create('new.csv')
    assert pending.publication_state == 'pending'
    schema = conn.execute(sa.text('SELECT current_schema()')).scalar_one()
    conn.commit()
    with conn.engine.connect() as reconnected:
        reconnected.exec_driver_sql(f'SET search_path TO "{schema}"')
        observed = {row.id: row.publication_state for row in PostgresDatasetStore(reconnected).list_incomplete()}
        assert observed[dataset_id] == 'unknown'
        assert observed[pending.id] == 'pending'
    with pytest.raises(IntegrityError), conn.begin_nested():
        conn.execute(sa.text("UPDATE datasets SET publication_state='invalid' WHERE id=:id"),
                     {'id': dataset_id})


@pytest.mark.live_postgres
def test_upgrade_constraints_and_downgrade(migrated_connection):
    conn, config = migrated_connection
    schema = conn.execute(sa.text('SELECT current_schema()')).scalar_one()
    assert schema.startswith('kataai_test_')
    assert conn.execute(sa.text("SELECT table_schema FROM information_schema.tables "
                                "WHERE table_schema = current_schema() "
                                "AND table_name = 'alembic_version'")).scalar_one() == schema
    insert = sa.text('INSERT INTO datasets (id, display_name, storage_key) VALUES (:id, :name, :key)')
    dataset_id, key = uuid4(), uuid4()
    conn.execute(insert, {'id': dataset_id, 'name': 'ข้อมูล.csv', 'key': key})
    row = conn.execute(sa.text('SELECT lifecycle, created_at, deleted_at FROM datasets')).one()
    assert row.lifecycle == 'active' and row.created_at is not None and row.deleted_at is None
    for name in ('', '../bad', 'bad/name', 'bad\\name', ' x ', '..', 'bad\nname'):
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(insert, {'id': uuid4(), 'name': name, 'key': uuid4()})
    with pytest.raises(IntegrityError), conn.begin_nested():
        conn.execute(insert, {'id': uuid4(), 'name': 'other.csv', 'key': key})
    with pytest.raises(IntegrityError), conn.begin_nested():
        conn.execute(sa.text("UPDATE datasets SET lifecycle='deleted' WHERE id=:id"), {'id': dataset_id})
    conn.execute(sa.text("UPDATE datasets SET lifecycle='deleted', deleted_at=now() WHERE id=:id"),
                 {'id': dataset_id})
    assert conn.execute(sa.text('SELECT lifecycle FROM datasets')).scalar_one() == 'deleted'
    conn.commit()
    command.downgrade(config, 'base')
    conn.commit()
    assert sa.inspect(conn).has_table('datasets') is False
    command.upgrade(config, 'head')
    conn.commit()
    assert sa.inspect(conn).has_table('datasets') is True
