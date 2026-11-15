from datetime import datetime, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa

from app.request_api import public_record
from app.request_queue import InvalidRequest, RequestQueue, RequestRecord
from test_postgres_live import migrated_connection as migrated_connection  # noqa: F401


def test_serializes_real_result_and_code_without_fake_label():
    now = datetime.now(timezone.utc)
    record = RequestRecord(uuid4(), uuid4(), uuid4(), 'question', 'completed', None, now, now,
                           run_id=uuid4(), real_result={'answer': 770}, generated_code='inert', answer='770 THB')
    body = public_record(record, include_detail=True)
    assert body['status'] == 'completed' and body['fake'] is False
    assert body['result'] == {'answer': 770} and body['answer'] == '770 THB'
    assert body['code'] == 'inert' and body['run_id'] == str(record.run_id)
    assert body['error_code'] is None


@pytest.mark.parametrize('status,result', [('fake_completed', {}), ('completed', 7), ('failed', {})])
def test_rejects_invalid_real_result_without_database(status, result):
    with pytest.raises(InvalidRequest):
        RequestQueue(None).finish_real(uuid4(), uuid4(), status, result=result)


@pytest.mark.live_postgres
@pytest.mark.parametrize('status', ['completed', 'failed', 'needs_clarification', 'unknown'])
def test_real_outcome_persists_with_fenced_token(request, status):
    connection, _ = request.getfixturevalue('migrated_connection')
    dataset = uuid4()
    connection.execute(sa.text("INSERT INTO datasets (id,storage_key,display_name,publication_state) "
                               "VALUES (:id,:key,'test.csv','ready')"), {'id': dataset, 'key': uuid4()})
    queue = RequestQueue(connection)
    record, _ = queue.create(uuid4(), dataset, 'question')
    token = uuid4()
    queue.claim_next(token)
    run = uuid4()
    assert not queue.bind_run(record.id, uuid4(), run, 'pass')
    assert queue.bind_run(record.id, token, run, 'pass')
    connection.commit()
    result = {'answer': 770} if status == 'completed' else None
    assert not queue.finish_real(record.id, uuid4(), status, result=result)
    assert queue.finish_real(record.id, token, status, result=result, answer='bounded answer') == status
    connection.commit()
    persisted = queue.get(record.id)
    assert persisted.status == status and persisted.claim_token is None
    assert persisted.run_id == run and persisted.real_result == result
    assert persisted.generated_code == 'pass' and persisted.answer == 'bounded answer'
    assert persisted.fake_result is None
    assert public_record(persisted, include_detail=True)['fake'] is False


@pytest.mark.live_postgres
def test_real_worker_claims_and_persists_using_postgres(request, tmp_path):
    from types import SimpleNamespace
    from app.kata_demo_worker import run_once
    from app.executor_contract import ExecutorResult, ExecutorStatus, ExecutorObservation, RunState, CleanupState
    from app.local_csv_storage import publish_csv
    from io import BytesIO
    connection, _ = request.getfixturevalue('migrated_connection')
    dataset, key = uuid4(), uuid4()
    publish_csv(tmp_path, BytesIO(b'quantity\n2\n'), key)
    connection.execute(sa.text("INSERT INTO datasets (id,storage_key,display_name,publication_state) "
                               "VALUES (:id,:key,'test.csv','ready')"), {'id': dataset, 'key': key})
    queue = RequestQueue(connection)
    record, _ = queue.create(uuid4(), dataset, 'question')
    connection.commit()
    class Executor:
        def submit(self, request):
            bound = queue.get(record.id)
            assert bound.run_id == request.run_id and bound.generated_code == 'inert'
            return ExecutorResult(request.request_id, request.run_id, ExecutorStatus.ACCEPTED)
        def status(self, request_id, run_id):
            return ExecutorObservation(request_id, run_id, RunState.COMPLETED, CleanupState.PENDING)
        def read_result(self, *args): return b'{"answer":2}'
        def cleanup(self, *args):
            assert queue.get(record.id).status == 'completed'
    model = SimpleNamespace(generate=lambda *a: [{'name': 'run_python', 'arguments': {'code': 'inert'}}],
                            summarize=lambda q, r: (r, 'Two.', None))
    assert run_once(connection, tmp_path, model=model, executor=Executor()) == 'completed'
    assert queue.get(record.id).real_result == {'answer': 2}


@pytest.mark.live_postgres
def test_browser_http_contract_through_postgres_and_mocked_boundaries(request, tmp_path):
    """Actual multipart/API/storage/queue/worker; only model and executor are test doubles."""
    from contextlib import contextmanager
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from app.main import app
    from app.dataset_lookup_api import get_dataset_runtime
    from app.kata_demo_worker import run_once
    from app.executor_contract import ExecutorResult, ExecutorStatus, ExecutorObservation, RunState, CleanupState

    connection, _ = request.getfixturevalue('migrated_connection')
    tmp_path.chmod(0o700)
    @contextmanager
    def connect():
        yield connection
    runtime = SimpleNamespace(root=tmp_path, connection=connect)
    app.dependency_overrides[get_dataset_runtime] = lambda: runtime
    client = TestClient(app, base_url='http://127.0.0.1:8000')
    headers = {'Origin': 'http://127.0.0.1:8000', 'X-KataAI-Request': '1'}
    try:
        uploaded = client.post('/v1/datasets', files={'file': ('data.csv', b'quantity\n2\n', 'text/csv')}, headers=headers)
        assert uploaded.status_code == 201
        dataset_id = uploaded.json()['dataset_id']
        payload = {'schema_version': '1.0', 'client_request_id': str(uuid4()),
                   'dataset_id': dataset_id, 'question': 'Total quantity?'}
        created = client.post('/v1/requests', json=payload, headers=headers)
        assert created.status_code == 201
        retry = client.post('/v1/requests', json=payload, headers=headers)
        assert retry.status_code == 200 and retry.json()['id'] == created.json()['id']
        class Executor:
            def submit(self, value):
                return ExecutorResult(value.request_id, value.run_id, ExecutorStatus.ACCEPTED)
            def status(self, request_id, run_id):
                return ExecutorObservation(request_id, run_id, RunState.COMPLETED, CleanupState.PENDING)
            def read_result(self, *args): return b'{"answer":2}'
            def cleanup(self, *args): pass
        model = SimpleNamespace(generate=lambda *a: [{'name': 'run_python', 'arguments': {'code': '# inert test code'}}],
                                summarize=lambda q, r: (r, 'Two units.', None))
        assert run_once(connection, tmp_path, model=model, executor=Executor()) == 'completed'
        result = client.get('/v1/requests/' + created.json()['id']).json()
        assert result['result'] == {'answer': 2} and result['answer'] == 'Two units.'
        assert result['code'] == '# inert test code' and result['fake'] is False and result['run_id']
    finally:
        app.dependency_overrides.clear()
