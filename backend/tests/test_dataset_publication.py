from datetime import datetime, timezone
from io import BytesIO
from uuid import UUID

import pytest
import sqlalchemy as sa

import app.dataset_publication as service
from app.dataset_store import PostgresDatasetStore
from test_postgres_live import migrated_connection as migrated_connection


class Result:
    def __init__(self, row):
        self.row = row

    def one_or_none(self):
        return self.row


class Connection:
    def __init__(self):
        self.pending = None
        self.committed = None

    def execute(self, statement, params):
        if str(statement).startswith('UPDATE'):
            self.pending = (*self.committed[:6], 'ready')
        else:
            self.pending = (params['id'], params['name'], params['key'],
                            datetime.now(timezone.utc), 'active', None, 'pending')
        return Result(self.pending)

    def commit(self):
        self.committed = self.pending


def make_store(connection):
    ids = iter([UUID(int=1), UUID(int=2)])
    return PostgresDatasetStore(connection, id_factory=lambda: next(ids))


def test_unsupported_metadata_store_fails_before_mutating_state(tmp_path):
    from app.dataset_store import DatasetNotFound, MemoryDatasetStore

    store = MemoryDatasetStore(id_factory=lambda: UUID(int=1))
    with pytest.raises(TypeError, match='INVALID_PUBLICATION_STORE'):
        service.publish_dataset(store, lambda: None, tmp_path, 'sample.csv', BytesIO(b'a\n'))  # type: ignore[arg-type]
    with pytest.raises(DatasetNotFound):
        store.get(UUID(int=1))
    assert list(tmp_path.iterdir()) == []


def test_commits_identity_before_publishing_real_csv(tmp_path):
    connection = Connection()
    result = service.publish_dataset(make_store(connection), connection.commit, tmp_path,
                                     'sample.csv', BytesIO(b'a\n1\n'))
    assert connection.committed[:3] == (result.dataset.id, 'sample.csv', result.dataset.storage_key)
    assert (tmp_path / str(result.dataset.storage_key)).read_bytes() == b'a\n1\n'
    assert result.csv.row_count == 1
    assert result.dataset.publication_state == 'ready'


def test_connection_entrypoint_binds_store_and_commit(tmp_path):
    connection = Connection()
    result = service.publish_dataset_on_connection(connection, tmp_path, 'sample.csv', BytesIO(b'a\n'))
    assert connection.committed[0] == result.dataset.id
    assert (tmp_path / str(connection.committed[2])).read_bytes() == b'a\n'


def test_commit_response_lost_preserves_identity_and_does_not_publish(tmp_path):
    connection = Connection()

    def lost_response():
        connection.commit()
        raise OSError('sensitive database detail')

    with pytest.raises(Exception) as caught:
        service.publish_dataset(make_store(connection), lost_response, tmp_path,
                                'sample.csv', BytesIO(b'a\n1\n'))
    error = caught.value
    assert type(error).__name__ == 'DatasetPublicationError'
    assert error.phase == 'commit_unknown'
    assert error.dataset.id == connection.committed[0]
    assert error.dataset.storage_key == connection.committed[2]
    assert 'sensitive' not in str(error)
    assert list(tmp_path.iterdir()) == []


def test_commit_interruption_is_sanitized_and_never_publishes(tmp_path):
    connection = Connection()

    def interrupted():
        connection.commit()
        raise KeyboardInterrupt('secret')

    with pytest.raises(KeyboardInterrupt) as caught:
        service.publish_dataset(make_store(connection), interrupted, tmp_path,
                                'sample.csv', BytesIO(b'a\n'))
    assert caught.value.args == ()
    assert list(tmp_path.iterdir()) == []
    assert connection.committed is not None


@pytest.mark.parametrize('conflict, expected_phase', [(False, 'ready_update_unknown'), (True, 'ready_conflict')])
def test_ready_update_failure_preserves_file_without_final_commit(tmp_path, monkeypatch, conflict, expected_phase):
    from app.dataset_store import DatasetPublicationConflict

    connection = Connection()
    store = make_store(connection)
    commits = []

    def commit():
        commits.append(1)
        connection.commit()

    def fail_update(dataset):
        if conflict:
            raise DatasetPublicationConflict()
        raise OSError('private detail')

    monkeypatch.setattr(store, 'mark_ready', fail_update)
    with pytest.raises(service.DatasetPublicationError) as caught:
        service.publish_dataset(store, commit, tmp_path, 'sample.csv', BytesIO(b'a\n1\n'))
    assert caught.value.phase == expected_phase
    assert len(commits) == 1
    assert connection.committed is not None
    assert connection.committed[6] == 'pending'
    assert (tmp_path / str(caught.value.dataset.storage_key)).read_bytes() == b'a\n1\n'
    assert 'private detail' not in str(caught.value)


@pytest.mark.parametrize('phase', ['update', 'commit'])
def test_ready_interruption_propagates_without_sensitive_context(tmp_path, phase, monkeypatch):
    connection = Connection()
    store = make_store(connection)
    original_commit = connection.commit
    calls = 0

    def commit():
        nonlocal calls
        calls += 1
        original_commit()
        if phase == 'commit' and calls == 2:
            raise KeyboardInterrupt('secret')

    if phase == 'update':
        def interrupt(dataset):
            raise KeyboardInterrupt('secret')
        monkeypatch.setattr(store, 'mark_ready', interrupt)
    with pytest.raises(KeyboardInterrupt) as caught:
        service.publish_dataset(store, commit, tmp_path, 'sample.csv', BytesIO(b'a\n'))
    assert caught.value.args == ()
    assert caught.value.__context__ is None
    assert (tmp_path / str(connection.committed[2])).exists()


def test_invalid_csv_leaves_committed_identity_and_reports_file_outcome(tmp_path):
    connection = Connection()
    with pytest.raises(Exception) as caught:
        service.publish_dataset(make_store(connection), connection.commit, tmp_path,
                                'sample.csv', BytesIO(b'"unterminated'))
    error = caught.value
    assert type(error).__name__ == 'DatasetPublicationError'
    assert error.phase == 'publication_failed'
    assert error.dataset.storage_key == connection.committed[2]
    assert error.code == 'INVALID_UPLOAD'
    assert error.publication == 'not_published'
    assert error.cleanup == 'confirmed'
    assert not list(tmp_path.iterdir())


def test_link_response_lost_preserves_file_and_reports_indeterminate(tmp_path, monkeypatch):
    import os

    connection = Connection()
    real_link = os.link

    def link_then_fail(*args, **kwargs):
        real_link(*args, **kwargs)
        raise OSError('secret')

    monkeypatch.setattr(os, 'link', link_then_fail)
    with pytest.raises(service.DatasetPublicationError) as caught:
        service.publish_dataset(make_store(connection), connection.commit, tmp_path,
                                'sample.csv', BytesIO(b'a\n1\n'))
    error = caught.value
    assert error.publication == 'indeterminate'
    assert error.dataset.storage_key == connection.committed[2]
    assert (tmp_path / str(error.dataset.storage_key)).read_bytes() == b'a\n1\n'
    assert list(tmp_path.iterdir()) == [tmp_path / str(error.dataset.storage_key)]


def test_interruption_after_link_preserves_file_and_committed_identity(tmp_path, monkeypatch):
    import os

    connection = Connection()
    real_link = os.link

    def link_then_interrupt(*args, **kwargs):
        real_link(*args, **kwargs)
        raise KeyboardInterrupt('secret')

    monkeypatch.setattr(os, 'link', link_then_interrupt)
    with pytest.raises(KeyboardInterrupt) as caught:
        service.publish_dataset(make_store(connection), connection.commit, tmp_path,
                                'sample.csv', BytesIO(b'a\n'))
    assert caught.value.args == ()
    assert (tmp_path / str(connection.committed[2])).read_bytes() == b'a\n'


@pytest.mark.live_postgres
def test_live_final_commit_lost_reply_leaves_durable_ready(request, tmp_path):
    connection, _ = request.getfixturevalue('migrated_connection')
    commits = 0

    def lost_reply():
        nonlocal commits
        commits += 1
        connection.commit()
        if commits == 2:
            raise OSError('secret')

    with pytest.raises(service.DatasetPublicationError) as caught:
        service.publish_dataset(PostgresDatasetStore(connection), lost_reply, tmp_path,
                                'sample.csv', BytesIO(b'a\n'))
    assert caught.value.phase == 'ready_commit_unknown'
    connection.rollback()
    record = PostgresDatasetStore(connection).get(caught.value.dataset.id)
    assert record.publication_state == 'ready'
    assert (tmp_path / str(record.storage_key)).exists()


@pytest.mark.live_postgres
def test_live_interruption_after_file_before_update_leaves_pending(request, tmp_path, monkeypatch):
    connection, _ = request.getfixturevalue('migrated_connection')
    store = PostgresDatasetStore(connection)

    def interrupt(dataset):
        raise KeyboardInterrupt()

    monkeypatch.setattr(store, 'mark_ready', interrupt)
    with pytest.raises(KeyboardInterrupt):
        service.publish_dataset(store, connection.commit, tmp_path, 'sample.csv', BytesIO(b'a\n'))
    connection.rollback()
    schema = connection.execute(sa.text('SELECT current_schema()')).scalar_one()
    with connection.engine.connect() as restarted:
        restarted.exec_driver_sql(f'SET search_path TO "{schema}"')
        records = PostgresDatasetStore(restarted).list_incomplete()
        assert len(records) == 1 and records[0].publication_state == 'pending'
        assert (tmp_path / str(records[0].storage_key)).exists()


@pytest.mark.live_postgres
def test_live_success_persists_identity_and_csv(request, tmp_path):
    connection, _ = request.getfixturevalue('migrated_connection')
    result = service.publish_dataset_on_connection(connection, tmp_path, 'sample.csv', BytesIO(b'a\n1\n'))
    connection.rollback()  # The coordinator committed its own transaction.
    assert PostgresDatasetStore(connection).get(result.dataset.id) == result.dataset
    assert (tmp_path / str(result.dataset.storage_key)).read_bytes() == b'a\n1\n'


@pytest.mark.live_postgres
def test_live_invalid_csv_preserves_metadata_but_not_file(request, tmp_path):
    connection, _ = request.getfixturevalue('migrated_connection')
    with pytest.raises(service.DatasetPublicationError) as caught:
        service.publish_dataset_on_connection(connection, tmp_path, 'sample.csv', BytesIO(b'"bad'))
    connection.rollback()
    error = caught.value
    assert error.publication == 'not_published'
    assert PostgresDatasetStore(connection).get(error.dataset.id) == error.dataset
    assert not list(tmp_path.iterdir())
