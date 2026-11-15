from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.frontend import mount_frontend
from app.local_security import LocalSecurityMiddleware


def test_static_frontend_preserves_security_and_api_routes(tmp_path):
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'assets' / 'app.js').write_text('public build')
    (tmp_path / 'index.html').write_text('<main>KataAI</main>')
    app = FastAPI()
    app.add_middleware(LocalSecurityMiddleware)
    mount_frontend(app, tmp_path)
    client = TestClient(app, base_url='http://127.0.0.1:8000')
    assert client.get('/').text == '<main>KataAI</main>'
    assert client.get('/assets/app.js').text == 'public build'
    assert client.get('/', headers={'Host': 'evil.example'}).status_code == 403
    assert client.get('/', headers={'Origin': 'http://evil.example'}).status_code == 403
    assert client.get('/v1/missing').status_code == 404
    assert client.get('/assets/../main.py').status_code == 404


def test_unbuilt_frontend_reports_unavailable(tmp_path):
    app = FastAPI()
    mount_frontend(app, tmp_path)
    assert TestClient(app).get('/').status_code == 503
