import pytest
import os
import uuid
import datetime
from config.settings import settings
from utils.logger import setup_logger, SensitiveDataFilter
from database.connection import init_db, get_db_session
from database.models import (
    Trade, Order, LogRecord, DailyReport, RiskEvent, StrategyPerformance
)

def test_settings_configuration():
    """Verify that settings are correctly loaded with expected default/env values."""
    assert settings.PROJECT_NAME is not None
    assert settings.NIFTY_LOT_SIZE == 65
    assert settings.NIFTY_STRIKE_STEP == 50
    assert settings.INITIAL_BALANCE == 30000.0
    assert settings.MAX_DAILY_LOSS == 2000.0
    assert settings.MAX_DAILY_PROFIT == 4000.0

def test_logger_masking():
    """Verify that sensitive information (like Telegram Token) is masked in logs."""
    test_secret = "8701058368:AAFYPtJliB1KjwUiUqOvpz9vCIqFTho-nhI"
    filter_obj = SensitiveDataFilter(secrets_to_mask=[test_secret])
    
    class FakeRecord:
        def __init__(self, msg):
            self.msg = msg

    rec = FakeRecord(f"Connecting to Telegram with token {test_secret}")
    filter_obj.filter(rec)
    
    assert test_secret not in rec.msg
    assert "870..." in rec.msg or "masked" in rec.msg

def test_database_initialization_and_crud():
    """Verify database initialization and table CRUD operations."""
    init_db()
    
    trade_uid = f"TRD-{uuid.uuid4().hex[:8]}"
    order_uid = f"ORD-{uuid.uuid4().hex[:8]}"
    
    with get_db_session() as session:
        # Create Trade
        trade = Trade(
            trade_id=trade_uid,
            symbol="NIFTY24AUG22500CE",
            instrument_type="OPTION",
            option_type="CE",
            strike_price=22500.0,
            direction="BUY",
            entry_price=120.5,
            quantity=65,
            stop_loss=100.0,
            target=160.0,
            status="OPEN",
            strategy_name="TrendFollowing",
            confidence_score=88.5,
            reason="EMA Crossover with VWAP support"
        )
        session.add(trade)
        session.flush()

        # Create Order linked to Trade
        order = Order(
            order_id=order_uid,
            trade_id=trade_uid,
            broker_order_id="PAPER-12345",
            symbol="NIFTY24AUG22500CE",
            order_type="MARKET",
            direction="BUY",
            price=120.5,
            quantity=65,
            status="EXECUTED"
        )
        session.add(order)
        
        # Create Risk Event
        risk_event = RiskEvent(
            event_type="CIRCUIT_CHECK",
            message="Daily trades count: 1/4",
            severity="INFO"
        )
        session.add(risk_event)

    # Read back and verify persistence
    with get_db_session() as session:
        saved_trade = session.query(Trade).filter_by(trade_id=trade_uid).first()
        assert saved_trade is not None
        assert saved_trade.symbol == "NIFTY24AUG22500CE"
        assert saved_trade.confidence_score == 88.5
        assert len(saved_trade.orders) == 1
        assert saved_trade.orders[0].order_id == order_uid

        saved_event = session.query(RiskEvent).filter_by(event_type="CIRCUIT_CHECK").first()
        assert saved_event is not None
