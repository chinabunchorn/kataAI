import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app


def asgi_post(chunks, headers):
    sent = []
    received = []
    messages = iter([
        {'type': 'http.request', 'body': chunk, 'more_body': index < len(chunks) - 1}
        for index, chunk in enumerate(chunks)
    ])

    async def receive():
        message = next(messages)
        received.append(message)
        return message

    async def send(message):
        sent.append(message)

    scope = {
        'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
        'method': 'POST', 'scheme': 'http', 'path': '/v1/requests',
        'raw_path': b'/v1/requests', 'query_string': b'',
        'headers': [(b'host', b'127.0.0.1:8000'), (b'origin', b'http://127.0.0.1:8000'),
                    (b'x-kataai-request', b'1'), *headers],
        'server': ('testserver', 80), 'client': ('testclient', 1),
    }
    asyncio.run(app(scope, receive, send))
    start = next(message for message in sent if message['type'] == 'http.response.start')
    body = b''.join(message.get('body', b'') for message in sent if message['type'] == 'http.response.body')
    return start['status'], json.loads(body), len(received)


@pytest.mark.parametrize('declared_length', [None, b'1'])
def test_streamed_oversize_ignores_missing_or_misleading_length(declared_length):
    headers = [(b'content-type', b'application/json')]
    if declared_length is not None:
        headers.append((b'content-length', declared_length))
    status, body, count = asgi_post([b' ' * 32768, b' ' * 32768, b'x', b'not read'], headers)
    assert status == 413
    assert body == {'error': {'code': 'REQUEST_TOO_LARGE', 'message': 'Request body is too large.'}}
    assert count == 3


def test_streamed_valid_body_ignores_misleading_high_length():
    payload = json.dumps({
        'schema_version': '1.0', 'client_request_id': '12345678-1234-4234-8234-123456789abc',
        'dataset_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'question': 'Question?',
    }).encode()
    status, body, count = asgi_post(
        [payload[:20], payload[20:]],
        [(b'content-type', b'application/json'), (b'content-length', b'999999')],
    )
    assert status == 503
    assert body == {'error': {'code': 'EXECUTION_UNAVAILABLE', 'message': 'Request processing is unavailable.'}}
    assert count == 2


@pytest.mark.parametrize('extra_bytes,expected_status', [(0, 503), (1, 413)])
def test_body_byte_limit_is_inclusive(extra_bytes, expected_status):
    payload = json.dumps({
        'schema_version': '1.0', 'client_request_id': '12345678-1234-4234-8234-123456789abc',
        'dataset_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'question': 'ยอดรวม',
    }, ensure_ascii=False).encode('utf-8')
    body = payload + b' ' * (65536 + extra_bytes - len(payload))
    response = TestClient(app, base_url='http://127.0.0.1:8000', headers={
        'origin': 'http://127.0.0.1:8000', 'x-kataai-request': '1',
    }).post('/v1/requests', content=body, headers={'content-type': 'application/json'})
    assert response.status_code == expected_status


def test_oversized_body_is_rejected_before_validation(monkeypatch):
    from app import fakes, slice

    def must_not_run(*args, **kwargs):
        raise AssertionError('adapter must not be called')

    monkeypatch.setattr(fakes.FakeModel, 'generate', must_not_run)
    monkeypatch.setattr(fakes.FakeExecutor, 'execute', must_not_run)
    monkeypatch.setattr(slice, 'run_fake_slice', must_not_run)
    response = TestClient(app, base_url='http://127.0.0.1:8000', headers={
        'origin': 'http://127.0.0.1:8000', 'x-kataai-request': '1',
    }).post(
        '/v1/requests', content=b'top-secret' + b' ' * 65536,
        headers={'content-type': 'application/json'},
    )
    assert response.status_code == 413
    assert response.json() == {'error': {'code': 'REQUEST_TOO_LARGE', 'message': 'Request body is too large.'}}
    assert 'top-secret' not in response.text


@pytest.mark.parametrize('question', ['What is the total?', 'ยอดรวมเท่าไร?'])
def test_valid_request_is_unavailable(question):
    client = TestClient(app, base_url='http://127.0.0.1:8000', headers={
        'origin': 'http://127.0.0.1:8000', 'x-kataai-request': '1',
    })
    payload = {
        'schema_version': '1.0',
        'client_request_id': '12345678-1234-4234-8234-123456789abc',
        'dataset_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        'question': question,
    }
    response = client.post('/v1/requests', json=payload)
    assert response.status_code == 503
    assert response.json() == {'error': {'code': 'EXECUTION_UNAVAILABLE', 'message': 'Request processing is unavailable.'}}


@pytest.mark.parametrize('changes', [
    {'schema_version': '2.0'}, {'schema_version': 1.0},
    {'client_request_id': 'not-a-uuid'}, {'client_request_id': 123},
    {'dataset_id': ''}, {'dataset_id': '   '}, {'dataset_id': 'x' * 257}, {'dataset_id': 1},
    {'question': ''}, {'question': ' \n'}, {'question': 'x' * 4097}, {'question': False},
    {'runtime': 'host'}, {'extra': 'secret-value'},
])
def test_invalid_request_has_safe_error(changes):
    payload = {
        'schema_version': '1.0',
        'client_request_id': '12345678-1234-4234-8234-123456789abc',
        'dataset_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        'question': 'Question?',
    }
    payload.update(changes)
    response = TestClient(app, base_url='http://127.0.0.1:8000', headers={
        'origin': 'http://127.0.0.1:8000', 'x-kataai-request': '1',
    }).post('/v1/requests', json=payload)
    assert response.status_code == 422
    assert response.json() == {'error': {'code': 'INVALID_REQUEST', 'message': 'Invalid request.'}}


@pytest.mark.parametrize('body', [
    b'{"secret":"top-secret",', b'null', b'[]', b'"top-secret"', b'{"question": "top-secret"}', b'\xff',
])
def test_malformed_or_wrong_shape_has_sanitized_error(body):
    response = TestClient(app, base_url='http://127.0.0.1:8000', headers={
        'origin': 'http://127.0.0.1:8000', 'x-kataai-request': '1',
    }).post('/v1/requests', content=body, headers={'content-type': 'application/json'})
    assert response.status_code == 422
    assert response.json() == {'error': {'code': 'INVALID_REQUEST', 'message': 'Invalid request.'}}
    assert 'top-secret' not in response.text


def test_bounds_are_inclusive_and_repeated_requests_make_no_promises(monkeypatch):
    from app import fakes, slice

    def must_not_run(*args, **kwargs):
        raise AssertionError('adapter must not be called')

    monkeypatch.setattr(fakes.FakeModel, 'generate', must_not_run)
    monkeypatch.setattr(fakes.FakeExecutor, 'execute', must_not_run)
    monkeypatch.setattr(slice, 'run_fake_slice', must_not_run)
    payload = {
        'schema_version': '1.0',
        'client_request_id': '12345678-1234-4234-8234-123456789abc',
        'dataset_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        'question': 'ก' * 4096,
    }
    client = TestClient(app, base_url='http://127.0.0.1:8000', headers={
        'origin': 'http://127.0.0.1:8000', 'x-kataai-request': '1',
    })
    for _ in range(2):
        response = client.post('/v1/requests', json=payload)
        assert response.status_code == 503
        assert response.json() == {'error': {'code': 'EXECUTION_UNAVAILABLE', 'message': 'Request processing is unavailable.'}}
        assert 'location' not in response.headers
        assert 'retry-after' not in response.headers
