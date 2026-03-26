"""API integration tests — FastAPI TestClient with real Supabase DB connection.

Tests verify endpoint availability, status codes, and basic response shapes.
No seed data is assumed; empty results are expected.
"""

import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ---------- Health ----------


def test_health(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert data["status"] == "ok"
    assert "version" in data


# ---------- Entities ----------


def test_list_entities(client: TestClient):
    resp = client.get("/api/entities")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_list_entities_shape(client: TestClient):
    """If entities exist, each row should have id, code, name keys."""
    resp = client.get("/api/entities")
    data = resp.json()
    if len(data) > 0:
        first = data[0]
        assert "id" in first
        assert "code" in first
        assert "name" in first


# ---------- Dashboard ----------


def test_dashboard(client: TestClient):
    resp = client.get("/api/dashboard", params={"entity_id": 1})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)


def test_nonexistent_entity_dashboard(client: TestClient):
    """Non-existent entity returns 200 with empty/zero data, not an error."""
    resp = client.get("/api/dashboard", params={"entity_id": 9999})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)


# ---------- Cashflow ----------


def test_cashflow_actual(client: TestClient):
    resp = client.get(
        "/api/cashflow/actual",
        params={"entity_id": 1, "year": 2026, "month": 3},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "year" in data
    assert "month" in data
    assert data["year"] == 2026
    assert data["month"] == 3


def test_cashflow_forecast(client: TestClient):
    resp = client.get(
        "/api/cashflow/forecast",
        params={"entity_id": 1, "year": 2026, "month": 3},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)


# ---------- Accounts ----------


def test_accounts_standard(client: TestClient):
    resp = client.get("/api/accounts/standard")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


# ---------- Upload ----------


def test_upload_no_file(client: TestClient):
    """POST /api/upload without a file should return 422 (validation error)."""
    resp = client.post("/api/upload", params={"entity_id": 1})
    assert resp.status_code == 422


# ---------- Transactions ----------


def test_transactions_list(client: TestClient):
    resp = client.get("/api/transactions", params={"entity_id": 1})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict) or isinstance(data, list)
