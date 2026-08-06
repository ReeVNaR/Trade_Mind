from typing import List, Optional, Dict, Any
import pandas as pd
from strategies.base import BaseStrategy, Signal
from strategies.trend_following import TrendFollowingStrategy
from strategies.breakout import BreakoutStrategy
from strategies.reversal import ReversalStrategy
from utils.logger import logger

class StrategyEngine:
    """Strategy Engine managing multiple active trading strategies."""

    def __init__(self):
        self.strategies: List[BaseStrategy] = [
            TrendFollowingStrategy(),
            BreakoutStrategy(),
            ReversalStrategy()
        ]

    def evaluate(self, df: pd.DataFrame, market_context: Optional[Dict[str, Any]] = None) -> List[Signal]:
        """Evaluates all registered strategies and returns candidate signals."""
        signals: List[Signal] = []
        for strategy in self.strategies:
            try:
                sig = strategy.generate_signal(df, market_context)
                if sig:
                    signals.append(sig)
                    logger.info(f"Generated Signal [{strategy.name}]: {sig.direction} {sig.symbol} @ ₹{sig.entry_price:.2f}")
            except Exception as e:
                logger.error(f"Error evaluating strategy {strategy.name}: {e}")
        return signals
