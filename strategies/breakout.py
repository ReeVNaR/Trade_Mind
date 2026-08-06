from typing import Optional, Dict, Any
import pandas as pd
from strategies.base import BaseStrategy, Signal
from config.settings import settings

class BreakoutStrategy(BaseStrategy):
    """Breakout Strategy based on Opening Range / Previous High-Low Breakout and Volume Expansion."""

    def __init__(self):
        super().__init__(name="Breakout")

    def generate_signal(self, df: pd.DataFrame, market_context: Optional[Dict[str, Any]] = None) -> Optional[Signal]:
        if df.empty or len(df) < 20:
            return None

        curr = df.iloc[-1]
        close = float(curr['Close'])
        volume = float(curr['Volume'])
        avg_vol = float(df['Volume'].iloc[-20:].mean())
        atr = float(curr.get('ATR', 30.0))

        # Lookback range (e.g., last 15 candles)
        lookback_df = df.iloc[-16:-1]
        highest_high = float(lookback_df['High'].max())
        lowest_low = float(lookback_df['Low'].min())

        # Bullish Breakout above range high with volume surge
        if close > highest_high and volume > 1.3 * avg_vol:
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
                stop_loss=round(highest_high - (1.0 * atr), 2),
                target=round(close + (2.0 * atr), 2),
                confidence=82.0,
                strategy_name=self.name,
                reason=f"Breakout above range high (₹{highest_high:.2f}) with Volume Surge ({volume:.0f} > 1.3x avg)"
            )

        # Bearish Breakdown below range low with volume surge
        if close < lowest_low and volume > 1.3 * avg_vol:
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
                stop_loss=round(lowest_low + (1.0 * atr), 2),
                target=round(close - (2.0 * atr), 2),
                confidence=82.0,
                strategy_name=self.name,
                reason=f"Breakdown below range low (₹{lowest_low:.2f}) with Volume Surge ({volume:.0f} > 1.3x avg)"
            )

        return None
