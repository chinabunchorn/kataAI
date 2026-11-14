"""Focused, explicitly opted-in concurrency test against disposable PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock

import pytest

from test_model_admission_live import admission as admission, count_requests, payload, upload
from test_postgres_live import migrated_connection as migrated_connection


@pytest.mark.live_postgres
def test_concurrent_same_key_performs_preflight_once(admission, monkeypatch):  # noqa: F811
    from app import dataset_columns

    client, conn, _ = admission
    dataset_id = upload(client, ['item', 'quantity'])
    question = payload(dataset_id, 'How many?')
    original = dataset_columns.read_dataset_columns
    count = []
    lock = Lock()

    def recording_read(*args, **kwargs):
        with lock:
            count.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(dataset_columns, 'read_dataset_columns', recording_read)
    barrier = Barrier(4)

    def submit(_):
        barrier.wait(timeout=10)
        return client.post('/v1/requests', json=question)

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(submit, range(4)))
    assert sorted(r.status_code for r in responses) == [200, 200, 200, 201]
    assert len({r.json()['id'] for r in responses}) == 1
    assert len(count) == 1
    assert count_requests(conn) == 1
