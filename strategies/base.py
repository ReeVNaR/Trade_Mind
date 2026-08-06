from dataclasses import dataclass
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
import pandas as pd

@dataclass
class Signal:
    """Normalized Trade Signal representation."""
    symbol: str
    direction: str # BUY / SELL
    instrument_type: str # OPTION / FUTURES / SPOT
    option_type: Optional[str] # CE / PE / None
    strike_price: Optional[float]
    entry_price: float
    stop_loss: float
    target: float
    confidence: float # 0 - 100
    strategy_name: str
    reason: str
    metadata: Optional[Dict[str, Any]] = None

class BaseStrategy(ABC):
    """Abstract Base Class for all trading strategies."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame, market_context: Optional[Dict[str, Any]] = None) -> Optional[Signal]:
        """Analyzes OHLCV dataframe with calculated indicators and returns Signal if conditions are met."""
        pass
