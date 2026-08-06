import pytest
import os
from broker.paper_broker import PaperBroker
from risk_management.risk_manager import RiskManager
from telegram.notifier import TelegramNotifier
from orders.executor import OrderExecutor
from strategies.base import Signal
from database.connection import init_db, get_db_session
from database.models import Trade, Order

def test_telegram_notifier_formatting_and_dispatch():
    """Verify Telegram notifier formatting and dry-run/live dispatch."""
    notifier = TelegramNotifier()
    
    # Test message dry-run / send
    result = notifier.send_message_sync("🧪 *Test Alert from TradeMind-AI Automated Test Suite*")
    # Note: If token is valid, returns True; if offline/no token, returns False without crashing
    assert isinstance(result, bool)

    sig = Signal(
        symbol="NIFTY_22500_CE",
        direction="BUY",
        instrument_type="OPTION",
        option_type="CE",
        strike_price=22500.0,
        entry_price=120.0,
        stop_loss=100.0,
        target=160.0,
        confidence=88.0,
        strategy_name="TrendFollowing",
        reason="EMA Crossover with VWAP confirmation"
    )
    
    # Should not raise exception
    notifier.notify_signal(sig)
    notifier.notify_startup(capital=30000.0)
    notifier.notify_risk_event("CIRCUIT_TEST", "Test risk event notification")

def test_order_executor_full_lifecycle():
    """Verify OrderExecutor end-to-end signal execution, DB persistence, and trade closing."""
    init_db()

    broker = PaperBroker(initial_capital=30000.0)
    broker.connect()
    broker.set_mock_quote("NIFTY_22500_CE", 120.0)

    rm = RiskManager()
    notifier = TelegramNotifier()
    executor = OrderExecutor(broker=broker, risk_manager=rm, notifier=notifier)

    sig = Signal(
        symbol="NIFTY_22500_CE",
        direction="BUY",
        instrument_type="OPTION",
        option_type="CE",
        strike_price=22500.0,
        entry_price=120.0,
        stop_loss=100.0,
        target=160.0,
        confidence=88.0,
        strategy_name="TrendFollowing",
        reason="EMA Crossover test"
    )

    # 1. Execute Signal
    success, res_data, msg = executor.execute_signal(sig, ignore_time_check=True)
    assert success is True
    assert res_data["quantity"] == 65
    trade_id = res_data["trade_id"]

    # Verify Database Trade record
    with get_db_session() as session:
        saved_trade = session.query(Trade).filter_by(trade_id=trade_id).first()
        assert saved_trade is not None
        assert saved_trade.status == "OPEN"
        assert saved_trade.symbol == "NIFTY_22500_CE"
        assert saved_trade.quantity == 65

    # 2. Close Trade at Target Price 160.0 (Gain of ₹40 * 65 = ₹2,600)
    broker.set_mock_quote("NIFTY_22500_CE", 160.0)
    executor.close_trade(trade_id=trade_id, exit_price=160.0, reason="TARGET_HIT")

    # Verify Database updated status and PnL
    with get_db_session() as session:
        closed_trade = session.query(Trade).filter_by(trade_id=trade_id).first()
        assert closed_trade.status == "CLOSED"
        assert closed_trade.pnl > 2000.0
        assert closed_trade.exit_price >= 155.0

    # Verify RiskManager updated daily PnL
    assert rm.daily_pnl > 2000.0
    assert rm.daily_trade_count == 1
