import pytest
import pandas as pd
from app.strategies.trend_following import TrendFollowingStrategy
from app.strategies.rsi_reversal import RSIReversalStrategy
from app.strategies.supertrend_vwap import SupertrendVWAPStrategy
from app.strategies.base import ActionType
from app.data.fetcher import data_fetcher


@pytest.fixture
def nifty_index_df():
    # Fetch real live historical OHLCV candles for NIFTY 50 Index from NSE
    return data_fetcher.fetch_ohlcv("^NSEI", period="30d", interval="1d")


def test_trend_following_strategy_nifty(nifty_index_df):
    strategy = TrendFollowingStrategy()
    signal = strategy.generate_signal(nifty_index_df, "^NSEI")
    
    assert signal.symbol == "^NSEI"
    assert signal.action in [ActionType.BUY, ActionType.SELL, ActionType.HOLD]
    assert signal.strategy_name == "EMA_MACD_Trend"
    assert signal.confidence >= 0.0
    assert signal.price > 0.0


def test_rsi_reversal_strategy_nifty(nifty_index_df):
    strategy = RSIReversalStrategy()
    signal = strategy.generate_signal(nifty_index_df, "^NSEI")
    
    assert signal.symbol == "^NSEI"
    assert signal.action in [ActionType.BUY, ActionType.SELL, ActionType.HOLD]
    assert signal.strategy_name == "RSI_BB_Reversal"
    assert signal.confidence >= 0.0


def test_supertrend_vwap_strategy_nifty(nifty_index_df):
    strategy = SupertrendVWAPStrategy()
    signal = strategy.generate_signal(nifty_index_df, "^NSEI")
    
    assert signal.symbol == "^NSEI"
    assert signal.action in [ActionType.BUY, ActionType.SELL, ActionType.HOLD]
    assert signal.strategy_name == "Supertrend_VWAP_Indian"
    assert "vwap" in signal.indicators
    assert "supertrend_direction" in signal.indicators
