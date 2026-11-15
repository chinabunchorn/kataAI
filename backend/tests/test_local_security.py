import asyncio

import pytest
from fastapi.testclient import TestClient

from app.main import app

HOST = (b'host', b'127.0.0.1:8000')
ORIGIN = (b'origin', b'http://127.0.0.1:8000')
CSRF = (b'x-kataai-request', b'1')


def request(method='GET', headers=None, path='/health', target=app):
    sent, reads = [], []

    async def receive():
        reads.append(True)
        return {'type': 'http.request', 'body': b'secret', 'more_body': False}

    async def send(message):
        sent.append(message)

    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
             'method': method, 'scheme': 'http', 'path': path, 'raw_path': path.encode(),
             'query_string': b'', 'headers': headers if headers is not None else [HOST],
             'server': ('127.0.0.1', 8000), 'client': ('127.0.0.1', 1234)}
    asyncio.run(target(scope, receive, send))
    start = next(m for m in sent if m['type'] == 'http.response.start')
    return start['status'], dict(start['headers']), reads, sent


def test_foreign_host_is_rejected():
    response = TestClient(app, base_url='http://evil.example:8000').get('/health')
    assert response.status_code == 403


@pytest.mark.parametrize('headers', [[], [(b'host', b'localhost:8000')],
    [(b'host', b'127.0.0.1:8001')], [(b'host', b'127.0.0.1')],
    [HOST, HOST], [(b'host', b'127.0.0.1:8000, evil')],
    [(b'host', b'evil.test'), (b'x-forwarded-host', b'127.0.0.1:8000')],
    [HOST, (b'origin', b'null')], [HOST, (b'origin', b'http://evil.test')],
    [HOST, (b'origin', b'http://127.0.0.1:8001')], [HOST, ORIGIN, ORIGIN],
    [HOST, (b'origin', b'http://127.0.0.1:8000/')] ])
def test_bad_headers_denied_before_body(headers):
    status, _, reads, sent = request('POST', headers, '/v1/requests')
    assert status == 403
    assert reads == []
    assert b'secret' not in str(sent).encode()


@pytest.mark.parametrize('method', ['POST', 'PUT', 'PATCH', 'DELETE', 'TRACE', 'CONNECT'])
@pytest.mark.parametrize('headers', [[HOST], [HOST, ORIGIN], [HOST, CSRF], [HOST, ORIGIN, CSRF, CSRF]])
def test_unsafe_methods_need_origin_and_custom_header_on_unknown_routes(method, headers):
    status, _, reads, _ = request(method, headers, '/unknown')
    assert status == 403
    assert not reads


def test_originless_safe_health_allowed():
    assert request(headers=[HOST])[0] == 200


@pytest.mark.parametrize('headers', [[HOST, (b'origin', b'null')],
                                     [HOST, ORIGIN, ORIGIN],
                                     [HOST, (b'origin', b'http://evil.test')],
                                     [HOST, (b'x-forwarded-host', b'evil.test'),
                                      (b'origin', b'http://evil.test')]])
def test_read_requests_also_reject_deceptive_origins(headers):
    assert request('GET', headers)[0] == 403


@pytest.mark.parametrize('path', ['/docs', '/redoc'])
def test_external_cdn_interactive_docs_are_not_served(path):
    assert request('GET', [HOST], path)[0] == 404


def test_dataset_routes_fail_closed_without_configuration(monkeypatch):
    from uuid import uuid4

    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.delenv('KATAAI_DATASET_ROOT', raising=False)
    headers = [HOST, ORIGIN, CSRF, (b'content-type', b'multipart/form-data; boundary=abc')]
    assert request('POST', headers, '/v1/datasets')[0] == 503
    assert request('GET', [HOST], f'/v1/datasets/{uuid4()}')[0] == 503


def test_preflight_is_strict_and_never_reads_body():
    headers = [HOST, ORIGIN, (b'access-control-request-method', b'POST'),
               (b'access-control-request-headers', b'content-type, x-kataai-request')]
    status, result, reads, _ = request('OPTIONS', headers, '/unknown')
    assert status == 204
    assert result[b'access-control-allow-origin'] == ORIGIN[1]
    assert b'*' not in result.values()
    assert not reads
    for bad in ([HOST, (b'origin', b'null'), *headers[2:]],
                [HOST, ORIGIN, (b'access-control-request-method', b'TRACE')],
                [HOST, ORIGIN, (b'access-control-request-method', b'POST'),
                 (b'access-control-request-headers', b'x-unapproved')],
                [HOST, ORIGIN, headers[2], headers[2]],
                [HOST, ORIGIN, headers[2], headers[3], headers[3]],
                [HOST, ORIGIN, headers[2], (b'access-control-request-headers', b'')],
                [HOST, ORIGIN, headers[2], (b'access-control-request-headers', b'content-type,,x-kataai-request')]):
        status, _, reads, _ = request('OPTIONS', bad)
        assert status == 403
        assert not reads


def test_valid_origin_receives_exact_cors_header():
    status, headers, _, _ = request(headers=[HOST, ORIGIN])
    assert status == 200
    assert headers[b'access-control-allow-origin'] == ORIGIN[1]
    assert b'access-control-allow-credentials' not in headers


def test_configuration_must_be_explicit_valid_loopback():
    from app.local_security import SecurityPolicy

    for host, origin in [('', 'http://127.0.0.1:8000'), ('*', 'http://127.0.0.1:8000'),
                         ('localhost:8000', 'http://127.0.0.1:8000'),
                         ('127.0.0.1:8000', 'null'), ('127.0.0.1:8000', ''),
                         ('127.0.0.1:8000', 'https://evil.test')]:
        with pytest.raises(ValueError):
            SecurityPolicy(host, origin)
    assert SecurityPolicy('127.0.0.1:8123', 'http://127.0.0.1:3000').host == '127.0.0.1:8123'


def test_injected_policy_distinguishes_backend_host_and_frontend_origin():
    from app.local_security import LocalSecurityMiddleware, SecurityPolicy

    async def downstream(scope, receive, send):
        from starlette.responses import Response
        await Response(status_code=204)(scope, receive, send)

    target = LocalSecurityMiddleware(downstream, SecurityPolicy('127.0.0.1:8123', 'http://127.0.0.1:3000'))
    valid = [(b'host', b'127.0.0.1:8123'), (b'origin', b'http://127.0.0.1:3000'), CSRF]
    assert request('POST', valid, target=target)[0] == 204
    assert request('POST', [HOST, *valid[1:]], target=target)[0] == 403
    assert request('POST', [valid[0], ORIGIN, CSRF], target=target)[0] == 403


def test_websocket_is_refused():
    sent = []
    async def receive():
        return {'type': 'websocket.connect'}
    async def send(message):
        sent.append(message)
    asyncio.run(app({'type': 'websocket', 'asgi': {'version': '3.0'}, 'path': '/',
                     'headers': [], 'query_string': b'', 'scheme': 'ws', 'subprotocols': []}, receive, send))
    assert sent == [{'type': 'websocket.close', 'code': 1008}]
