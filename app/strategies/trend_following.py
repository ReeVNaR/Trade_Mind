import pandas as pd
from app.strategies.base import BaseStrategy, Signal, ActionType
from app.indicators.technical import calculate_all_indicators


class TrendFollowingStrategy(BaseStrategy):
    """
    Trend Following Strategy:
    Combines EMA (9/21) crossover, MACD histogram momentum, and EMA50 trend filter.
    """

    def __init__(self, name: str = "EMA_MACD_Trend"):
        super().__init__(name=name)

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Signal:
        if df.empty or len(df) < 25:
            return Signal(
                symbol=symbol,
                action=ActionType.HOLD,
                price=0.0,
                confidence=0.0,
                strategy_name=self.name,
                reason="Insufficient historical data for trend analysis."
            )

        # Ensure indicators are calculated
        data = calculate_all_indicators(df)
        curr = data.iloc[-1]
        prev = data.iloc[-2]

        price = float(curr["close"])
        ema9 = float(curr["ema_9"])
        ema21 = float(curr["ema_21"])
        ema50 = float(curr["ema_50"])
        ema200 = float(curr.get("ema_200", price))
        macd_hist = float(curr["macd_hist"])
        prev_macd_hist = float(prev["macd_hist"])
        atr = float(curr["atr_14"]) if "atr_14" in curr else price * 0.02
        rsi = float(curr["rsi_14"])
        vol_surge = float(curr.get("volume_surge_ratio", 1.0))

        indicators_summary = {
            "price": round(price, 2),
            "ema9": round(ema9, 2),
            "ema21": round(ema21, 2),
            "ema50": round(ema50, 2),
            "ema200": round(ema200, 2),
            "macd_hist": round(macd_hist, 4),
            "rsi": round(rsi, 2),
            "atr": round(atr, 2),
            "volume_surge": round(vol_surge, 2),
        }

        # Bullish conditions: Fast EMA above Slow EMA, MACD hist > 0, price above EMA50/200, healthy RSI
        bullish_score = 0.0
        if ema9 > ema21:
            bullish_score += 0.30
        if price > ema50:
            bullish_score += 0.20
        if macd_hist > 0:
            bullish_score += 0.15
            if macd_hist >= prev_macd_hist:
                bullish_score += 0.05
        if 40 <= rsi <= 75:
            bullish_score += 0.15
        if price > ema200:
            bullish_score += 0.10
        if vol_surge >= 1.05:
            bullish_score += 0.05

        # Bearish conditions: Fast EMA below Slow EMA, MACD hist < 0, price below EMA50/200, breakdown RSI
        bearish_score = 0.0
        if ema9 < ema21:
            bearish_score += 0.30
        if price < ema50:
            bearish_score += 0.20
        if macd_hist < 0:
            bearish_score += 0.15
            if macd_hist <= prev_macd_hist:
                bearish_score += 0.05
        if 25 <= rsi <= 60:
            bearish_score += 0.15
        if price < ema200:
            bearish_score += 0.10
        if vol_surge >= 1.05:
            bearish_score += 0.05

        if bullish_score >= 0.52 and bullish_score > bearish_score:
            stop_loss = price - (1.5 * atr)
            take_profit = price + (3.5 * atr)  # Expanded 1:2.3+ R:R target
            vol_note = f", Vol Surge {vol_surge:.1f}x" if vol_surge >= 1.1 else ""
            return Signal(
                symbol=symbol,
                action=ActionType.BUY,
                price=price,
                confidence=min(0.95, round(bullish_score, 2)),
                strategy_name=self.name,
                stop_loss=stop_loss,
                take_profit=take_profit,
                reason=f"Bullish trend confluence: EMA9 > EMA21, Price > EMA50, MACD positive (Score: {bullish_score:.2f}){vol_note}.",
                indicators=indicators_summary
            )

        if bearish_score >= 0.52 and bearish_score > bullish_score:
            stop_loss = price + (1.5 * atr)
            take_profit = price - (3.5 * atr)
            vol_note = f", Vol Surge {vol_surge:.1f}x" if vol_surge >= 1.1 else ""
            return Signal(
                symbol=symbol,
                action=ActionType.SELL,
                price=price,
                confidence=min(0.95, round(bearish_score, 2)),
                strategy_name=self.name,
                stop_loss=stop_loss,
                take_profit=take_profit,
                reason=f"Bearish trend breakdown: EMA9 < EMA21, Price < EMA50, MACD negative (Score: {bearish_score:.2f}){vol_note}.",
                indicators=indicators_summary
            )

        return Signal(
            symbol=symbol,
            action=ActionType.HOLD,
            price=price,
            confidence=max(bullish_score, bearish_score),
            strategy_name=self.name,
            reason=f"Neutral consolidation. Bullish score {bullish_score:.2f}, Bearish score {bearish_score:.2f}.",
            indicators=indicators_summary
        )

