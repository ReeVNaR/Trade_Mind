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
    
    # 1. Execute BUY on NIFTY option contract
    symbol = "NIFTY 24800 CE"
    buy_result = engine.execute_buy(symbol=symbol, price=130.0, strategy="Supertrend_VWAP_Indian", bypass_circuit=True)
    assert buy_result is not None
    assert buy_result["symbol"] == symbol
    assert buy_result["side"] == "BUY"
    assert round(buy_result["entry_price"], 2) == round(130.0 * 1.0005, 2)
    
    summary = engine.get_portfolio_summary({symbol: 150.0})
    assert summary["open_positions_count"] == 1
    assert len(summary["positions"]) == 1
    assert summary["total_unrealized_pnl"] > 0  # Bought at ~130.065, current is 150

    # 2. Execute SELL
    sell_result = engine.execute_sell(symbol=symbol, price=150.0, reason="Take Profit Target Hit")
    assert sell_result is not None
    assert sell_result["symbol"] == symbol
    assert sell_result["status"] == "CLOSED"
    assert sell_result["realized_pnl"] > 0
    
    summary_after = engine.get_portfolio_summary()
    assert summary_after["open_positions_count"] == 0
    assert summary_after["total_realized_pnl"] > 0


def test_trailing_stop_loss_and_metrics():
    engine = PortfolioEngine()
    symbol = "NIFTY 24750 CE"
    
    # 1. Buy position
    engine.execute_buy(symbol=symbol, price=200.0, strategy="Supertrend_VWAP_Indian", bypass_circuit=True)
    
    # 2. Simulate price rally to ₹204.0 (+2.0% gain > 1.5% threshold, below TP ₹207.0) -> triggers TSL ratchet
    engine.check_stop_loss_take_profit({symbol: 204.0})
    pos = engine.get_position(symbol)
    assert pos is not None
    assert pos.highest_price == 204.0
    assert pos.trailing_stop is not None
    assert pos.trailing_stop >= 199.0
    
    # 3. Simulate pullback to ₹201.0 (hits trailing stop level ~₹202.03, locks gain above entry ₹200.10)
    closed = engine.check_stop_loss_take_profit({symbol: 201.0})
    assert len(closed) == 1
    assert closed[0]["symbol"] == symbol
    assert "Trailing Stop-Loss" in closed[0]["reason"]
    assert closed[0]["realized_pnl"] > 0

    
    # 4. Check performance metrics
    metrics = engine.get_trade_performance_metrics()
    assert metrics["total_trades"] >= 1
    assert metrics["winning_trades"] >= 1
    assert metrics["win_rate_percent"] == 100.0
    assert len(metrics["trades"]) >= 1


def test_eod_square_off():
    """Validates that 15:25 IST Auto Square-off closes all open intraday positions."""
    engine = PortfolioEngine()
    
    # 1. Open 2 positions
    engine.execute_buy(symbol="NIFTY 24800 CE", price=120.0, strategy="TestStrategy", bypass_circuit=True)
    engine.execute_buy(symbol="NIFTY 24700 PE", price=110.0, strategy="TestStrategy", bypass_circuit=True)
    
    summary = engine.get_portfolio_summary()
    assert summary["open_positions_count"] == 2
    
    # 2. Run EOD Square Off
    closed_trades = engine.run_eod_square_off(current_prices={"NIFTY 24800 CE": 130.0, "NIFTY 24700 PE": 125.0})
    assert len(closed_trades) == 2
    for t in closed_trades:
        assert t["status"] == "CLOSED"
        assert "Intraday EOD Auto Square-Off" in (t.get("reason") or "")
        
    summary_after = engine.get_portfolio_summary()
    assert summary_after["open_positions_count"] == 0
    assert summary_after["portfolio_value"] == 0.0


def test_pre_market_and_startup_reconciliation():
    """Validates self-healing DB reconciliation on startup or pre-market reset."""
    engine = PortfolioEngine()
    
    # Simulate open position left over in database
    engine.execute_buy(symbol="^NSEI", price=24500.0, strategy="TestStrategy", bypass_circuit=True)
    summary = engine.get_portfolio_summary()
    assert summary["open_positions_count"] == 1
    
    # Force reset reconciliation
    init_db(force_reset=True)
    
    summary_clean = engine.get_portfolio_summary()
    assert summary_clean["open_positions_count"] == 0
    assert summary_clean["initial_balance"] == 30000.0
    assert summary_clean["cash_balance"] == 30000.0
    assert summary_clean["total_equity"] == 30000.0
