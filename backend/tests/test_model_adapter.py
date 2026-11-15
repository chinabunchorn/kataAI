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


def test_text_only_stop_is_distinct_sanitized_no_proposal_outcome():
    requests = []
    def transport(payload):
        requests.append(payload)
        return {'choices': [{'finish_reason': 'stop', 'message': {'content': 'untrusted secret'}}]}
    adapter = LocalModelAdapter('http://127.0.0.1:8080/v1/chat/completions', transport=transport)
    with pytest.raises(ModelAdapterError) as caught:
        adapter.generate('question', ['column'])
    assert type(caught.value).__name__ == 'ModelTextOnlyOutcome'
    assert str(caught.value) == 'MODEL_ADAPTER_FAILED'
    assert 'secret' not in repr(caught.value)
    assert len(requests) == 1


@pytest.mark.parametrize('message', [
    {'content': 'hello', 'role': 'user'},
    {'content': 'hello', 'role': None},
])
def test_text_only_requires_assistant_role_when_present(message):
    response = {'choices': [{'finish_reason': 'stop', 'message': message}]}
    adapter = LocalModelAdapter('http://127.0.0.1:8080/v1/chat/completions', transport=lambda _: response)
    with pytest.raises(ModelAdapterError) as caught:
        adapter.generate('question', ['column'])
    assert type(caught.value) is ModelAdapterError


@pytest.mark.parametrize('finish,message', [
    ('stop', {'content': ''}),
    ('stop', {'content': '  '}),
    ('stop', {'content': None}),
    ('stop', {'content': 'x' * 8193}),
    ('stop', {'content': 'bad\x00text'}),
    ('stop', {'content': 'hello', 'tool_calls': {}}),
    ('stop', {'content': 'hello', 'tool_calls': [{'type': 'function'}]}),
    ('stop', {'content': 'hello', 'function_call': {}}),
    ('length', {'content': 'hello'}),
    ('tool_calls', {'content': 'hello'}),
])
def test_invalid_text_only_responses_remain_generic_errors(finish, message):
    response = {'choices': [{'finish_reason': finish, 'message': message}]}
    adapter = LocalModelAdapter('http://127.0.0.1:8080/v1/chat/completions', transport=lambda _: response)
    with pytest.raises(ModelAdapterError) as caught:
        adapter.generate('question', ['column'])
    assert type(caught.value) is ModelAdapterError


@pytest.mark.parametrize('calls', [None, []])
def test_text_only_response_with_empty_calls_never_reaches_executor(calls):
    from app.model_adapter import ModelTextOnlyOutcome
    from app.slice import run_fake_slice

    class ForbiddenExecutor:
        def execute(self, proposal):
            pytest.fail('text-only response must not be executed')

    response = {'choices': [{'finish_reason': 'stop', 'message': {
        'role': 'assistant', 'content': 'arbitrary text, not necessarily a clarification',
        'tool_calls': calls, 'function_call': None}}]}
    adapter = LocalModelAdapter('http://127.0.0.1:8080/v1/chat/completions', transport=lambda _: response)
    with pytest.raises(ModelTextOnlyOutcome):
        run_fake_slice(adapter, ForbiddenExecutor(), 'question', ('column',))


@pytest.mark.parametrize('role,content', [
    ('user', None), ('system', None), (None, None),
    ('assistant', 'I refuse'), ('assistant', ' '), ('assistant', 123),
])
def test_tool_call_rejects_nonassistant_role_or_mixed_text(role, content):
    response = tool_response()
    response['choices'][0]['message'].update(role=role, content=content)
    adapter = LocalModelAdapter('http://127.0.0.1:8080/v1/chat/completions', transport=lambda _: response)
    with pytest.raises(ModelAdapterError):
        adapter.generate('question', ('column',))


@pytest.mark.parametrize('content', [None, ''])
def test_tool_call_accepts_explicit_assistant_with_empty_content(content):
    response = tool_response()
    response['choices'][0]['message'].update(role='assistant', content=content)
    adapter = LocalModelAdapter('http://127.0.0.1:8080/v1/chat/completions', transport=lambda _: response)
    assert adapter.generate('question', ('column',)) == [
        {'name': 'run_python', 'arguments': {'code': 'print(1)'}}]


def test_generation_requests_provisional_qwen_mvp_contract_and_sampling():
    requests = []
    def transport(payload):
        requests.append(payload)
        return tool_response('raise RuntimeError("inert")')

    adapter = LocalModelAdapter('http://127.0.0.1:8080/v1/chat/completions',
                                model='operator-model', transport=transport)
    assert adapter.generate('total?', ['sales']) == [
        {'name': 'run_python', 'arguments': {'code': 'raise RuntimeError("inert")'}}]
    assert len(requests) == 1
    payload = requests[0]
    assert payload['model'] == 'operator-model'
    prompt = payload['messages'][0]['content']
    assert payload['messages'][0]['role'] == 'system'
    for requirement in ('Python 3.12', 'standard library', '/inputs/data.csv',
                        '/inputs/script.py', '/tmp/result.json', 'utf-8-sig',
                        '2048', '30 seconds', 'run_python', '16384'):
        assert requirement in prompt
    assert 'pandas' not in prompt and 'DataFrame' not in prompt
    assert json.loads(payload['messages'][1]['content']) == {'question': 'total?', 'columns': ['sales']}
    assert {key: payload[key] for key in ('max_tokens', 'temperature', 'top_p', 'top_k', 'min_p',
                                            'presence_penalty', 'repeat_penalty')} == {
        'max_tokens': 4096, 'temperature': 0.6, 'top_p': 0.95, 'top_k': 20,
        'min_p': 0.0, 'presence_penalty': 0.0, 'repeat_penalty': 1.0}
    assert 'seed' not in payload


def test_generation_uses_public_preflight_exact_json():
    from app import model_adapter

    requests = []
    def transport(payload):
        requests.append(payload)
        return tool_response()

    question = 'ยอด "รวม"\\รายการ\n?'
    columns = ('ราคา', 'a"b\\c')
    encoded = model_adapter.encode_generation_input(question, columns)
    assert encoded == '{"question":"ยอด \\"รวม\\"\\\\รายการ\\n?","columns":["ราคา","a\\"b\\\\c"]}'
    adapter = LocalModelAdapter('http://127.0.0.1:8080/v1/chat/completions', transport=transport)
    adapter.generate(question, columns)
    assert requests[0]['messages'][1]['content'] == encoded


@pytest.mark.parametrize('question,columns', [
    ('ก' * 4096, ['ก' * 341 + 'a']),
    ('😀' * 4096, ['a' * 1024]),
    ('q', ['c'] * 256),
])
def test_generation_preflight_accepts_valid_boundaries(question, columns):
    from app.model_adapter import encode_generation_input
    assert json.loads(encode_generation_input(question, columns)) == {
        'question': question, 'columns': columns}


@pytest.mark.parametrize('question,columns', [
    ('ก' * 4097, ['c']), ('😀' * 4097, ['c']),
    ('', ['c']), ('  ', ['c']), ('private\x00question', ['c']),
    ('\ud800', ['c']), (None, ['c']),
    ('q', []), ('q', ['c'] * 257), ('q', 'column'),
    ('q', ['ก' * 342]), ('q', ['a' * 1025]), ('q', [' ']),
    ('q', ['private\x00column']), ('q', ['\ud800']), ('q', [123]),
])
def test_generation_preflight_rejects_invalid_inputs_without_sending(question, columns):
    from app.model_adapter import encode_generation_input
    def forbidden(_):
        pytest.fail('invalid input must not reach transport')
    adapter = LocalModelAdapter('http://127.0.0.1:8080/v1/chat/completions', transport=forbidden)
    for operation in (encode_generation_input, adapter.generate):
        with pytest.raises(ModelAdapterError, match='^MODEL_ADAPTER_FAILED$') as caught:
            operation(question, columns)
        assert 'private' not in repr(caught.value)


def test_generation_preflight_enforces_encoded_json_byte_limit_including_escapes():
    from app.model_adapter import encode_generation_input

    columns = ['a' * 1024] * 31 + ['']
    base = json.dumps({'question': 'q', 'columns': columns}, ensure_ascii=False,
                      separators=(',', ':')).encode('utf-8')
    remaining = 32768 - len(base)
    columns[-1] = '"' * (remaining // 2) + 'x' * (remaining % 2)
    assert len(columns[-1].encode('utf-8')) <= 1024
    encoded = encode_generation_input('q', columns)
    assert len(encoded.encode('utf-8')) == 32768
    columns[-1] += 'x'
    with pytest.raises(ModelAdapterError, match='^MODEL_ADAPTER_FAILED$'):
        encode_generation_input('q', columns)


def test_generation_preflight_rejects_double_escaped_outer_request_before_transport():
    import csv
    import io
    from app.model_adapter import encode_generation_input

    columns = [f'{i:02d}' + '"' * 998 for i in range(16)]
    csv_file = io.StringIO(newline='')
    csv.writer(csv_file).writerow(columns)
    csv_file.seek(0)
    assert next(csv.reader(csv_file)) == columns
    inner = json.dumps({'question': 'q', 'columns': columns}, ensure_ascii=False,
                       separators=(',', ':')).encode('utf-8')
    assert len(set(columns)) == len(columns)
    assert len(inner) <= 32768

    def forbidden(_):
        pytest.fail('oversized request must not reach transport')

    adapter = LocalModelAdapter('http://127.0.0.1:8080/v1/chat/completions', transport=forbidden)
    for operation in (encode_generation_input, adapter.generate):
        with pytest.raises(ModelAdapterError, match='^MODEL_ADAPTER_FAILED$'):
            operation('q', columns)


def test_generation_outer_worst_case_exact_boundary_matches_preflight():
    from app.model_adapter import encode_generation_input, MAX_REQUEST_BYTES

    requests = []
    worst_model = '\x01' * 256
    adapter = LocalModelAdapter('http://127.0.0.1:8080/v1/chat/completions',
                                model=worst_model,
                                transport=lambda payload: requests.append(payload) or tool_response())
    adapter.generate('q', ['c'])
    template = requests.pop()
    columns = [f'{i:02d}' + '"' * 898 for i in range(16)]

    def sizes(question):
        inner = json.dumps({'question': question, 'columns': columns}, ensure_ascii=False,
                           separators=(',', ':'))
        template['messages'][1]['content'] = inner
        outer = json.dumps(template, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        return len(inner.encode('utf-8')), len(outer)

    base = sizes('q')[1]
    quote_count, padding = divmod(MAX_REQUEST_BYTES - base, 4)
    question = 'q' + '"' * quote_count + 'x' * padding
    assert len(question) <= 4096
    assert sizes(question)[0] <= 32768
    assert sizes(question)[1] == MAX_REQUEST_BYTES
    assert json.loads(encode_generation_input(question, columns)) == {'question': question, 'columns': columns}
    assert adapter.generate(question, columns)[0]['name'] == 'run_python'
    assert len(json.dumps(requests.pop(), ensure_ascii=False, separators=(',', ':')).encode('utf-8')) == MAX_REQUEST_BYTES

    question += 'x'
    assert sizes(question)[1] == MAX_REQUEST_BYTES + 1
    for operation in (encode_generation_input, adapter.generate):
        with pytest.raises(ModelAdapterError, match='^MODEL_ADAPTER_FAILED$'):
            operation(question, columns)
    assert requests == []
    # A smaller model would fit, but admission intentionally covers every
    # valid worker configuration instead of trusting the current worker.
    template['model'] = 'local-model'
    assert sizes(question)[1] < MAX_REQUEST_BYTES


def test_generation_outer_overflow_maps_to_http_422_without_enqueue(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from app import dataset_columns, request_api

    columns = [f'{i:02d}' + '"' * 998 for i in range(16)]
    monkeypatch.setattr(dataset_columns, 'read_dataset_columns', lambda root, key: columns)

    class Queue:
        def create(self, request_id, dataset_id, question, validate):
            validate('dataset.csv')
            pytest.fail('incompatible request must not be enqueued')

    monkeypatch.setattr(request_api, 'queue_factory', lambda connection: Queue())
    runtime = SimpleNamespace(root='unused', connection=lambda: nullcontext(object()))
    payload = SimpleNamespace(question='q', client_request_id='00000000-0000-0000-0000-000000000001',
                              dataset_id='00000000-0000-0000-0000-000000000002')
    response = request_api.create_request(payload, runtime)
    assert response.status_code == 422
    assert json.loads(response.body)['error']['code'] == 'MODEL_INPUT_INCOMPATIBLE'


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


@pytest.mark.parametrize('mutate', [
    lambda msg: msg.update(role='user'),
    lambda msg: msg.update(role=None),
    lambda msg: msg.update(tool_calls={}),
    lambda msg: msg.update(tool_calls=''),
    lambda msg: msg.update(tool_calls=False),
    lambda msg: msg.update(function_call={}),
    lambda msg: msg.update(function_call=''),
    lambda msg: msg.update(function_call=False),
])
def test_summary_rejects_invalid_role_or_malformed_tool_fields(mutate):
    data = {'answer': 3}
    response = {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': 'three'}}]}
    mutate(response['choices'][0]['message'])
    adapter = LocalModelAdapter('http://127.0.0.1:8080/v1/chat/completions', transport=lambda _: response)
    result, summary, warning = adapter.summarize('question', data)
    assert result is data
    assert summary is None
    assert warning == 'SUMMARY_UNAVAILABLE'


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
    assert requests[0]['chat_template_kwargs'] == {'enable_thinking': False}


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
