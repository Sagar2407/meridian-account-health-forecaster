from fastapi.testclient import TestClient

from meridian.api.main import app

client = TestClient(app)


def test_health_contract() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "meridian-api",
        "version": "0.1.0",
        "environment": "development",
        "data_mode": "synthetic",
    }


def test_openapi_exposes_health_only() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert set(response.json()["paths"]) == {"/api/health"}
