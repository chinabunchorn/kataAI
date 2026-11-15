"""Lifecycle tests: offline validation and explicitly disposable PostgreSQL."""
from uuid import uuid4

import pytest


from test_postgres_live import migrated_connection as migrated_connection  # noqa: F401
from test_request_queue import ready


def test_history_rejects_unbounded_page_before_database_access():
    from app.request_queue import InvalidRequest, RequestQueue
    with pytest.raises(InvalidRequest):
        RequestQueue(None).history(101)


@pytest.mark.live_postgres
def test_queued_cancel_is_terminal_and_not_claimable(request):
    from app.request_queue import RequestQueue
    conn, _ = request.getfixturevalue('migrated_connection')
    q = RequestQueue(conn)
    dataset = ready(conn)
    record, _ = q.create(uuid4(), dataset, 'one')
    assert q.cancel(record.id).status == 'cancelled'
    assert q.cancel(record.id).status == 'cancelled'
    assert q.claim_next(uuid4()) is None
    conn.commit()
