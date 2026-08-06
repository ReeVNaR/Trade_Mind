import pytest
import pandas as pd
from risk_management.risk_manager import RiskManager
from ai_engine.decision_engine import AIDecisionEngine
from strategies.base import Signal
from market_data.indicators import TechnicalIndicators

def test_risk_manager_initial_state_and_position_sizing():
    """Verify RiskManager initial state and lot size calculation."""
    rm = RiskManager()
    can_trade, reason = rm.can_trade(available_margin=30000.0, ignore_time_check=True)
    assert can_trade is True

    # Check position sizing: 35% of ₹30,000 = ₹10,500. Entry = ₹100. Cost/lot (65 shares) = ₹6,500.
    # Should recommend 1 lot = 65 shares.
    qty = rm.calculate_position_size(entry_price=100.0, stop_loss=80.0, available_margin=30000.0)
    assert qty == 65

def test_risk_manager_circuit_breaker():
    """Verify RiskManager circuit breaker halts trading after max daily loss."""
    rm = RiskManager()
    rm.max_daily_loss = 2000.0

    # Simulate losing trade of ₹2,100
    rm.update_trade_result(pnl=-2100.0)

    assert rm.circuit_breaker_active is True
    assert "Max Daily Loss" in rm.circuit_reason

    can_trade, reason = rm.can_trade(available_margin=30000.0, ignore_time_check=True)
    assert can_trade is False
    assert "Circuit Breaker Active" in reason

def test_risk_manager_trailing_stop_loss():
    """Verify Trailing Stop Loss adjustment."""
    rm = RiskManager()
    entry = 100.0
    initial_sl = 80.0
    
    # Price rises to 120 (₹20 gain). New SL should trail to 100 + (20 * 0.5) = 110.0
    new_sl = rm.update_trailing_stop_loss(entry_price=entry, current_price=120.0, current_sl=initial_sl, direction="BUY")
    assert new_sl == 110.0

def test_ai_decision_engine_approval_and_rejection():
    """Verify AI Decision Engine confidence scoring and threshold filtering."""
    engine = AIDecisionEngine(confidence_threshold=80.0)

    dates = pd.date_range("2026-08-06", periods=20, freq="5min")
    closes = [22500.0 + i * 5 for i in range(20)]
    df = pd.DataFrame({
        'Open': closes,
        'High': [c + 5 for c in closes],
        'Low': [c - 5 for c in closes],
        'Close': closes,
        'Volume': [20000 for _ in range(20)]
    }, index=dates)
    df = TechnicalIndicators.calculate_all(df)

    sig = Signal(
        symbol="NIFTY_22500_CE",
        direction="BUY",
        instrument_type="OPTION",
        option_type="CE",
        strike_price=22500.0,
        entry_price=22500.0,
        stop_loss=22400.0,
        target=22700.0,
        confidence=82.0,
        strategy_name="TrendFollowing",
        reason="EMA Crossover"
    )

    # 1. Evaluate with favorable PCR (1.15) and normal VIX (14.5)
    approved, updated_sig, explanation = engine.evaluate_signal(sig, df, {"pcr": 1.15, "vix": 14.5})
    assert approved is True
    assert updated_sig.confidence >= 85.0
    assert "AI Multi-factor Score" in explanation

    # 2. Evaluate with unfavorable High VIX (30.0) causing rejection
    sig_low = Signal(
        symbol="NIFTY_22500_CE",
        direction="BUY",
        instrument_type="OPTION",
        option_type="CE",
        strike_price=22500.0,
        entry_price=22500.0,
        stop_loss=22400.0,
        target=22700.0,
        confidence=80.0,
        strategy_name="TrendFollowing",
        reason="EMA Crossover"
    )
    approved_rej, updated_sig_rej, explanation_rej = engine.evaluate_signal(sig_low, df, {"pcr": 0.7, "vix": 30.0})
    assert approved_rej is False
    assert updated_sig_rej.confidence < 80.0
