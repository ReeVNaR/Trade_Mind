from typing import Optional, Dict, Any
import pandas as pd
from strategies.base import BaseStrategy, Signal
from config.settings import settings

class TrendFollowingStrategy(BaseStrategy):
    """Trend Following Strategy using EMA Crossover, VWAP, Supertrend, and ADX."""

    def __init__(self):
        super().__init__(name="TrendFollowing")

    def generate_signal(self, df: pd.DataFrame, market_context: Optional[Dict[str, Any]] = None) -> Optional[Signal]:
        if df.empty or len(df) < 5 or 'EMA9' not in df.columns:
            return None

        curr = df.iloc[-1]
        prev = df.iloc[-2]

        close = float(curr['Close'])
        vwap = float(curr['VWAP'])
        supertrend_dir = int(curr.get('Supertrend_Direction', 1))
        adx = float(curr.get('ADX', 25.0))
        atr = float(curr.get('ATR', 30.0))

        # Check for Bullish Trend Crossover
        ema_bullish_cross = (prev['EMA9'] <= prev['EMA20']) and (curr['EMA9'] > curr['EMA20'])
        if ema_bullish_cross and close > vwap and supertrend_dir == 1 and adx >= 20.0:
            # Bullish: Buy ITM/ATM Call Option
            step = settings.NIFTY_STRIKE_STEP
            strike = round(close / step) * step
            if settings.OPTION_STRIKE_TYPE == "ITM":
                strike -= step # ITM Call

            stop_loss = round(close - (1.5 * atr), 2)
            target = round(close + (2.5 * atr), 2)
            
            return Signal(
                symbol=f"NIFTY_{strike}_CE",
                direction="BUY",
                instrument_type="OPTION",
                option_type="CE",
                strike_price=strike,
                entry_price=close,
                stop_loss=stop_loss,
                target=target,
                confidence=85.0,
                strategy_name=self.name,
                reason=f"EMA9 crossed EMA20 up, Price (₹{close:.2f}) > VWAP (₹{vwap:.2f}), Supertrend Bullish, ADX ({adx:.1f}) > 20"
            )

        # Check for Bearish Trend Crossover
        ema_bearish_cross = (prev['EMA9'] >= prev['EMA20']) and (curr['EMA9'] < curr['EMA20'])
        if ema_bearish_cross and close < vwap and supertrend_dir == -1 and adx >= 20.0:
            # Bearish: Buy ITM/ATM Put Option
            step = settings.NIFTY_STRIKE_STEP
            strike = round(close / step) * step
            if settings.OPTION_STRIKE_TYPE == "ITM":
                strike += step # ITM Put

            stop_loss = round(close + (1.5 * atr), 2)
            target = round(close - (2.5 * atr), 2)

            return Signal(
                symbol=f"NIFTY_{strike}_PE",
                direction="BUY",
                instrument_type="OPTION",
                option_type="PE",
                strike_price=strike,
                entry_price=close,
                stop_loss=stop_loss,
                target=target,
                confidence=85.0,
                strategy_name=self.name,
                reason=f"EMA9 crossed EMA20 down, Price (₹{close:.2f}) < VWAP (₹{vwap:.2f}), Supertrend Bearish, ADX ({adx:.1f}) > 20"
            )

        return None
