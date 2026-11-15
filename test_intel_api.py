"""Tests for intelligence API endpoints and dashboard smoke (milestone M7)."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

import database
from main import app


@pytest.fixture
def client() -> TestClient:
    database.init_db()
    return TestClient(app)


def test_intel_health_endpoint(client: TestClient) -> None:
    res = client.get("/intel/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["offline_ready"] is True
    assert data["corpus_records"] >= 7


def test_intel_ask_endpoint(client: TestClient) -> None:
    res = client.post("/intel/ask", json={"query": "Compare old vs new regime", "user_id": 1})
    assert res.status_code == 200
    data = res.json()
    assert data["query"] == "Compare old vs new regime"
    assert "band" in data
    assert "confidence" in data
    assert "answer" in data
    assert len(data["numbers"]) >= 2


def test_intel_simulate_endpoint(client: TestClient) -> None:
    res = client.post("/intel/simulate", json={"gross_receipts": 6500000.0, "user_id": 1})
    assert res.status_code == 200
    data = res.json()
    assert data["band"] == "high"
    assert "simulated" in data["answer"].lower() or "turnover" in data["answer"].lower()


def test_intel_history_endpoints(client: TestClient) -> None:
    # 1. Ask a query to ensure an answer is persisted
    client.post("/intel/ask", json={"query": "What is the GST registration threshold?", "user_id": 1})

    # 2. List answers
    list_res = client.get("/intel/answers?user_id=1&limit=5")
    assert list_res.status_code == 200
    answers = list_res.json()
    assert len(answers) >= 1
    latest_id = answers[0]["id"]

    # 3. Retrieve by ID
    get_res = client.get(f"/intel/answer/{latest_id}")
    assert get_res.status_code == 200
    env = get_res.json()
    assert "GST" in env["query"] or "gst" in env["intent"]


def test_existing_smoke_routes_undisturbed(client: TestClient) -> None:
    # D4 acceptance: existing routes must stay green
    status_res = client.get("/status")
    assert status_res.status_code == 200

    dash_res = client.get("/")
    assert dash_res.status_code == 200
    assert "Deterministic Tax Intelligence" in dash_res.text

    ca_res = client.get("/api/ca/taxpayers")
    assert ca_res.status_code == 200
