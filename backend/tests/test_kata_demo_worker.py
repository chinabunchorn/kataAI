"""Real worker orchestration tests; model code remains inert throughout."""
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import kata_demo_worker as worker
from app.executor_contract import CleanupState, ExecutorObservation, ExecutorResult, ExecutorStatus, RunState
from app.model_adapter import LocalModelAdapter, ModelTextOnlyOutcome


class Connection:
    def commit(self): pass
    def rollback(self): pass


class Queue:
    def __init__(self, claim, events):
        self.claim, self.events = claim, events
        self.finished = None
    def get(self, identifier): return self.claim
    def bind_run(self, identifier, token, run_id, code):
        self.events.append('bind')
        self.run_id = run_id
        self.code = code
        return True
    def finish_real(self, identifier, token, status, **values):
        self.events.append('persist')
        self.finished = (status, values)
        return status


class Executor:
    def __init__(self, events, raw=b'{"answer":770}', state=RunState.COMPLETED):
        self.events, self.raw, self.state = events, raw, state
    def submit(self, request):
        self.events.append('submit')
        self.request = request
        assert request.timeout_seconds == 30
        return ExecutorResult(request.request_id, request.run_id, ExecutorStatus.ACCEPTED)
    def status(self, request_id, run_id):
        return ExecutorObservation(request_id, run_id, self.state, CleanupState.PENDING)
    def read_result(self, *args): return self.raw
    def outcome(self, *args): return {'code': 'SCRIPT_FAILED'}
    def cleanup(self, *args): self.events.append('cleanup')
    def cancel(self, *args): self.events.append('cancel')


def setup(monkeypatch, tmp_path):
    tmp_path.chmod(0o700)
    key = uuid4()
    path = tmp_path / str(key)
    path.write_bytes(b'\xef\xbb\xbfquantity,unit_price_thb\n2,100\n')
    path.chmod(0o600)
    dataset = SimpleNamespace(lifecycle='active', publication_state='ready', storage_key=key)
    monkeypatch.setattr(worker, '_dataset', lambda *args: dataset)
    monkeypatch.setattr(worker, '_require_ownership', lambda *args: None)
    claim = SimpleNamespace(id=uuid4(), dataset_id=uuid4(), claim_token=uuid4(), question='revenue?', status='running')
    events = []
    queue, executor = Queue(claim, events), Executor(events)
    return claim, queue, executor, path


def model_response(text=None):
    message = ({'content': text} if text else {'tool_calls': [{'type': 'function', 'function': {
        'name': 'run_python', 'arguments': json.dumps({'code': 'raise RuntimeError("never locally executed")'})}}]})
    return {'choices': [{'finish_reason': 'stop' if text else 'tool_calls', 'message': message}]}


def test_success_persists_actual_result_before_cleanup(monkeypatch, tmp_path):
    claim, queue, executor, _ = setup(monkeypatch, tmp_path)
    class Model:
        def generate(self, question, columns):
            assert columns == ('quantity', 'unit_price_thb')
            return [{'name': 'run_python', 'arguments': {'code': 'raise RuntimeError("inert")'}}]
        def summarize(self, question, result):
            assert result == {'answer': 770}
            return {'invented': 9}, 'Revenue is 770 THB.', None
    assert worker.process_claim(Connection(), tmp_path, claim, model=Model(), executor=executor, queue=queue) == 'completed'
    assert queue.finished == ('completed', {'result': {'answer': 770}, 'answer': 'Revenue is 770 THB.', 'error_code': None})
    assert queue.events == ['bind', 'submit', 'persist', 'cleanup']


def test_summary_failure_keeps_result(monkeypatch, tmp_path):
    claim, queue, executor, _ = setup(monkeypatch, tmp_path)
    model = LocalModelAdapter('http://127.0.0.1:8080/v1/chat/completions', transport=lambda p: model_response())
    worker.process_claim(Connection(), tmp_path, claim, model=model, executor=executor, queue=queue)
    assert queue.finished == ('completed', {'result': {'answer': 770}, 'answer': None, 'error_code': 'SUMMARY_UNAVAILABLE'})


def test_text_only_is_bounded_and_never_submitted(monkeypatch, tmp_path):
    claim, queue, executor, _ = setup(monkeypatch, tmp_path)
    model = LocalModelAdapter('http://127.0.0.1:8080/v1/chat/completions', transport=lambda p: model_response('Which total?'))
    worker.process_claim(Connection(), tmp_path, claim, model=model, executor=executor, queue=queue)
    assert queue.finished == ('needs_clarification', {'result': None, 'answer': 'Which total?', 'error_code': None})
    assert queue.events == ['persist']
    with pytest.raises(ModelTextOnlyOutcome) as caught:
        model.generate('q', ['a'])
    assert caught.value.text == 'Which total?' and str(caught.value) == 'MODEL_ADAPTER_FAILED'


@pytest.mark.parametrize('raw', [b'null', b'{"answer":NaN}', b'{"a":1,"a":2}', b'[]' + b' ' * 2048])
def test_invalid_runner_result_is_visible_uncertainty(monkeypatch, tmp_path, raw):
    claim, queue, executor, _ = setup(monkeypatch, tmp_path)
    executor.raw = raw
    model = LocalModelAdapter('http://127.0.0.1:8080/v1/chat/completions', transport=lambda p: model_response())
    worker.process_claim(Connection(), tmp_path, claim, model=model, executor=executor, queue=queue)
    assert queue.finished[0] == 'unknown'
    assert queue.finished[1]['result'] is None
    assert queue.events == ['bind', 'submit', 'persist', 'cancel', 'cleanup']


def test_timeout_persists_before_cancel(monkeypatch, tmp_path):
    claim, queue, executor, _ = setup(monkeypatch, tmp_path)
    executor.state = RunState.RUNNING
    model = LocalModelAdapter('http://127.0.0.1:8080/v1/chat/completions', transport=lambda p: model_response())
    worker.process_claim(Connection(), tmp_path, claim, model=model, executor=executor, queue=queue, wait_seconds=0)
    assert queue.finished[1]['error_code'] == 'EXECUTION_TIMEOUT'
    assert queue.events == ['bind', 'submit', 'persist', 'cancel', 'cleanup']


def test_model_failure_is_persisted_without_dispatch(monkeypatch, tmp_path):
    claim, queue, executor, _ = setup(monkeypatch, tmp_path)
    model = LocalModelAdapter('http://127.0.0.1:8080/v1/chat/completions', transport=lambda p: {})
    worker.process_claim(Connection(), tmp_path, claim, model=model, executor=executor, queue=queue)
    assert queue.finished[0] == 'failed' and queue.finished[1]['error_code'] == 'MODEL_GENERATION_FAILED'
    assert queue.events == ['persist']


def test_dataset_bytes_and_reject_oversize_symlink_permissions(monkeypatch, tmp_path):
    claim, queue, executor, path = setup(monkeypatch, tmp_path)
    request = SimpleNamespace(dataset_id=claim.dataset_id)
    raw = path.read_bytes()
    assert worker.resolve_dataset(Connection(), tmp_path, request, len(raw)) == raw
    with pytest.raises(ValueError):
        worker.resolve_dataset(Connection(), tmp_path, request, len(raw)-1)
    path.chmod(0o644)
    with pytest.raises(ValueError):
        worker.resolve_dataset(Connection(), tmp_path, request, 524288)
    path.unlink()
    path.symlink_to(tmp_path / 'missing')
    with pytest.raises(OSError):
        worker.resolve_dataset(Connection(), tmp_path, request, 524288)


def test_image_identity_checks_provider_image_id():
    assert worker.verify_image(worker.RUNNER_IMAGE, {'imageID': 'docker-pullable://' + worker.RUNNER_IMAGE})
    assert worker.verify_image(worker.RUNNER_IMAGE, {'imageID': 'containerd://' + worker.RUNNER_CONFIG})
    assert not worker.verify_image(worker.RUNNER_IMAGE, {'imageID': 'sha256:' + '0'*64})
    assert not worker.verify_image('runner:latest', {'imageID': worker.RUNNER_CONFIG})


def test_disabled_by_default(capsys, monkeypatch):
    monkeypatch.delenv('KATAAI_PRIVATE_EXPERIMENTAL_DEMO', raising=False)
    assert worker.main(['--once', '--kubeconfig', '/unused', '--context', 'unused', '--journal', '/unused']) == 1
    assert 'EXECUTION_NOT_APPROVED' in capsys.readouterr().err


@pytest.mark.parametrize('ack_status,expected', [(ExecutorStatus.REJECTED, 'failed'),
                                               (ExecutorStatus.UNKNOWN, 'unknown')])
def test_submit_uncertainty_never_completes_with_a_result(monkeypatch, tmp_path, ack_status, expected):
    claim, queue, executor, _ = setup(monkeypatch, tmp_path)
    def submit(request):
        queue.events.append('submit')
        return ExecutorResult(request.request_id, request.run_id, ack_status)
    executor.submit = submit
    model = LocalModelAdapter('http://127.0.0.1:8080/v1/chat/completions', transport=lambda p: model_response())
    worker.process_claim(Connection(), tmp_path, claim, model=model, executor=executor, queue=queue)
    assert queue.finished[0] == expected and queue.finished[1]['result'] is None
    assert queue.events == ['bind', 'submit', 'persist', 'cancel', 'cleanup']


def test_provider_failure_persists_actual_error(monkeypatch, tmp_path):
    claim, queue, executor, _ = setup(monkeypatch, tmp_path)
    executor.state = RunState.FAILED
    model = LocalModelAdapter('http://127.0.0.1:8080/v1/chat/completions', transport=lambda p: model_response())
    worker.process_claim(Connection(), tmp_path, claim, model=model, executor=executor, queue=queue)
    assert queue.finished == ('failed', {'result': None, 'answer': None, 'error_code': 'SCRIPT_FAILED'})
    assert queue.events == ['bind', 'submit', 'persist', 'cleanup']


def test_cleanup_failure_does_not_erase_committed_result(monkeypatch, tmp_path, capsys):
    claim, queue, executor, _ = setup(monkeypatch, tmp_path)
    def cleanup(*args): raise OSError('provider unavailable')
    executor.cleanup = cleanup
    model = LocalModelAdapter('http://127.0.0.1:8080/v1/chat/completions', transport=lambda p: model_response())
    worker.process_claim(Connection(), tmp_path, claim, model=model, executor=executor, queue=queue)
    assert queue.finished[0] == 'completed' and queue.finished[1]['result'] == {'answer': 770}
    assert 'CLEANUP_PENDING' in capsys.readouterr().err
