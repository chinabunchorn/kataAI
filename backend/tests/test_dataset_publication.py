from datetime import datetime, timezone
from io import BytesIO
from uuid import UUID

import pytest

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
        self.pending = (params['id'], params['name'], params['key'],
                        datetime.now(timezone.utc), 'active', None)
        return Result(self.pending)

    def commit(self):
        self.committed = self.pending


def make_store(connection):
    ids = iter([UUID(int=1), UUID(int=2)])
    return PostgresDatasetStore(connection, id_factory=lambda: next(ids))


def test_commits_identity_before_publishing_real_csv(tmp_path):
    connection = Connection()
    result = service.publish_dataset(make_store(connection), connection.commit, tmp_path,
                                     'sample.csv', BytesIO(b'a\n1\n'))
    assert connection.committed[:3] == (result.dataset.id, 'sample.csv', result.dataset.storage_key)
    assert (tmp_path / str(result.dataset.storage_key)).read_bytes() == b'a\n1\n'
    assert result.csv.row_count == 1


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
