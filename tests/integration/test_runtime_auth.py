from fastapi.testclient import TestClient

from quant_trading.api.main import create_app
from quant_trading.config import AppSettings
from quant_trading.storage.db import create_all, make_engine


def make_client(require_auth: bool = True) -> TestClient:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    settings = AppSettings(require_auth=require_auth, api_token="local-token")
    return TestClient(create_app(engine=engine, settings=settings))


def test_health_remains_public_when_auth_enabled():
    client = make_client()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_dashboard_requires_auth_when_enabled():
    client = make_client()

    response = client.get("/dashboard")

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


def test_workflow_command_requires_auth_when_enabled():
    client = make_client()

    response = client.post("/workflows/import-legacy", json={"legacy_db_path": "x.sqlite3"})

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


def test_read_api_requires_auth_when_enabled():
    client = make_client()

    response = client.get("/instruments")

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


def test_bearer_token_allows_protected_request():
    client = make_client()

    response = client.get("/dashboard", headers={"Authorization": "Bearer local-token"})

    assert response.status_code == 200
    assert "Operations Workbench" in response.text


def test_x_api_token_allows_protected_request():
    client = make_client()

    response = client.get("/instruments", headers={"X-API-Token": "local-token"})

    assert response.status_code == 200
    assert response.json() == []


def test_wrong_token_returns_401():
    client = make_client()

    response = client.get("/dashboard", headers={"Authorization": "Bearer wrong-token"})

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


def test_auth_disabled_keeps_local_routes_open():
    client = make_client(require_auth=False)

    response = client.get("/dashboard")

    assert response.status_code == 200
