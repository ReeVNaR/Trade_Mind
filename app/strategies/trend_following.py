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
        macd_hist = float(curr["macd_hist"])
        prev_macd_hist = float(prev["macd_hist"])
        atr = float(curr["atr_14"]) if "atr_14" in curr else price * 0.02
        rsi = float(curr["rsi_14"])

        indicators_summary = {
            "price": round(price, 2),
            "ema9": round(ema9, 2),
            "ema21": round(ema21, 2),
            "ema50": round(ema50, 2),
            "macd_hist": round(macd_hist, 4),
            "rsi": round(rsi, 2),
            "atr": round(atr, 2),
        }

        # Bullish conditions: Fast EMA above Slow EMA, MACD hist > 0 and increasing, price above EMA50, RSI not overbought
        bullish_score = 0
        if ema9 > ema21:
            bullish_score += 0.35
        if price > ema50:
            bullish_score += 0.25
        if macd_hist > 0 and macd_hist >= prev_macd_hist:
            bullish_score += 0.25
        if 45 <= rsi <= 70:
            bullish_score += 0.15

        # Bearish conditions: Fast EMA below Slow EMA, MACD hist < 0, price below EMA50
        bearish_score = 0
        if ema9 < ema21:
            bearish_score += 0.35
        if price < ema50:
            bearish_score += 0.25
        if macd_hist < 0 and macd_hist <= prev_macd_hist:
            bearish_score += 0.25
        if 30 <= rsi <= 55:
            bearish_score += 0.15

        if bullish_score >= 0.70:
            stop_loss = price - (1.5 * atr)
            take_profit = price + (3.0 * atr)
            return Signal(
                symbol=symbol,
                action=ActionType.BUY,
                price=price,
                confidence=bullish_score,
                strategy_name=self.name,
                stop_loss=stop_loss,
                take_profit=take_profit,
                reason=f"Bullish trend confluence: EMA9 > EMA21, MACD momentum positive, RSI at {rsi:.1f}.",
                indicators=indicators_summary
            )

        if bearish_score >= 0.70:
            stop_loss = price + (1.5 * atr)
            take_profit = price - (3.0 * atr)
            return Signal(
                symbol=symbol,
                action=ActionType.SELL,
                price=price,
                confidence=bearish_score,
                strategy_name=self.name,
                stop_loss=stop_loss,
                take_profit=take_profit,
                reason=f"Bearish trend breakdown: EMA9 < EMA21, MACD negative, price below EMA50.",
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
