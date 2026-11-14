"""Deterministic HTTP + disposable-Postgres Qwen-worker integration."""
from contextlib import contextmanager
import json
from threading import Thread
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.dataset_lookup_api import get_dataset_runtime
from app.main import app
from test_postgres_live import migrated_connection as migrated_connection  # noqa: F401


@pytest.mark.live_postgres
def test_queued_model_worker_sends_question_and_headers_not_rows(request, tmp_path, monkeypatch):
    from app import qwen_demo_worker
    from http.server import BaseHTTPRequestHandler, HTTPServer

    conn, _ = request.getfixturevalue('migrated_connection')
    schema = conn.execute(sa.text('SELECT current_schema()')).scalar_one()
    conn.commit()
    tmp_path.chmod(0o700)
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers['Content-Length']))
            requests.append(json.loads(body))
            response = {'choices': [{'finish_reason': 'tool_calls', 'message': {'tool_calls': [
                {'type': 'function', 'function': {'name': 'run_python',
                    'arguments': json.dumps({'code': 'raise RuntimeError("must remain inert")'})}}]}}]}
            data = json.dumps(response).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        def log_message(self, *args):
            pass

    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    @contextmanager
    def isolated_connection():
        with conn.engine.connect() as current:
            current.exec_driver_sql(f'SET search_path TO "{schema}"')
            current.commit()
            yield current

    class Runtime:
        root = tmp_path
        connection = staticmethod(isolated_connection)

    runtime = Runtime()
    app.dependency_overrides[get_dataset_runtime] = lambda: runtime
    monkeypatch.setattr(qwen_demo_worker, 'load_dataset_runtime', lambda: runtime)
    try:
        client = TestClient(app, base_url='http://127.0.0.1:8000')
        headers = {'origin': 'http://127.0.0.1:8000', 'x-kataai-request': '1'}
        csv = b'product,sales\nPRIVATE_ROW_SENTINEL,3\n'
        upload = client.post('/v1/datasets', files={'file': ('x.csv', csv, 'text/csv')}, headers=headers)
        assert upload.status_code == 201
        payload = {'schema_version': '1.0', 'client_request_id': str(uuid4()),
                   'dataset_id': upload.json()['dataset_id'], 'question': 'Total sales?'}
        created = client.post('/v1/requests', json=payload, headers=headers)
        assert created.status_code == 201
        endpoint = f'http://127.0.0.1:{server.server_port}/v1/chat/completions'
        assert qwen_demo_worker.main(['--once', '--model-endpoint', endpoint]) == 0
        assert len(requests) == 1
        wire = json.dumps(requests[0])
        assert 'Total sales?' in wire and 'product' in wire and 'sales' in wire
        assert 'PRIVATE_ROW_SENTINEL' not in wire
        detail = client.get('/v1/requests/' + created.json()['id']).json()
        result = detail['fake_result']
        assert detail['status'] == 'fake_completed' and result['fake'] is True
        assert result['result'] == {'example': [1, 2]}
        assert result['summary'] is None and result['warning'] == 'FAKE_PRESET_NOT_AN_ANSWER'
        assert result['metrics'] is None and 'must remain inert' in result['code']
    finally:
        app.dependency_overrides.pop(get_dataset_runtime, None)
        server.shutdown()
        server.server_close()
        thread.join(3)
