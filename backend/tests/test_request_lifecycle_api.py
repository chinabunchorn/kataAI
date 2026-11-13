"""Lifecycle HTTP contract tests with synthetic in-memory dependencies."""
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app import request_api
from app.dataset_lookup_api import get_dataset_runtime
from app.main import app

RID = UUID('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb')


@pytest.fixture
def harness(monkeypatch):
    state = SimpleNamespace(events=[], status='cancelled', failure=False, records=[])

    class Connection:
        def commit(self):
            state.events.append('commit')
            if state.failure:
                raise RuntimeError('secret /private question')

    class Runtime:
        @contextmanager
        def connection(self):
            yield Connection()

    class Queue:
        def __init__(self, connection):
            pass

        def cancel(self, request_id):
            state.events.append(('cancel', request_id))
            return SimpleNamespace(id=request_id, status=state.status) if state.status else None

        def hide_history(self, request_id):
            state.events.append(('hide', request_id))
            return SimpleNamespace(id=request_id, status=state.status) if state.status else None

        def history(self, limit, before=None):
            state.events.append(('history', limit, before))
            return state.records

    monkeypatch.setattr(request_api, 'queue_factory', Queue)
    app.dependency_overrides[get_dataset_runtime] = lambda: Runtime()
    client = TestClient(app, base_url='http://127.0.0.1:8000', headers={
        'origin': 'http://127.0.0.1:8000', 'x-kataai-request': '1'})
    yield client, state
    app.dependency_overrides.clear()


def test_cancel_queued_commits_before_success(harness):
    client, state = harness
    response = client.post(f'/v1/requests/{RID}/cancel')
    assert response.status_code == 200
    assert response.json() == {'id': str(RID), 'status': 'cancelled', 'provisional': True}
    assert response.headers['cache-control'] == 'no-store'
    assert state.events == [('cancel', RID), 'commit']


@pytest.mark.parametrize('status', ['fake_completed', 'unknown'])
def test_cancel_terminal_or_uncertain_is_conflict(harness, status):
    client, state = harness
    state.status = status
    response = client.post(f'/v1/requests/{RID}/cancel')
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'REQUEST_CONFLICT'
    assert 'secret' not in response.text


def test_cancel_missing_is_not_found(harness):
    client, state = harness
    state.status = None
    response = client.post(f'/v1/requests/{RID}/cancel')
    assert response.status_code == 404


def test_hide_terminal_commits_before_success(harness):
    client, state = harness
    response = client.delete(f'/v1/requests/{RID}')
    assert response.status_code == 204
    assert response.headers['cache-control'] == 'no-store'
    assert state.events == [('hide', RID), 'commit']


@pytest.mark.parametrize('status', ['queued', 'running', 'cancel_requested', 'unknown'])
def test_hide_active_or_uncertain_is_conflict(harness, status):
    client, state = harness
    state.status = status
    response = client.delete(f'/v1/requests/{RID}')
    assert response.status_code == 409


def test_hide_missing_is_not_found(harness):
    client, state = harness
    state.status = None
    assert client.delete(f'/v1/requests/{RID}').status_code == 404


def test_validation_errors_are_not_cached(harness):
    client, _ = harness
    response = client.post('/v1/requests/private-not-a-uuid/cancel')
    assert response.status_code == 422
    assert response.headers['cache-control'] == 'no-store'
    assert 'private' not in response.text


def test_history_cursor_round_trip(harness):
    client, state = harness
    created = datetime(2026, 1, 2, tzinfo=timezone.utc)
    state.records = [SimpleNamespace(id=RID, dataset_id=RID, status='cancelled',
                                     question='question', created_at=created)]
    first = client.get('/v1/requests?limit=1')
    assert first.status_code == 200
    cursor = first.json()['next_cursor']
    state.records = []
    second = client.get('/v1/requests', params={'limit': 1, 'cursor': cursor})
    assert second.status_code == 200
    assert second.json()['requests'] == []
    assert state.events[-1] == ('history', 1, (created, RID))


def test_cancel_running_remains_cancel_requested(harness):
    client, state = harness
    state.status = 'cancel_requested'
    response = client.post(f'/v1/requests/{RID}/cancel')
    assert response.status_code == 200
    assert response.json()['status'] == 'cancel_requested'


@pytest.mark.parametrize('method,suffix', [('post', '/cancel'), ('delete', '')])
def test_commit_failure_is_sanitized_and_not_retried(harness, method, suffix):
    client, state = harness
    state.failure = True
    response = getattr(client, method)(f'/v1/requests/{RID}{suffix}')
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'EXECUTION_UNAVAILABLE'
    assert 'secret' not in response.text and '/private' not in response.text
    assert len(state.events) == 2 and state.events[-1] == 'commit'


@pytest.mark.parametrize('method,suffix', [('post', '/cancel'), ('delete', '')])
def test_writes_require_csrf_header(harness, method, suffix):
    _, state = harness
    client = TestClient(app, base_url='http://127.0.0.1:8000', headers={'origin': 'http://127.0.0.1:8000'})
    assert getattr(client, method)(f'/v1/requests/{RID}{suffix}').status_code == 403
    assert state.events == []


@pytest.mark.parametrize('cursor', ['secret!', 'a' * 257, ''])
def test_invalid_cursor_is_sanitized_and_does_not_access_queue(harness, cursor):
    client, state = harness
    response = client.get('/v1/requests', params={'cursor': cursor})
    assert response.status_code == 422
    assert response.headers['cache-control'] == 'no-store'
    assert 'secret' not in response.text
    assert state.events == []


def test_oversize_cancel_body_is_bounded_and_not_cached(harness):
    client, state = harness
    response = client.post(f'/v1/requests/{RID}/cancel', content=b'x' * 65537)
    assert response.status_code == 413
    assert response.headers['cache-control'] == 'no-store'
    assert state.events == []
