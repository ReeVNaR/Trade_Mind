"""
Trading strategies package for TradeMind-AI.
Contains strategy interfaces, signal structures, and concrete implementations.
"""
from .base import BaseStrategy, Signal, ActionType
from .trend_following import TrendFollowingStrategy
from .rsi_reversal import RSIReversalStrategy
from .supertrend_vwap import SupertrendVWAPStrategy

__all__ = [
    "BaseStrategy",
    "Signal",
    "ActionType",
    "TrendFollowingStrategy",
    "RSIReversalStrategy",
    "SupertrendVWAPStrategy"
]
