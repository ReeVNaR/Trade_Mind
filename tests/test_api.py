import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_healthcheck_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "TradeMind-AI"

    response_z = client.get("/healthz")
    assert response_z.status_code == 200


def test_dashboard_endpoint(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "TradeMind AI" in response.text
    assert "₹" in response.text
    assert "NSE" in response.text


def test_status_endpoint(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert data["currency"] == "₹"
    assert data["currency_code"] == "INR"
    assert "NSE" in data["market"]
    assert "market_status_ist" in data
    assert data["initial_balance"] == 30000.0


def test_indian_stocks_endpoint(client):
    response = client.get("/api/indian-stocks")
    assert response.status_code == 200
    stocks = response.json()
    assert isinstance(stocks, list)
    assert len(stocks) >= 10
    symbols = [s["symbol"] for s in stocks]
    assert "RELIANCE.NS" in symbols
    assert "TCS.NS" in symbols


def test_trace_live_indian_stock(client):
    response = client.get("/api/trace/RELIANCE.NS")
    assert response.status_code == 200
    data = response.json()
    assert "trace" in data
    assert data["trace"]["symbol"] == "RELIANCE.NS"
    assert data["trace"]["current_price"] > 0
    assert data["trace"]["currency"] == "₹"
    assert "technical_indicators" in data
    assert "vwap" in data["technical_indicators"]
    assert "supertrend_direction" in data["technical_indicators"]


def test_reject_non_indian_stock(client):
    # Non-Indian or crypto symbol must be rejected
    response = client.get("/api/trace/AAPL")
    # AAPL is not an Indian stock -> returns 404 or 400
    assert response.status_code in [400, 404]


def test_portfolio_endpoint(client):
    response = client.get("/api/portfolio")
    assert response.status_code == 200
    data = response.json()
    assert "cash_balance" in data
    assert "total_equity" in data
    assert "positions" in data
    assert data["currency"] == "₹"


def test_backtest_endpoint(client):
    response = client.post("/api/backtest", json={
        "symbol": "RELIANCE.NS",
        "strategy_name": "Supertrend_VWAP_Indian",
        "period": "30d",
        "interval": "1d",
        "initial_balance": 2000.0
    })
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "RELIANCE.NS"
    assert "total_return_percent" in data
    assert "win_rate_percent" in data
    assert data["currency"] == "₹"


def test_trades_history_endpoint(client):
    response = client.get("/api/trades/history")
    assert response.status_code == 200
    data = response.json()
    assert "win_rate_percent" in data
    assert "profit_factor" in data
    assert "total_realized_pnl" in data
    assert "trades" in data
    assert data["currency"] == "₹"


def test_confirm_setup_endpoint(client):
    response = client.get("/api/confirm-setup/RELIANCE.NS")
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "RELIANCE.NS"
    assert "confidence_percent" in data
    assert "checklist" in data
    assert len(data["checklist"]) >= 5
    assert "risk_reward_ratio" in data
    assert "projected_stop_loss" in data
    assert "projected_take_profit" in data

