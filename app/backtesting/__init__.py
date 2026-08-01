"""
Backtesting engine package for TradeMind-AI.
Provides historical simulation, performance metrics (CAGR, Sharpe, Drawdown, Win Rate), and trade logs.
"""
from .engine import BacktestEngine, BacktestResult, backtest_engine

__all__ = ["BacktestEngine", "BacktestResult", "backtest_engine"]
