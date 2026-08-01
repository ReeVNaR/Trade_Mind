import pytest
from app.database.session import init_db, SessionLocal
from app.database.models import Trade, Position, SignalLog, PortfolioSnapshot


def test_database_initialization():
    init_db()
    db = SessionLocal()
    
    snapshot = db.query(PortfolioSnapshot).first()
    assert snapshot is not None
    assert snapshot.cash_balance >= 0
    db.close()


def test_signal_log_creation():
    db = SessionLocal()
    # Clean previous test entries
    db.query(SignalLog).filter(SignalLog.symbol == "TEST_NSE_STOCK.NS").delete()
    db.commit()

    log = SignalLog(
        symbol="TEST_NSE_STOCK.NS",
        strategy="Supertrend_VWAP_Indian",
        action="BUY",
        confidence=0.88,
        price=2450.0,
        ai_reasoning="Strong confluence with VWAP in Indian session",
        ai_confirmed=True,
        executed=True
    )
    db.add(log)
    db.commit()
    
    retrieved = db.query(SignalLog).filter(SignalLog.symbol == "TEST_NSE_STOCK.NS").order_by(SignalLog.id.desc()).first()
    assert retrieved is not None
    assert retrieved.confidence == 0.88
    assert retrieved.ai_confirmed is True
    
    db.delete(retrieved)
    db.commit()
    db.close()
