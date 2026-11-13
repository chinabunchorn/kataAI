import json
import socket
import threading
import time

import pytest

from app.model_adapter import LocalModelAdapter, ModelAdapterError


def tool_response(code='print(1)'):
    return {'choices': [{'finish_reason': 'tool_calls', 'message': {
        'tool_calls': [{'type': 'function', 'function': {
            'name': 'run_python', 'arguments': json.dumps({'code': code})}}]}}]}


def test_existing_fake_slice_accepts_generated_inert_proposal():
    from app.fakes import FakeExecutor
    from app.slice import run_fake_slice

    marker = 'raise RuntimeError("must never run")'
    adapter = LocalModelAdapter('http://127.0.0.1:8080/v1/chat/completions',
                                transport=lambda _: tool_response(marker))
    outcome = run_fake_slice(adapter, FakeExecutor({'fake': True, 'answer': 42}), 'question', ('column',))
    assert outcome == {'fake': True, 'answer': 42}


def test_generation_accepts_question_at_existing_unicode_character_limit():
    question = 'ก' * 4096
    adapter = LocalModelAdapter('http://127.0.0.1:8080/v1/chat/completions',
                                transport=lambda _: tool_response())
    assert adapter.generate(question, ['column'])[0]['name'] == 'run_python'


def test_generation_returns_one_inert_python_proposal():
    requests = []
    def transport(payload):
        requests.append(payload)
        return tool_response()
    adapter = LocalModelAdapter('http://127.0.0.1:8080/v1/chat/completions', transport=transport)
    assert adapter.generate('how many?', ('name',)) == [{'name': 'run_python', 'arguments': {'code': 'print(1)'}}]
    assert requests[0]['tool_choice'] == 'auto'
    assert 'insufficient' in requests[0]['messages'][0]['content'].lower()
    assert 'how many?' in requests[0]['messages'][1]['content']
    assert 'name' in requests[0]['messages'][1]['content']


@pytest.mark.parametrize('endpoint', [
    'http://localhost:8080/v1/chat/completions', 'http://127.0.0.2:8080/v1/chat/completions',
    'http://127.0.0.1.evil:8080/v1/chat/completions', 'https://127.0.0.1:8080/v1/chat/completions',
    'http://user@127.0.0.1:8080/v1/chat/completions', 'http://127.0.0.1:8080/v1/chat/completions?x=1',
])
def test_endpoint_rejects_ambiguous_or_remote_hosts(endpoint):
    with pytest.raises(ModelAdapterError, match='^MODEL_ADAPTER_FAILED$'):
        LocalModelAdapter(endpoint)


@pytest.mark.parametrize('mutate', [
    lambda c: c.update(finish_reason='stop'),
    lambda c: c['message']['tool_calls'].append(c['message']['tool_calls'][0]),
    lambda c: c['message']['tool_calls'][0]['function'].update(name='other'),
    lambda c: c['message']['tool_calls'][0]['function'].update(arguments='{"code":"x", "path":"secret"}'),
    lambda c: c['message']['tool_calls'][0]['function'].update(arguments='{"code":"x", "code":"y"}'),
    lambda c: c['message']['tool_calls'][0]['function'].update(arguments=json.dumps({'code': 'x' * 16385})),
    lambda c: c['message'].update(function_call={'name': 'run_python', 'arguments': '{"code":"x"}'}),
])
def test_rejects_invalid_or_multiple_proposals(mutate):
    response = tool_response()
    mutate(response['choices'][0])
    adapter = LocalModelAdapter('http://127.0.0.1:8080/v1/chat/completions', transport=lambda _: response)
    with pytest.raises(ModelAdapterError, match='^MODEL_ADAPTER_FAILED$'):
        adapter.generate('question', ('column',))


def test_summary_includes_original_question_and_validated_result():
    requests = []
    def transport(payload):
        requests.append(payload)
        return {'choices': [{'finish_reason': 'stop', 'message': {'content': 'three'}}]}
    adapter = LocalModelAdapter('http://127.0.0.1:8080/v1/chat/completions', transport=transport)
    assert adapter.summarize('How many rows?', {'count': 3}) == ({'count': 3}, 'three', None)
    content = json.loads(requests[0]['messages'][1]['content'])
    assert content == {'question': 'How many rows?', 'result': {'count': 3}}


def test_summary_preserves_result_and_disables_tools():
    data = {'answer': [1, {'v': True}]}
    requests = []
    def transport(payload):
        requests.append(payload)
        return {'choices': [{'finish_reason': 'stop', 'message': {'content': 'summary'}}]}
    result, summary, warning = LocalModelAdapter('http://127.0.0.1:8080/v1/chat/completions', transport=transport).summarize('question', data)
    assert result is data and summary == 'summary' and warning is None
    assert requests[0]['tool_choice'] == 'none' and 'tools' not in requests[0]


@pytest.mark.parametrize('value', [float('nan'), {'x': object()}, {'x': 'a' * 40000}])
def test_invalid_summary_input_is_never_sent(value):
    def forbidden(_):
        pytest.fail('invalid result must not be sent')
    adapter = LocalModelAdapter('http://127.0.0.1:8080/v1/chat/completions', transport=forbidden)
    result, summary, warning = adapter.summarize('question', value)
    assert result is value and summary is None and warning == 'SUMMARY_UNAVAILABLE'


def test_summary_failure_preserves_result_without_exception_detail():
    data = {'private': 'secret'}
    def broken(_):
        raise RuntimeError('secret')
    adapter = LocalModelAdapter('http://127.0.0.1:8080/v1/chat/completions', transport=broken)
    assert adapter.summarize('question', data) == (data, None, 'SUMMARY_UNAVAILABLE')


def server(reply, *, delay=0):
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    def serve():
        try:
            conn, _ = listener.accept()
            with conn:
                conn.recv(65536)
                if delay:
                    time.sleep(delay)
                conn.sendall(reply)
        except OSError:
            pass
        finally:
            listener.close()
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return f'http://127.0.0.1:{port}/v1/chat/completions', thread


def test_real_http_local_fake_model():
    body = json.dumps(tool_response()).encode()
    endpoint, thread = server(b'HTTP/1.1 200 OK\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body)
    try:
        assert LocalModelAdapter(endpoint).generate('q', ['c'])[0]['arguments']['code'] == 'print(1)'
    finally:
        thread.join(1)


@pytest.mark.parametrize('reply', [
    b'HTTP/1.1 302 Found\r\nLocation: http://example.com/\r\nContent-Length: 0\r\n\r\n',
    b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nContent-Length: 2\r\n\r\n{}',
    b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nTransfer-Encoding: chunked\r\n\r\n{}',
    b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nTransfer-Encoding: identity\r\n\r\n0\r\n\r\n',
    b'HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\nContent-Length: '
        + str(len(json.dumps(tool_response()).encode())).encode() + b'\r\n\r\n' + json.dumps(tool_response()).encode(),
    b'HTTP/1.1 200 OK\r\nX-Invalid: value\x00here\r\nContent-Length: '
        + str(len(json.dumps(tool_response()).encode())).encode() + b'\r\n\r\n' + json.dumps(tool_response()).encode(),
    b'HTTP/1.1 200 OK\r\nMalformed header\r\nContent-Length: 500\r\n\r\n' + json.dumps(tool_response()).encode(),
    b'HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n\r\n' + json.dumps(tool_response()).encode(),
    b'HTTP/1.1 200 OK\r\nContent-Length: 140000\r\n\r\n' + b'x' * 140000,
])
def test_http_rejects_redirect_truncation_and_oversize(reply):
    endpoint, thread = server(reply)
    try:
        with pytest.raises(ModelAdapterError, match='^MODEL_ADAPTER_FAILED$'):
            LocalModelAdapter(endpoint, timeout=2).generate('q', ['c'])
    finally:
        thread.join(1)


def test_http_rejects_unsupported_chunked_response():
    body = json.dumps(tool_response()).encode()
    reply = (b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n'
             + format(len(body), 'x').encode() + b'\r\n' + body + b'\r\n0\r\n\r\n')
    endpoint, thread = server(reply)
    try:
        with pytest.raises(ModelAdapterError):
            LocalModelAdapter(endpoint).generate('q', ['c'])
    finally:
        thread.join(1)


def test_http_accepts_fully_framed_response_before_connection_closes():
    body = json.dumps(tool_response()).encode()
    reply = b'HTTP/1.1 200 OK\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    def serve():
        conn, _ = listener.accept()
        with conn:
            conn.recv(65536)
            conn.sendall(reply)
            time.sleep(0.3)
        listener.close()
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        endpoint = f'http://127.0.0.1:{port}/v1/chat/completions'
        assert LocalModelAdapter(endpoint, timeout=0.1).generate('q', ['c'])[0]['arguments']['code'] == 'print(1)'
    finally:
        thread.join(1)


def test_http_total_deadline():
    endpoint, thread = server(b'', delay=0.2)
    start = time.monotonic()
    try:
        with pytest.raises(ModelAdapterError):
            LocalModelAdapter(endpoint, timeout=0.05).generate('q', ['c'])
        assert time.monotonic() - start < 0.18
    finally:
        thread.join(1)
