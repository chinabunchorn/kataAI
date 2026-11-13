"""HTTP contract tests use isolated synthetic dependencies, never a user database."""
from fastapi.testclient import TestClient

from app.main import app


def test_dataset_id_must_be_uuid_even_without_runtime():
    client = TestClient(app, base_url='http://127.0.0.1:8000', headers={
        'origin': 'http://127.0.0.1:8000', 'x-kataai-request': '1',
    })
    response = client.post('/v1/requests', json={
        'schema_version': '1.0', 'client_request_id': '12345678-1234-4234-8234-123456789abc',
        'dataset_id': 'secret-invalid-id', 'question': 'Question?',
    })
    assert response.status_code == 422
    assert 'secret-invalid-id' not in response.text


def test_question_rejects_nul_and_unpaired_surrogate():
    import json
    client = TestClient(app, base_url='http://127.0.0.1:8000', headers={
        'origin': 'http://127.0.0.1:8000', 'x-kataai-request': '1',
    })
    for question in ['private\x00value', 'private\ud800']:
        payload = {'schema_version': '1.0',
                   'client_request_id': '12345678-1234-4234-8234-123456789abc',
                   'dataset_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'question': question}
        response = client.post('/v1/requests', content=json.dumps(payload),
                               headers={'content-type': 'application/json'})
        assert response.status_code == 422
        assert 'private' not in response.text


def test_create_persists_and_returns_only_safe_status(monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from uuid import UUID
    from app.dataset_lookup_api import get_dataset_runtime
    from app import request_api

    events = []
    class Connection:
        def commit(self):
            events.append('commit')
    class Runtime:
        @contextmanager
        def connection(self):
            yield Connection()
    class Queue:
        def __init__(self, connection):
            pass
        def create(self, client_id, dataset_id, question):
            events.append((client_id, dataset_id, question))
            return SimpleNamespace(id=UUID('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'), status='queued'), True
    monkeypatch.setattr(request_api, 'queue_factory', Queue)
    app.dependency_overrides[get_dataset_runtime] = lambda: Runtime()
    try:
        client = TestClient(app, base_url='http://127.0.0.1:8000', headers={
            'origin': 'http://127.0.0.1:8000', 'x-kataai-request': '1',
        })
        response = client.post('/v1/requests', json={
            'schema_version': '1.0', 'client_request_id': '12345678-1234-4234-8234-123456789abc',
            'dataset_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'question': 'private question',
        })
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 201
    assert response.headers['cache-control'] == 'no-store'
    assert response.json() == {'id': 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'status': 'queued', 'provisional': True}
    assert events == [(UUID('12345678-1234-4234-8234-123456789abc'), UUID('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'), 'private question'), 'commit']


def test_history_returns_bounded_safe_statuses(monkeypatch):
    from contextlib import contextmanager
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from uuid import UUID
    from app import request_api
    from app.dataset_lookup_api import get_dataset_runtime
    class Runtime:
        @contextmanager
        def connection(self):
            yield object()
    class Queue:
        def __init__(self, connection):
            pass
        def history(self, limit):
            assert limit == 2
            return [SimpleNamespace(id=UUID('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'), status='queued',
                                    dataset_id=UUID('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'), question='secret',
                                    created_at=datetime(2026, 1, 2, tzinfo=timezone.utc))]
    monkeypatch.setattr(request_api, 'queue_factory', Queue)
    app.dependency_overrides[get_dataset_runtime] = lambda: Runtime()
    try:
        client = TestClient(app, base_url='http://127.0.0.1:8000')
        response = client.get('/v1/requests?limit=2')
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        assert response.json() == {'requests': [{'id': 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
            'status': 'queued', 'provisional': True, 'dataset_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            'question': 'secret', 'created_at': '2026-01-02T00:00:00+00:00'}]}
        assert client.get('/v1/requests?limit=101').status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_status_get_and_missing(monkeypatch):
    from contextlib import contextmanager
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from uuid import UUID
    from app import request_api
    from app.dataset_lookup_api import get_dataset_runtime
    rid = UUID('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb')
    class Runtime:
        @contextmanager
        def connection(self):
            yield object()
    class Queue:
        def __init__(self, connection): pass
        def get(self, request_id):
            return (SimpleNamespace(id=rid, status='queued', question='secret',
                                    dataset_id=UUID('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'),
                                    created_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
                    if request_id == rid else None)
    monkeypatch.setattr(request_api, 'queue_factory', Queue)
    app.dependency_overrides[get_dataset_runtime] = lambda: Runtime()
    try:
        client = TestClient(app, base_url='http://127.0.0.1:8000')
        response = client.get('/v1/requests/' + str(rid))
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        assert response.json() == {'id': str(rid), 'status': 'queued', 'provisional': True,
                                   'dataset_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
                                   'question': 'secret', 'created_at': '2026-01-02T00:00:00+00:00'}
        assert client.get('/v1/requests/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa').status_code == 404
        assert client.get('/v1/requests/invalid').status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_commit_failure_is_not_success(monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from uuid import UUID
    from app import request_api
    from app.dataset_lookup_api import get_dataset_runtime
    class Connection:
        def commit(self): raise RuntimeError('secret sql')
    class Runtime:
        @contextmanager
        def connection(self): yield Connection()
    class Queue:
        def __init__(self, connection): pass
        def create(self, *args):
            return SimpleNamespace(id=UUID('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'), status='queued'), True
    monkeypatch.setattr(request_api, 'queue_factory', Queue)
    app.dependency_overrides[get_dataset_runtime] = lambda: Runtime()
    try:
        client = TestClient(app, base_url='http://127.0.0.1:8000', headers={'origin': 'http://127.0.0.1:8000', 'x-kataai-request': '1'})
        response = client.post('/v1/requests', json={'schema_version': '1.0', 'client_request_id': '12345678-1234-4234-8234-123456789abc', 'dataset_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'question': 'private'})
        assert response.status_code == 503
        assert 'secret' not in response.text
    finally:
        app.dependency_overrides.clear()


def test_missing_dataset_is_not_found(monkeypatch):
    from contextlib import contextmanager
    from app import request_api
    from app.dataset_lookup_api import get_dataset_runtime
    from app.dataset_store import DatasetNotFound
    class Runtime:
        @contextmanager
        def connection(self): yield object()
    class Queue:
        def __init__(self, connection): pass
        def create(self, *args): raise DatasetNotFound()
    monkeypatch.setattr(request_api, 'queue_factory', Queue)
    app.dependency_overrides[get_dataset_runtime] = lambda: Runtime()
    try:
        client = TestClient(app, base_url='http://127.0.0.1:8000', headers={'origin': 'http://127.0.0.1:8000', 'x-kataai-request': '1'})
        response = client.post('/v1/requests', json={'schema_version': '1.0', 'client_request_id': '12345678-1234-4234-8234-123456789abc', 'dataset_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'question': 'private'})
        assert response.status_code == 404
        assert response.headers['cache-control'] == 'no-store'
    finally:
        app.dependency_overrides.clear()


def test_history_rejects_unbounded_or_unrecognized_status(monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from uuid import uuid4
    from app import request_api
    from app.dataset_lookup_api import get_dataset_runtime
    class Runtime:
        @contextmanager
        def connection(self): yield object()
    class Queue:
        def __init__(self, connection): pass
        def history(self, limit): return [SimpleNamespace(id=uuid4(), status='secret' * 10000)]
    monkeypatch.setattr(request_api, 'queue_factory', Queue)
    app.dependency_overrides[get_dataset_runtime] = lambda: Runtime()
    try:
        response = TestClient(app, base_url='http://127.0.0.1:8000').get('/v1/requests')
        assert response.status_code == 503
        assert 'secret' not in response.text
    finally:
        app.dependency_overrides.clear()


def test_history_record_is_identifiable_as_plain_data():
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from uuid import uuid4
    from app.request_api import public_record

    dataset_id = uuid4()
    question = '<script>not code</script> ยอดรวมเท่าไร?'
    record = SimpleNamespace(id=uuid4(), dataset_id=dataset_id, status='queued',
                             question=question, created_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
    payload = public_record(record, include_detail=True)
    assert payload['dataset_id'] == str(dataset_id)
    assert payload['question'] == question
    assert payload['created_at'] == '2026-01-02T00:00:00+00:00'


def test_fake_completed_is_explicitly_identified():
    from types import SimpleNamespace
    from uuid import uuid4
    from app.request_api import public_record
    result = public_record(SimpleNamespace(id=uuid4(), status='fake_completed'))
    assert result['status'] == 'fake_completed'
    assert result['fake'] is True


def test_idempotency_conflict_is_sanitized_409(monkeypatch):
    import sys
    from contextlib import contextmanager
    from types import ModuleType
    from app import request_api
    from app.dataset_lookup_api import get_dataset_runtime
    class Conflict(Exception):
        pass
    module = ModuleType('app.request_queue')
    module.IdempotencyConflict = Conflict
    monkeypatch.setitem(sys.modules, 'app.request_queue', module)
    class Runtime:
        @contextmanager
        def connection(self): yield object()
    class Queue:
        def __init__(self, connection): pass
        def create(self, *args): raise Conflict('private')
    monkeypatch.setattr(request_api, 'queue_factory', Queue)
    app.dependency_overrides[get_dataset_runtime] = lambda: Runtime()
    try:
        client = TestClient(app, base_url='http://127.0.0.1:8000', headers={'origin': 'http://127.0.0.1:8000', 'x-kataai-request': '1'})
        response = client.post('/v1/requests', json={'schema_version': '1.0', 'client_request_id': '12345678-1234-4234-8234-123456789abc', 'dataset_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'question': 'private'})
        assert response.status_code == 409
        assert 'private' not in response.text
    finally:
        app.dependency_overrides.clear()
