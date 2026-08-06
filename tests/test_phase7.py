import pytest
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)

def test_api_health_endpoint():
    """Verify GET /health returns 200 and healthy status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ["healthy", "paused"]
    assert "uptime_seconds" in data

def test_api_balance_endpoint():
    """Verify GET /api/balance returns initial capital and available margin."""
    response = client.get("/api/balance")
    assert response.status_code == 200
    data = response.json()
    assert "cash_balance" in data
    assert data["cash_balance"] == 30000.0

def test_api_system_status_endpoint():
    """Verify GET /api/system-status returns CPU and RAM memory usage."""
    response = client.get("/api/system-status")
    assert response.status_code == 200
    data = response.json()
    assert "ram_mb" in data
    assert data["ram_mb"] > 0

def test_api_pause_resume_endpoints():
    """Verify POST /api/pause and POST /api/resume toggles trading state."""
    pause_res = client.post("/api/pause")
    assert pause_res.status_code == 200
    assert pause_res.json()["status"] == "paused"

    resume_res = client.post("/api/resume")
    assert resume_res.status_code == 200
    assert resume_res.json()["status"] == "active"

def test_dashboard_route():
    """Verify GET /dashboard serves HTML UI."""
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "TradeMind-AI" in response.text
