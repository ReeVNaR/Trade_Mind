import pytest
import pandas as pd
import numpy as np
from market_data.indicators import TechnicalIndicators
from strategies.trend_following import TrendFollowingStrategy
from strategies.breakout import BreakoutStrategy
from strategies.reversal import ReversalStrategy
from strategies.option_strategies import StrategyEngine

def test_trend_following_signal_generation():
    """Verify Trend Following Strategy signal generation on bullish trend."""
    dates = pd.date_range("2026-08-06", periods=30, freq="5min")
    # Build sharp upward trend
    closes = [22000.0 + i * 15.0 for i in range(30)]
    df = pd.DataFrame({
        'Open': [c - 5 for c in closes],
        'High': [c + 10 for c in closes],
        'Low': [c - 10 for c in closes],
        'Close': closes,
        'Volume': [50000 + i * 1000 for i in range(30)]
    }, index=dates)

    df = TechnicalIndicators.calculate_all(df)

    strat = TrendFollowingStrategy()
    sig = strat.generate_signal(df)

    # Should generate Bullish CE signal
    if sig:
        assert sig.direction == "BUY"
        assert sig.option_type == "CE"
        assert sig.confidence >= 80.0
        assert "EMA9" in sig.reason

def test_breakout_strategy_signal_generation():
    """Verify Breakout Strategy signal generation on range high breakout."""
    dates = pd.date_range("2026-08-06", periods=25, freq="5min")
    # 24 sideways candles then 1 big breakout candle
    closes = [22500.0 + (i % 3) * 2 for i in range(24)] + [22650.0]
    highs = [c + 5 for c in closes[:-1]] + [22660.0]
    lows = [c - 5 for c in closes[:-1]] + [22640.0]
    volumes = [10000 for _ in range(24)] + [50000] # 5x volume surge

    df = pd.DataFrame({
        'Open': closes,
        'High': highs,
        'Low': lows,
        'Close': closes,
        'Volume': volumes
    }, index=dates)

    df = TechnicalIndicators.calculate_all(df)

    strat = BreakoutStrategy()
    sig = strat.generate_signal(df)

    assert sig is not None
    assert sig.direction == "BUY"
    assert sig.option_type == "CE"
    assert "Breakout" in sig.reason

def test_reversal_strategy_signal_generation():
    """Verify Reversal Strategy signal generation on RSI oversold conditions."""
    dates = pd.date_range("2026-08-06", periods=25, freq="5min")
    # Sharp downward fall causing RSI < 30
    closes = [22500.0 - i * 20.0 for i in range(25)]
    df = pd.DataFrame({
        'Open': closes,
        'High': [c + 2 for c in closes],
        'Low': [c - 10 for c in closes],
        'Close': closes,
        'Volume': [10000 for _ in range(25)]
    }, index=dates)

    df = TechnicalIndicators.calculate_all(df)

    strat = ReversalStrategy()
    sig = strat.generate_signal(df)

    if sig:
        assert sig.option_type == "CE" # Bullish reversal buy CE
        assert sig.confidence >= 80.0

def test_strategy_engine_runner():
    """Verify Strategy Engine evaluating multiple strategies."""
    engine = StrategyEngine()
    assert len(engine.strategies) == 3
