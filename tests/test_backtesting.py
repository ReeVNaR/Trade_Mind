import pytest
import pandas as pd
from app.backtesting.engine import BacktestEngine, BacktestResult
from app.strategies.supertrend_vwap import SupertrendVWAPStrategy
from app.data.fetcher import data_fetcher


@pytest.fixture
def nifty_index_data():
    return data_fetcher.fetch_ohlcv("^NSEI", period="60d", interval="1d")


def test_supertrend_vwap_strategy(nifty_index_data):
    strat = SupertrendVWAPStrategy()
    signal = strat.generate_signal(nifty_index_data, "^NSEI")
    
    assert signal.symbol == "^NSEI"
    assert signal.strategy_name == "Supertrend_VWAP_Indian"
    assert signal.price > 0
    assert signal.indicators is not None
    assert "vwap" in signal.indicators
    assert "supertrend_direction" in signal.indicators


def test_backtest_engine_execution(nifty_index_data):
    engine = BacktestEngine()
    result = engine.run_backtest(
        symbol="^NSEI",
        strategy_name="Supertrend_VWAP_Indian",
        initial_balance=30000.0,
        df=nifty_index_data
    )
    
    assert isinstance(result, BacktestResult)
    assert result.symbol == "^NSEI"
    assert result.initial_balance == 30000.0
    assert result.currency == "₹"
    assert len(result.equity_curve) > 0
    assert isinstance(result.total_return_percent, float)
    assert isinstance(result.win_rate_percent, float)
    assert isinstance(result.max_drawdown_percent, float)
