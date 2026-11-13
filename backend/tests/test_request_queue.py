"""Request queue tests use only explicitly opted-in disposable PostgreSQL."""
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command

from test_postgres_live import migrated_connection as migrated_connection  # noqa: F401


@pytest.fixture
def queue_db(request):
    conn, config = request.getfixturevalue('migrated_connection')
    yield conn
    conn.rollback()
    command.downgrade(config, '0002_publication_state')
    conn.commit()


def ready(conn):
    dataset_id = uuid4()
    conn.execute(sa.text("INSERT INTO datasets (id, display_name, storage_key, publication_state) VALUES (:id, 'test.csv', :key, 'ready')"), {'id': dataset_id, 'key': uuid4()})
    conn.commit()
    return dataset_id


@pytest.mark.parametrize('question', ['', '  \t', '\ud800', 'a' * 4097, 'a\x00b'])
def test_invalid_questions_never_access_database(question):
    from app.request_queue import InvalidRequest, RequestQueue
    with pytest.raises(InvalidRequest):
        RequestQueue(None).create(uuid4(), uuid4(), question)


def test_rejects_invalid_question_before_database_access():
    from app.request_queue import InvalidRequest, RequestQueue
    with pytest.raises(InvalidRequest):
        RequestQueue(None).create(uuid4(), uuid4(), 'a\x00b')


@pytest.mark.live_postgres
def test_create_persists_idempotent_request(queue_db):
    from app.request_queue import RequestQueue
    dataset = ready(queue_db)
    client_id = uuid4()
    first, created = RequestQueue(queue_db).create(client_id, dataset, 'question?')
    assert created and first.status == 'queued'
    assert 'question?' not in repr(first)
    queue_db.commit()
    second, created = RequestQueue(queue_db).create(client_id, dataset, 'question?')
    assert not created and second.id == first.id


@pytest.mark.live_postgres
def test_claim_fifo_fencing_and_recovery(queue_db):
    from app.request_queue import RequestQueue
    q = RequestQueue(queue_db)
    dataset = ready(queue_db)
    first, _ = q.create(uuid4(), dataset, 'one')
    queue_db.commit()
    second, _ = q.create(uuid4(), dataset, 'two')
    queue_db.commit()
    token = uuid4()
    assert q.get(first.id) == first
    assert q.get(uuid4()) is None
    assert [r.id for r in q.history(10)] == [second.id, first.id]
    claimed = q.claim_next(token)
    assert claimed.id == first.id and claimed.status == 'running'
    queue_db.commit()
    assert q.claim_next(uuid4()) is None
    assert not q.complete_fake(first.id, uuid4())
    assert q.complete_fake(first.id, token)
    queue_db.commit()
    assert q.claim_next(uuid4()).id == second.id
    queue_db.commit()
    assert q.mark_unknown_running() == 1
    assert q.get(second.id).status == 'unknown'
    assert not q.complete_fake(second.id, token)


@pytest.mark.live_postgres
def test_readiness_idempotency_and_rollback(queue_db):
    from app.dataset_store import DatasetNotFound
    from app.ready_dataset import DatasetUnavailable
    from app.request_queue import IdempotencyConflict, RequestQueue

    q = RequestQueue(queue_db)
    dataset = ready(queue_db)
    client = uuid4()
    record, _ = q.create(client, dataset, ' exact ')
    queue_db.rollback()
    assert q.get(record.id) is None
    record, _ = q.create(client, dataset, ' exact ')
    queue_db.commit()
    queue_db.execute(sa.text("UPDATE datasets SET publication_state='pending' WHERE id=:id"), {'id': dataset})
    queue_db.commit()
    assert q.create(client, dataset, ' exact ') == (record, False)
    with pytest.raises(IdempotencyConflict):
        q.create(client, dataset, 'exact')
    with pytest.raises(DatasetUnavailable):
        q.create(uuid4(), dataset, 'other')
    with pytest.raises(DatasetNotFound):
        q.create(uuid4(), uuid4(), 'other')
    queue_db.execute(sa.text("UPDATE datasets SET lifecycle='deleted', deleted_at=now() WHERE id=:id"), {'id': dataset})
    with pytest.raises(DatasetNotFound):
        q.create(uuid4(), dataset, 'other')
    assert q.create(client, dataset, ' exact ') == (record, False)


@pytest.mark.live_postgres
def test_database_enforces_single_running_and_dataset_restrict(queue_db):
    from sqlalchemy.exc import IntegrityError
    from app.request_queue import RequestQueue

    q = RequestQueue(queue_db)
    dataset = ready(queue_db)
    first, _ = q.create(uuid4(), dataset, 'one')
    second, _ = q.create(uuid4(), dataset, 'two')
    q.claim_next(uuid4())
    with pytest.raises(IntegrityError), queue_db.begin_nested():
        queue_db.execute(sa.text("UPDATE request_intents SET status='running', claim_token=:token WHERE id=:id"),
                         {'token': uuid4(), 'id': second.id})
    with pytest.raises(IntegrityError), queue_db.begin_nested():
        queue_db.execute(sa.text('DELETE FROM datasets WHERE id=:id'), {'id': dataset})
    assert q.get(first.id).status == 'running'


@pytest.mark.live_postgres
def test_concurrent_idempotent_create_and_claim(queue_db):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.request_queue import RequestQueue

    dataset = ready(queue_db)
    schema = queue_db.execute(sa.text('SELECT current_schema()')).scalar_one()
    queue_db.commit()
    client = uuid4()
    barrier = Barrier(2)

    def create(_):
        with queue_db.engine.connect() as other:
            other.exec_driver_sql(f'SET search_path TO "{schema}"')
            other.commit()
            barrier.wait(timeout=5)
            result = RequestQueue(other).create(client, dataset, 'same')
            other.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(create, range(2)))
    assert sorted(created for _, created in results) == [False, True]
    assert results[0][0].id == results[1][0].id
    RequestQueue(queue_db).create(uuid4(), dataset, 'second')
    queue_db.commit()
    barrier = Barrier(2)

    def claim(_):
        with queue_db.engine.connect() as other:
            other.exec_driver_sql(f'SET search_path TO "{schema}"')
            other.commit()
            barrier.wait(timeout=5)
            result = RequestQueue(other).claim_next(uuid4())
            other.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, range(2)))
    assert sum(row is not None for row in results) == 1
