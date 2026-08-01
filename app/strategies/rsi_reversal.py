import pandas as pd
from app.strategies.base import BaseStrategy, Signal, ActionType
from app.indicators.technical import calculate_all_indicators


class RSIReversalStrategy(BaseStrategy):
    """
    Mean Reversion Strategy:
    Detects extreme RSI oversold/overbought conditions combined with Bollinger Band touches.
    """

    def __init__(self, name: str = "RSI_BB_Reversal"):
        super().__init__(name=name)

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Signal:
        if df.empty or len(df) < 20:
            return Signal(
                symbol=symbol,
                action=ActionType.HOLD,
                price=0.0,
                confidence=0.0,
                strategy_name=self.name,
                reason="Insufficient historical data for RSI/BB analysis."
            )

        data = calculate_all_indicators(df)
        curr = data.iloc[-1]

        price = float(curr["close"])
        rsi = float(curr["rsi_14"])
        bb_upper = float(curr["bb_upper"])
        bb_middle = float(curr["bb_middle"])
        bb_lower = float(curr["bb_lower"])
        bb_percent = float(curr["bb_percent"])
        atr = float(curr["atr_14"]) if "atr_14" in curr else price * 0.02

        indicators_summary = {
            "price": round(price, 2),
            "rsi": round(rsi, 2),
            "bb_lower": round(bb_lower, 2),
            "bb_middle": round(bb_middle, 2),
            "bb_upper": round(bb_upper, 2),
            "bb_percent": round(bb_percent, 2),
            "atr": round(atr, 2),
        }

        # Oversold Reversal (BUY)
        if rsi < 32 and (price <= bb_lower or bb_percent <= 0.1):
            confidence = min(0.95, 0.70 + (32 - rsi) * 0.015)
            stop_loss = min(price - (1.2 * atr), bb_lower - (0.5 * atr))
            take_profit = bb_middle
            return Signal(
                symbol=symbol,
                action=ActionType.BUY,
                price=price,
                confidence=confidence,
                strategy_name=self.name,
                stop_loss=stop_loss,
                take_profit=take_profit,
                reason=f"Oversold bounce detected: RSI at {rsi:.1f} <= 32 and price at lower Bollinger Band.",
                indicators=indicators_summary
            )

        # Overbought Reversal (SELL)
        if rsi > 68 and (price >= bb_upper or bb_percent >= 0.9):
            confidence = min(0.95, 0.70 + (rsi - 68) * 0.015)
            stop_loss = max(price + (1.2 * atr), bb_upper + (0.5 * atr))
            take_profit = bb_middle
            return Signal(
                symbol=symbol,
                action=ActionType.SELL,
                price=price,
                confidence=confidence,
                strategy_name=self.name,
                stop_loss=stop_loss,
                take_profit=take_profit,
                reason=f"Overbought exhaustion detected: RSI at {rsi:.1f} >= 68 and price at upper Bollinger Band.",
                indicators=indicators_summary
            )

        return Signal(
            symbol=symbol,
            action=ActionType.HOLD,
            price=price,
            confidence=0.5,
            strategy_name=self.name,
            reason=f"RSI in neutral range ({rsi:.1f}), within Bollinger Bands.",
            indicators=indicators_summary
        )
