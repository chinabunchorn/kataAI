import pytest


def test_cli_requires_explicit_opt_in_and_endpoint(capsys):
    from app.qwen_demo_worker import main

    for args in ([], ['--once'], ['--model-endpoint', 'http://127.0.0.1:8000/v1/chat/completions']):
        with pytest.raises(SystemExit) as exc:
            main(args)
        assert exc.value.code == 2


def test_generation_only_commits_before_model_and_labels_preset(monkeypatch):
    from app import qwen_demo_worker
    from app.fake_flow import run_fake_flow

    events = []
    class Connection:
        def commit(self):
            events.append('commit')
    class Model:
        def generate(self, question, columns):
            events.append((question, columns))
            return [{'name': 'run_python', 'arguments': {'code': 'raise RuntimeError("must not execute")'}}]
        def summarize(self, *args):
            pytest.fail('must not send preset to model')
    def process(conn, root, claim, *, model):
        conn.commit()
        return run_fake_flow(model, {'example': [1, 2]}, 'question', ('col',))
    monkeypatch.setattr(qwen_demo_worker, 'process_claim', process)
    result = qwen_demo_worker._process(Connection(), None, None, Model())
    assert events == ['commit', ('question', ('col',))]
    assert result['fake'] is True and result['metrics'] is None
    assert result['summary'] is None and result['warning'] == 'FAKE_PRESET_NOT_AN_ANSWER'
    assert result['result'] == {'example': [1, 2]}


@pytest.mark.parametrize('endpoint', ['http://localhost:8000/v1/chat/completions',
                                      'http://8.8.8.8:80/v1/chat/completions',
                                      'http://secret@127.0.0.1:8000/v1/chat/completions'])
def test_remote_or_ambiguous_endpoint_fails_before_db_access(endpoint, monkeypatch, capsys):
    from app import qwen_demo_worker as worker
    monkeypatch.setattr(worker, 'load_dataset_runtime', lambda: pytest.fail('database accessed'))
    assert worker.main(['--once', '--model-endpoint', endpoint]) == 1
    out = capsys.readouterr()
    assert endpoint not in out.err and 'secret' not in out.err
    assert 'uncertain' in out.err


def test_main_processes_one_claim_using_real_fake_flow(monkeypatch, tmp_path, capsys):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from uuid import uuid4
    from test_fake_worker import Connection, Database, Queue
    from app import qwen_demo_worker as worker, phase6_processor
    from app.model_adapter import LocalModelAdapter

    request_id, dataset_id = uuid4(), uuid4()
    db = Database([{'id': request_id, 'status': 'queued'}])
    conn = Connection(db)
    seen = []
    class QueueWithResult(Queue):
        def claim_next(self, token):
            claim = super().claim_next(token)
            return SimpleNamespace(id=claim.id, dataset_id=dataset_id, question='question') if claim else None
        def complete_fake(self, request_id, token, result):
            self.db.rows[0]['result'] = result
            return super().complete_fake(request_id, token)
    class Store:
        def __init__(self, connection):
            assert connection is conn
        def get(self, value):
            assert value == dataset_id
            return SimpleNamespace(lifecycle='active', publication_state='ready', storage_key='key')
    @contextmanager
    def connection():
        yield conn
    def transport(payload):
        assert conn.commits == 4 and db.owner is conn
        seen.append(payload)
        return {'choices': [{'finish_reason': 'tool_calls', 'message': {'tool_calls': [
            {'type': 'function', 'function': {'name': 'run_python', 'arguments':
             '{"code":"raise RuntimeError(\\"inert\\")"}'}}]}}]}
    monkeypatch.setattr(worker, 'load_dataset_runtime', lambda: SimpleNamespace(root=tmp_path, connection=connection))
    monkeypatch.setattr(worker, 'RequestQueue', QueueWithResult)
    monkeypatch.setattr(worker, 'LocalModelAdapter', lambda endpoint, model: LocalModelAdapter(endpoint, model=model, transport=transport))
    monkeypatch.setattr(phase6_processor, 'PostgresDatasetStore', Store)
    monkeypatch.setattr(phase6_processor, 'read_dataset_columns', lambda root, key: ('col',))
    assert worker.main(['--once', '--model-endpoint', 'http://127.0.0.1:8000/v1/chat/completions']) == 0
    result = db.rows[0]['result']
    assert db.rows[0]['status'] == 'fake_completed' and db.owner is None
    assert len(seen) == 1 and 'question' in seen[0]['messages'][1]['content']
    assert result['fake'] is True and result['metrics'] is None and result['summary'] is None
    assert result['warning'] == 'FAKE_PRESET_NOT_AN_ANSWER'
    assert result['result'] == {'example': [1, 2]}
    assert 'not a real answer' in capsys.readouterr().out


def test_model_failure_is_sanitized_and_not_retried(monkeypatch, capsys):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from app import qwen_demo_worker as worker
    calls = []
    @contextmanager
    def connection():
        yield object()
    monkeypatch.setattr(worker, 'load_dataset_runtime', lambda: SimpleNamespace(root='root', connection=connection))
    def failed(connection, queue, *, processor):
        calls.append('once')
        raise RuntimeError('secret generated code or database password')
    monkeypatch.setattr(worker, 'run_once', failed)
    assert worker.main(['--once', '--model-endpoint', 'http://127.0.0.1:8000/v1/chat/completions']) == 1
    output = capsys.readouterr()
    assert calls == ['once'] and 'secret' not in output.err and 'no retry' in output.err
