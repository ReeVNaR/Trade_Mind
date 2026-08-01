import pytest
import pandas as pd
from app.backtesting.engine import BacktestEngine, BacktestResult
from app.strategies.supertrend_vwap import SupertrendVWAPStrategy
from app.data.fetcher import data_fetcher


@pytest.fixture
def indian_stock_data():
    return data_fetcher.fetch_ohlcv("RELIANCE.NS", period="60d", interval="1d")


def test_supertrend_vwap_strategy(indian_stock_data):
    strat = SupertrendVWAPStrategy()
    signal = strat.generate_signal(indian_stock_data, "RELIANCE.NS")
    
    assert signal.symbol == "RELIANCE.NS"
    assert signal.strategy_name == "Supertrend_VWAP_Indian"
    assert signal.price > 0
    assert signal.indicators is not None
    assert "vwap" in signal.indicators
    assert "supertrend_direction" in signal.indicators


def test_backtest_engine_execution(indian_stock_data):
    engine = BacktestEngine()
    result = engine.run_backtest(
        symbol="RELIANCE.NS",
        strategy_name="Supertrend_VWAP_Indian",
        initial_balance=2000.0,
        df=indian_stock_data
    )
    
    assert isinstance(result, BacktestResult)
    assert result.symbol == "RELIANCE.NS"
    assert result.initial_balance == 2000.0
    assert result.currency == "₹"
    assert len(result.equity_curve) > 0
    assert isinstance(result.total_return_percent, float)
    assert isinstance(result.win_rate_percent, float)
    assert isinstance(result.max_drawdown_percent, float)
