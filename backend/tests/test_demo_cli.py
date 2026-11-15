import httpx
from app import demo_cli


def test_cli_uses_existing_multipart_protocol_and_polls(monkeypatch, tmp_path, capsys):
    csv = tmp_path / 'sales.csv'
    csv.write_text('quantity\n2\n')
    calls = []
    def handle(request):
        calls.append(request)
        assert request.headers['host'] == '127.0.0.1:8000'
        assert request.headers['origin'] == 'http://127.0.0.1:8000'
        assert request.headers['x-kataai-request'] == '1'
        if request.url.path == '/v1/datasets':
            assert b'name="file"' in request.content and b'quantity' in request.content
            return httpx.Response(201, json={'dataset_id': 'dataset'})
        if request.url.path == '/v1/requests':
            import json
            payload = json.loads(request.content)
            assert payload['schema_version'] == '1.0' and payload['dataset_id'] == 'dataset'
            return httpx.Response(201, json={'id': 'request', 'status': 'queued'})
        return httpx.Response(200, json={'id': 'request', 'status': 'completed', 'fake': False,
                                         'result': {'answer': 770}, 'answer': '770 THB'})
    client_type = httpx.Client
    monkeypatch.setattr(demo_cli.httpx, 'Client', lambda **kwargs: client_type(**kwargs, transport=httpx.MockTransport(handle)))
    assert demo_cli.demo(csv, 'Revenue?') == 0
    assert len(calls) == 3 and '770 THB' in capsys.readouterr().out
