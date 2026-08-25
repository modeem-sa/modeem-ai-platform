from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "modeem-ai-api"}


def test_info() -> None:
    response = client.get("/api/v1/info")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Modeem AI Platform API"
    assert body["version"] == "0.1.0"
    assert body["api_version"] == "v1"
    assert "environment" in body
