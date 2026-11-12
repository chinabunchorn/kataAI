from fastapi.testclient import TestClient


def test_health_reports_ok():
    from app.main import app

    response = TestClient(app, base_url='http://127.0.0.1:8000').get('/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}
