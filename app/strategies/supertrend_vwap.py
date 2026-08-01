import pandas as pd
from app.strategies.base import BaseStrategy, Signal, ActionType
from app.indicators.technical import calculate_all_indicators


class SupertrendVWAPStrategy(BaseStrategy):
    """
    Supertrend + VWAP Strategy (Gold standard for Indian Equities & Nifty/BankNifty).
    Combines Supertrend trend direction with institutional volume benchmark (VWAP).
    """

    def __init__(self, name: str = "Supertrend_VWAP_Indian"):
        super().__init__(name=name)

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Signal:
        if df.empty or len(df) < 20:
            return Signal(
                symbol=symbol,
                action=ActionType.HOLD,
                price=0.0,
                confidence=0.0,
                strategy_name=self.name,
                reason="Insufficient data for Supertrend/VWAP analysis."
            )

        data = calculate_all_indicators(df)
        curr = data.iloc[-1]
        prev = data.iloc[-2]

        price = float(curr["close"])
        vwap = float(curr["vwap"])
        st_dir = int(curr.get("supertrend_dir", 1))
        st_band = float(curr.get("supertrend", price))
        rsi = float(curr["rsi_14"])
        atr = float(curr["atr_14"]) if "atr_14" in curr else price * 0.015

        indicators_summary = {
            "price": round(price, 2),
            "vwap": round(vwap, 2),
            "supertrend_direction": "BULLISH" if st_dir == 1 else "BEARISH",
            "supertrend_band": round(st_band, 2),
            "rsi": round(rsi, 2),
            "atr": round(atr, 2),
        }

        # Bullish setup: Supertrend is Green (1), Price > VWAP, RSI healthy (50 to 72)
        if st_dir == 1 and price > vwap and 50 <= rsi <= 72:
            confidence = 0.85 if price > vwap * 1.002 else 0.72
            stop_loss = max(st_band, price - (1.5 * atr))
            take_profit = price + (3.0 * atr)
            return Signal(
                symbol=symbol,
                action=ActionType.BUY,
                price=price,
                confidence=confidence,
                strategy_name=self.name,
                stop_loss=stop_loss,
                take_profit=take_profit,
                reason=f"Bullish Indian Market confluence: Supertrend Green, Close ₹{price:.2f} > VWAP ₹{vwap:.2f}, RSI at {rsi:.1f}.",
                indicators=indicators_summary
            )

        # Bearish setup: Supertrend is Red (-1), Price < VWAP, RSI breakdown (< 48)
        if st_dir == -1 and price < vwap and rsi <= 48:
            confidence = 0.85 if price < vwap * 0.998 else 0.72
            stop_loss = min(st_band, price + (1.5 * atr))
            take_profit = price - (3.0 * atr)
            return Signal(
                symbol=symbol,
                action=ActionType.SELL,
                price=price,
                confidence=confidence,
                strategy_name=self.name,
                stop_loss=stop_loss,
                take_profit=take_profit,
                reason=f"Bearish Indian Market breakdown: Supertrend Red, Close ₹{price:.2f} < VWAP ₹{vwap:.2f}, RSI at {rsi:.1f}.",
                indicators=indicators_summary
            )

        return Signal(
            symbol=symbol,
            action=ActionType.HOLD,
            price=price,
            confidence=0.4,
            strategy_name=self.name,
            reason=f"Price near VWAP (₹{vwap:.2f}) without clear trend confluence. Standing aside.",
            indicators=indicators_summary
        )
