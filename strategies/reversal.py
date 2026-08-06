from typing import Optional, Dict, Any
import pandas as pd
from strategies.base import BaseStrategy, Signal
from config.settings import settings

class ReversalStrategy(BaseStrategy):
    """Mean Reversal Strategy using RSI extremes and Bollinger Bands."""

    def __init__(self):
        super().__init__(name="MeanReversal")

    def generate_signal(self, df: pd.DataFrame, market_context: Optional[Dict[str, Any]] = None) -> Optional[Signal]:
        if df.empty or len(df) < 15 or 'RSI' not in df.columns:
            return None

        curr = df.iloc[-1]
        close = float(curr['Close'])
        rsi = float(curr['RSI'])
        bb_lower = float(curr.get('BB_Lower', close * 0.98))
        bb_upper = float(curr.get('BB_Upper', close * 1.02))
        atr = float(curr.get('ATR', 30.0))

        # Bullish Reversal: RSI Oversold & price at/below lower BB
        if rsi <= 32.0 and close <= bb_lower * 1.002:
            step = settings.NIFTY_STRIKE_STEP
            strike = round(close / step) * step
            if settings.OPTION_STRIKE_TYPE == "ITM":
                strike -= step

            return Signal(
                symbol=f"NIFTY_{strike}_CE",
                direction="BUY",
                instrument_type="OPTION",
                option_type="CE",
                strike_price=strike,
                entry_price=close,
                stop_loss=round(close - (1.2 * atr), 2),
                target=round(curr.get('BB_Middle', close + 2 * atr), 2),
                confidence=80.0,
                strategy_name=self.name,
                reason=f"Bullish Reversal: RSI ({rsi:.1f}) Oversold + Price at Lower Bollinger Band (₹{bb_lower:.2f})"
            )

        # Bearish Reversal: RSI Overbought & price at/above upper BB
        if rsi >= 68.0 and close >= bb_upper * 0.998:
            step = settings.NIFTY_STRIKE_STEP
            strike = round(close / step) * step
            if settings.OPTION_STRIKE_TYPE == "ITM":
                strike += step

            return Signal(
                symbol=f"NIFTY_{strike}_PE",
                direction="BUY",
                instrument_type="OPTION",
                option_type="PE",
                strike_price=strike,
                entry_price=close,
                stop_loss=round(close + (1.2 * atr), 2),
                target=round(curr.get('BB_Middle', close - 2 * atr), 2),
                confidence=80.0,
                strategy_name=self.name,
                reason=f"Bearish Reversal: RSI ({rsi:.1f}) Overbought + Price at Upper Bollinger Band (₹{bb_upper:.2f})"
            )

        return None
