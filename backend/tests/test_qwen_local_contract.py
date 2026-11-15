"""Offline integration: synthetic queue, local transport and inert model output."""
from contextlib import contextmanager
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from test_fake_worker import Connection, Database, Queue


def test_configured_9b_queue_uses_provisional_contract_and_fake_preset(monkeypatch, tmp_path, capsys):
    from app import phase6_processor, qwen_demo_worker as worker
    from app.model_adapter import LocalModelAdapter

    dataset_id, storage_key, request_id = uuid4(), uuid4(), uuid4()
    question = 'What is total revenue?'
    model_name = 'Qwen3.5-9B-Q4_K_M'
    db = Database([{'id': request_id, 'status': 'queued'}])
    conn = Connection(db)
    tmp_path.chmod(0o700)
    (tmp_path / str(storage_key)).write_text('quantity,unit_price_thb\nPRIVATE_ROW_SENTINEL,99\n')
    marker = tmp_path / 'must-not-exist'
    code = f"open({str(marker)!r}, 'w').write('unsafe')"
    requests = []

    class SyntheticQueue(Queue):
        def claim_next(self, token):
            claim = super().claim_next(token)
            return SimpleNamespace(id=claim.id, dataset_id=dataset_id, question=question) if claim else None

        def complete_fake(self, request_id, token, result):
            completed = super().complete_fake(request_id, token)
            if completed:
                self.db.rows[0]['result'] = result
            return completed

    class SyntheticStore:
        def __init__(self, connection):
            assert connection is conn

        def get(self, value):
            assert value == dataset_id
            return SimpleNamespace(lifecycle='active', publication_state='ready', storage_key=storage_key)

    @contextmanager
    def connection():
        yield conn

    def transport(payload):
        assert db.owner is conn
        requests.append(payload)
        return {'choices': [{'finish_reason': 'tool_calls', 'message': {'tool_calls': [
            {'type': 'function', 'function': {'name': 'run_python', 'arguments': json.dumps({'code': code})}}
        ]}}]}

    monkeypatch.setattr(worker, 'load_dataset_runtime', lambda: SimpleNamespace(root=tmp_path, connection=connection))
    monkeypatch.setattr(worker, 'RequestQueue', SyntheticQueue)
    monkeypatch.setattr(worker, 'LocalModelAdapter', lambda endpoint, model: LocalModelAdapter(endpoint, model=model, transport=transport))
    monkeypatch.setattr(phase6_processor, 'PostgresDatasetStore', SyntheticStore)
    assert worker.main(['--once', '--model-endpoint', 'http://127.0.0.1:8080/v1/chat/completions', '--model', model_name]) == 0

    assert len(requests) == 1  # No model summary call for a fake preset.
    payload = requests[0]
    assert payload['model'] == model_name
    assert json.loads(payload['messages'][1]['content']) == {'question': question, 'columns': ['quantity', 'unit_price_thb']}
    assert 'PRIVATE_ROW_SENTINEL' not in json.dumps(payload)
    prompt = payload['messages'][0]['content'].lower()
    assert '/inputs/data.csv' in prompt and '/tmp/result.json' in prompt
    assert 'dataframe' not in prompt and 'pandas' not in prompt
    assert 'result' in prompt and 'answer' in prompt and 'json' in prompt
    assert payload['temperature'] == 0.6 and payload['top_p'] == 0.95
    assert payload['top_k'] == 20 and payload['min_p'] == 0.0
    assert payload['presence_penalty'] == 0.0 and payload['repeat_penalty'] == 1.0
    assert payload['tool_choice'] == 'auto'
    result = db.rows[0]['result']
    assert db.rows[0]['status'] == 'fake_completed' and db.owner is None
    assert result == {'fake': True, 'code': code, 'result': {'example': [1, 2]},
                      'summary': None, 'warning': 'FAKE_PRESET_NOT_AN_ANSWER', 'metrics': None}
    assert not marker.exists()
    assert 'not a real answer' in capsys.readouterr().out


@pytest.mark.parametrize('read_time, succeeds', [(100.999, True), (101.0, False), (101.001, False)])
def test_total_http_deadline_boundary_is_not_reset_between_phases(monkeypatch, read_time, succeeds):
    from app import model_adapter as module

    body = json.dumps({'choices': [{'finish_reason': 'tool_calls', 'message': {'tool_calls': [
        {'type': 'function', 'function': {'name': 'run_python', 'arguments': '{"code":"pass"}'}}
    ]}}]}).encode()
    response = b'HTTP/1.1 200 OK\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body
    clock = iter([100.0, 100.1, 100.5, read_time])
    reads = []

    class Socket:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def setblocking(self, value): assert value is False
        def connect_ex(self, address): return 0
        def getsockopt(self, *args): return 0
        def send(self, view): return len(view)
        def recv(self, count):
            reads.append(count)
            return response

    monkeypatch.setattr(module, 'time', SimpleNamespace(monotonic=lambda: next(clock)))
    monkeypatch.setattr(module.socket, 'socket', lambda *args: Socket())
    monkeypatch.setattr(module.select, 'select', lambda r, w, x, timeout: (r, w, []))
    adapter = module.LocalModelAdapter('http://127.0.0.1:8080/v1/chat/completions', timeout=1)
    if succeeds:
        assert adapter.generate('q', ['column'])[0]['arguments']['code'] == 'pass'
        assert len(reads) == 1
    else:
        with pytest.raises(module.ModelAdapterError, match='^MODEL_ADAPTER_FAILED$'):
            adapter.generate('q', ['column'])
        assert reads == []


@pytest.mark.parametrize('timeout, valid', [(0, False), (0.001, True), (120, True), (120.001, False)])
def test_timeout_configuration_boundaries(timeout, valid):
    from app.model_adapter import LocalModelAdapter, ModelAdapterError
    if valid:
        LocalModelAdapter('http://127.0.0.1:8080/v1/chat/completions', timeout=timeout)
    else:
        with pytest.raises(ModelAdapterError):
            LocalModelAdapter('http://127.0.0.1:8080/v1/chat/completions', timeout=timeout)
