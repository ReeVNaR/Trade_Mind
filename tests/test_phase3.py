import pytest
import pandas as pd
from market_data.fetcher import MarketDataFetcher
from market_data.indicators import TechnicalIndicators, OptionAnalytics

def test_technical_indicators_calculation():
    """Verify calculation of technical indicators on candles DataFrame."""
    fetcher = MarketDataFetcher()
    df = fetcher.generate_mock_candles(count=50, base_price=22500.0)

    assert not df.empty
    assert "EMA9" in df.columns
    assert "EMA20" in df.columns
    assert "EMA50" in df.columns
    assert "VWAP" in df.columns
    assert "RSI" in df.columns
    assert "MACD" in df.columns
    assert "ATR" in df.columns
    assert "Supertrend" in df.columns
    assert "ADX" in df.columns

    # Verify RSI range
    rsi_vals = df['RSI'].dropna()
    assert (rsi_vals >= 0).all() and (rsi_vals <= 100).all()

    # Verify Supertrend direction (-1 or 1)
    assert set(df['Supertrend_Direction'].unique()).issubset({-1, 1})

def test_option_analytics_pcr_and_max_pain():
    """Verify Put-Call Ratio and Max Pain calculations."""
    fetcher = MarketDataFetcher()
    analytics = fetcher.get_option_chain_analytics(spot_price=22500.0)

    assert analytics["spot_price"] == 22500.0
    assert analytics["atm_strike"] == 22500.0
    assert analytics["pcr"] > 0
    assert analytics["max_pain"] in [item["strike"] for item in analytics["chain"]]

def test_market_data_live_quote_fallback():
    """Verify live quote fetcher fallback behavior."""
    fetcher = MarketDataFetcher(symbol="^NSEI")
    quote = fetcher.get_live_quote()

    assert quote["symbol"] == "^NSEI"
    assert quote["ltp"] > 0
    assert quote["vix"] > 0
