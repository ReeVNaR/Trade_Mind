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
        vol_surge = float(curr.get("volume_surge_ratio", 1.0))
        ema50 = float(curr.get("ema_50", price))
        ema200 = float(curr.get("ema_200", price))

        indicators_summary = {
            "price": round(price, 2),
            "vwap": round(vwap, 2),
            "supertrend_direction": "BULLISH" if st_dir == 1 else "BEARISH",
            "supertrend_band": round(st_band, 2),
            "rsi": round(rsi, 2),
            "atr": round(atr, 2),
            "volume_surge": round(vol_surge, 2),
            "ema50": round(ema50, 2),
            "ema200": round(ema200, 2),
        }

        # High-Conviction Bullish Setup:
        # 1. Supertrend is Bullish Green (1)
        # 2. Price is trading firmly above VWAP
        # 3. RSI in healthy expansion zone (48 to 74)
        # 4. Long-term trend alignment (Price above EMA50 / EMA200)
        # 5. Volume surge bonus (higher confidence when volume >= 1.1x MA)
        if st_dir == 1 and price > vwap and 48 <= rsi <= 74:
            base_conf = 0.75
            if price > ema50:
                base_conf += 0.08
            if price > ema200:
                base_conf += 0.07
            if vol_surge >= 1.1:
                base_conf += 0.08

            confidence = min(0.95, base_conf)
            stop_loss = min(price - (0.5 * atr), max(st_band, price - (1.5 * atr)))
            take_profit = price + (3.5 * atr)  # Expanded 1:2.3+ R:R target
            
            vol_text = f", Volume Surge {vol_surge:.1f}x" if vol_surge >= 1.1 else ""
            return Signal(
                symbol=symbol,
                action=ActionType.BUY,
                price=price,
                confidence=confidence,
                strategy_name=self.name,
                stop_loss=stop_loss,
                take_profit=take_profit,
                reason=f"High-Profit Bullish Confluence: Supertrend Green, Close ₹{price:.2f} > VWAP ₹{vwap:.2f}, RSI {rsi:.1f}{vol_text}.",
                indicators=indicators_summary
            )

        # High-Conviction Bearish Setup:
        # Supertrend is Red (-1), Price < VWAP, RSI breakdown (< 48)
        if st_dir == -1 and price < vwap and rsi <= 48:
            base_conf = 0.75
            if price < ema50:
                base_conf += 0.08
            if price < ema200:
                base_conf += 0.07
            if vol_surge >= 1.1:
                base_conf += 0.08

            confidence = min(0.95, base_conf)
            stop_loss = max(price + (0.5 * atr), min(st_band, price + (1.5 * atr)))
            take_profit = price - (3.5 * atr)
            
            vol_text = f", Volume Surge {vol_surge:.1f}x" if vol_surge >= 1.1 else ""
            return Signal(
                symbol=symbol,
                action=ActionType.SELL,
                price=price,
                confidence=confidence,
                strategy_name=self.name,
                stop_loss=stop_loss,
                take_profit=take_profit,
                reason=f"High-Conviction Bearish Breakdown: Supertrend Red, Close ₹{price:.2f} < VWAP ₹{vwap:.2f}, RSI {rsi:.1f}{vol_text}.",
                indicators=indicators_summary
            )

        return Signal(
            symbol=symbol,
            action=ActionType.HOLD,
            price=price,
            confidence=0.4,
            strategy_name=self.name,
            reason=f"Consolidation near VWAP (₹{vwap:.2f}) without clear trend breakout confluence.",
            indicators=indicators_summary
        )

