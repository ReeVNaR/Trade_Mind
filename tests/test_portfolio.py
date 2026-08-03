import pytest
from app.database.session import init_db, SessionLocal
from app.database.models import Position, Trade, PortfolioSnapshot
from app.portfolio.engine import PortfolioEngine


@pytest.fixture(autouse=True)
def setup_database():
    init_db()
    db = SessionLocal()
    # Reset positions, trades, and snapshots for clean test
    db.query(Position).delete()
    db.query(Trade).delete()
    db.query(PortfolioSnapshot).delete()
    db.commit()
    db.close()


def test_portfolio_initial_balance():
    engine = PortfolioEngine()
    summary = engine.get_portfolio_summary()
    assert summary["initial_balance"] == 30000.0
    assert summary["cash_balance"] > 0
    assert summary["open_positions_count"] == 0
    assert summary["currency"] == "₹"


def test_portfolio_buy_and_sell():
    engine = PortfolioEngine()
    
    # 1. Execute BUY on Indian stock
    buy_result = engine.execute_buy(symbol="RELIANCE.NS", price=1300.0, strategy="Supertrend_VWAP_Indian")
    assert buy_result is not None
    assert buy_result["symbol"] == "RELIANCE.NS"
    assert buy_result["side"] == "BUY"
    assert round(buy_result["entry_price"], 2) == round(1300.0 * 1.0005, 2)
    
    summary = engine.get_portfolio_summary({"RELIANCE.NS": 1400.0})
    assert summary["open_positions_count"] == 1
    assert len(summary["positions"]) == 1
    assert summary["total_unrealized_pnl"] > 0  # Bought at ~1300.65, current is 1400

    # 2. Execute SELL
    sell_result = engine.execute_sell(symbol="RELIANCE.NS", price=1400.0, reason="Take Profit Target Hit")
    assert sell_result is not None
    assert sell_result["symbol"] == "RELIANCE.NS"
    assert sell_result["status"] == "CLOSED"
    assert sell_result["realized_pnl"] > 0
    
    summary_after = engine.get_portfolio_summary()
    assert summary_after["open_positions_count"] == 0
    assert summary_after["total_realized_pnl"] > 0


def test_trailing_stop_loss_and_metrics():
    engine = PortfolioEngine()
    
    # 1. Buy position
    engine.execute_buy(symbol="TCS.NS", price=2500.0, strategy="Supertrend_VWAP_Indian")
    
    # 2. Simulate price rally to ₹2560 (+2.4% gain > 1.5% threshold, below TP ₹2587.50) -> triggers TSL ratchet
    engine.check_stop_loss_take_profit({"TCS.NS": 2560.0})
    pos = engine.get_position("TCS.NS")
    assert pos is not None
    assert pos.highest_price == 2560.0
    assert pos.trailing_stop is not None
    assert pos.trailing_stop >= 2500.0  # Protected above entry price
    
    # 3. Simulate pullback to ₹2520 (hits trailing stop level of ~₹2521.26)
    closed = engine.check_stop_loss_take_profit({"TCS.NS": 2520.0})
    assert len(closed) == 1
    assert closed[0]["symbol"] == "TCS.NS"
    assert "Trailing Stop-Loss" in closed[0]["reason"]
    assert closed[0]["realized_pnl"] > 0  # Locked gain

    
    # 4. Check performance metrics
    metrics = engine.get_trade_performance_metrics()
    assert metrics["total_trades"] >= 1
    assert metrics["winning_trades"] >= 1
    assert metrics["win_rate_percent"] == 100.0
    assert metrics["total_realized_pnl"] > 0
    assert len(metrics["trades"]) >= 1
