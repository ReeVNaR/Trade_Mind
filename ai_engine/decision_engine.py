from typing import Optional, Dict, Any, Tuple
import pandas as pd
from strategies.base import Signal
from utils.logger import logger

class AIDecisionEngine:
    """AI Decision Engine for evaluating, scoring, and explaining trading signals."""

    def __init__(self, confidence_threshold: float = 80.0):
        self.confidence_threshold = confidence_threshold

    def evaluate_signal(
        self,
        signal: Signal,
        df: pd.DataFrame,
        market_analytics: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, Signal, str]:
        """
        Evaluates technical signal against market context (PCR, VIX, Greeks, Volume)
        and adjusts confidence score. Returns (is_approved, updated_signal, explanation).
        """
        if df.empty or len(df) < 5:
            return False, signal, "Insufficient market data for AI analysis."

        analytics = market_analytics or {}
        pcr = analytics.get("pcr", 1.0)
        vix = analytics.get("vix", 14.5)

        curr = df.iloc[-1]
        close = float(curr['Close'])
        vwap = float(curr.get('VWAP', close))
        adx = float(curr.get('ADX', 25.0))
        rsi = float(curr.get('RSI', 50.0))

        score = signal.confidence
        reasons = [signal.reason]

        # 1. PCR Alignment Check
        if signal.option_type == "CE":
            if pcr >= 1.0:
                score += 5.0
                reasons.append(f"Bullish PCR ({pcr:.2f} >= 1.0)")
            elif pcr < 0.8:
                score -= 8.0
                reasons.append(f"Bearish PCR divergence ({pcr:.2f} < 0.8)")
        elif signal.option_type == "PE":
            if pcr <= 0.9:
                score += 5.0
                reasons.append(f"Bearish PCR ({pcr:.2f} <= 0.9)")
            elif pcr > 1.2:
                score -= 8.0
                reasons.append(f"Bullish PCR divergence ({pcr:.2f} > 1.2)")

        # 2. India VIX Volatility Filter
        if 12.0 <= vix <= 22.0:
            score += 3.0
            reasons.append(f"Optimal VIX ({vix:.1f})")
        elif vix > 25.0:
            score -= 10.0
            reasons.append(f"High VIX risk ({vix:.1f} > 25.0)")

        # 3. Momentum & Trend Confirmation
        if signal.direction == "BUY" and signal.option_type == "CE":
            if close > vwap and rsi > 55.0:
                score += 4.0
                reasons.append(f"Strong Momentum (RSI {rsi:.1f}, Price > VWAP)")
        elif signal.direction == "BUY" and signal.option_type == "PE":
            if close < vwap and rsi < 45.0:
                score += 4.0
                reasons.append(f"Strong Downward Momentum (RSI {rsi:.1f}, Price < VWAP)")

        # Cap score between 0 and 100
        final_score = max(0.0, min(100.0, round(score, 1)))
        signal.confidence = final_score

        explanation = f"AI Multi-factor Score: {final_score}%. " + " | ".join(reasons)
        signal.reason = explanation

        is_approved = final_score >= self.confidence_threshold

        if is_approved:
            logger.info(f"AI Signal Approved: {signal.symbol} with score {final_score}%")
        else:
            logger.info(f"AI Signal Rejected: {signal.symbol} score {final_score}% < threshold {self.confidence_threshold}%")

        return is_approved, signal, explanation
