"""Logical deletion tests: synthetic roots and explicitly disposable PostgreSQL only."""
from contextlib import contextmanager


import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from test_request_queue import queue_db as queue_db, ready  # noqa: F401
from test_postgres_live import migrated_connection as migrated_connection  # noqa: F401


class Runtime:
    def __init__(self, conn, root):
        self.engine = conn.engine
        self.root = root
        self.schema = conn.execute(sa.text('SELECT current_schema()')).scalar_one()
        conn.commit()

    @contextmanager
    def connection(self):
        with self.engine.connect() as conn:
            conn.exec_driver_sql(f'SET search_path TO "{self.schema}"')
            conn.commit()
            yield conn


def client_for(runtime):
    from app.dataset_lifecycle_api import create_dataset_lifecycle_router
    app = FastAPI()
    app.include_router(create_dataset_lifecycle_router(lambda: runtime))
    return TestClient(app)


@pytest.mark.live_postgres
def test_delete_is_idempotent_and_preserves_file(request, tmp_path):
    connection = request.getfixturevalue('queue_db')
    dataset = ready(connection)
    path = tmp_path / 'synthetic.csv'
    path.write_bytes(b'a,b\n1,2\n')
    client = client_for(Runtime(connection, tmp_path))
    for _ in range(2):
        response = client.delete(f'/v1/datasets/{dataset}')
        assert response.status_code == 200
        assert response.json() == {'dataset_id': str(dataset), 'state': 'deleted', 'file_cleanup': 'not_attempted'}
    assert path.read_bytes() == b'a,b\n1,2\n'
    row = connection.execute(sa.text('SELECT lifecycle, deleted_at FROM datasets WHERE id=:id'), {'id': dataset}).one()
    assert row.lifecycle == 'deleted' and row.deleted_at is not None
