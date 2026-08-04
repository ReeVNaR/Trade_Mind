import pytest
import pandas as pd
import numpy as np
from app.indicators.technical import TechnicalIndicators, calculate_all_indicators
from app.data.fetcher import data_fetcher


@pytest.fixture
def nifty_ohlcv():
    return data_fetcher.fetch_ohlcv("^NSEI", period="30d", interval="1d")


def test_rsi_calculation(nifty_ohlcv):
    rsi = TechnicalIndicators.rsi(nifty_ohlcv["close"], period=14)
    assert isinstance(rsi, pd.Series)
    assert len(rsi) == len(nifty_ohlcv)
    assert (rsi.dropna() >= 0).all() and (rsi.dropna() <= 100).all()


def test_vwap_calculation(nifty_ohlcv):
    vwap = TechnicalIndicators.vwap(nifty_ohlcv)
    assert isinstance(vwap, pd.Series)
    assert len(vwap) == len(nifty_ohlcv)
    assert (vwap > 0).all()


def test_supertrend_calculation(nifty_ohlcv):
    st = TechnicalIndicators.supertrend(nifty_ohlcv)
    assert "supertrend" in st
    assert "supertrend_direction" in st
    assert len(st["supertrend"]) == len(nifty_ohlcv)


def test_ema_calculation(nifty_ohlcv):
    ema9 = TechnicalIndicators.ema(nifty_ohlcv["close"], span=9)
    assert isinstance(ema9, pd.Series)
    assert len(ema9) == len(nifty_ohlcv)
    assert not ema9.isna().all()


def test_macd_calculation(nifty_ohlcv):
    macd_res = TechnicalIndicators.macd(nifty_ohlcv["close"])
    assert "macd" in macd_res
    assert "macd_signal" in macd_res
    assert "macd_hist" in macd_res
    assert len(macd_res["macd"]) == len(nifty_ohlcv)


def test_bollinger_bands(nifty_ohlcv):
    bb = TechnicalIndicators.bollinger_bands(nifty_ohlcv["close"], window=20)
    assert "bb_upper" in bb
    assert "bb_middle" in bb
    assert "bb_lower" in bb
    assert (bb["bb_upper"].dropna() >= bb["bb_middle"].dropna()).all()


def test_atr_calculation(nifty_ohlcv):
    atr = TechnicalIndicators.atr(nifty_ohlcv, period=14)
    assert isinstance(atr, pd.Series)
    assert (atr.dropna() >= 0).all()


def test_calculate_all_indicators(nifty_ohlcv):
    df = calculate_all_indicators(nifty_ohlcv)
    expected_cols = ["ema_9", "ema_21", "ema_50", "rsi_14", "vwap", "macd", "macd_signal", "bb_upper", "bb_lower", "atr_14", "supertrend"]
    for col in expected_cols:
        assert col in df.columns, f"Expected column {col} in indicators DataFrame"
