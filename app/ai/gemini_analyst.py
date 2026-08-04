import json
from typing import Dict, Any, Optional
from dataclasses import dataclass
from app.config import settings
from app.strategies.base import Signal, ActionType
from app.utils.logger import logger

# Import Google Gemini SDK if available
try:
    import google.generativeai as genai
    HAS_GEMINI_LIB = True
except ImportError:
    HAS_GEMINI_LIB = False


@dataclass
class AIAnalysisResult:
    confirmed: bool
    confidence_score: float
    reasoning: str
    risk_level: str
    action_recommendation: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "confirmed": self.confirmed,
            "confidence_score": round(self.confidence_score, 2),
            "reasoning": self.reasoning,
            "risk_level": self.risk_level,
            "action_recommendation": self.action_recommendation,
        }


class GeminiAnalyst:
    """
    Analyzes NIFTY 50 Index & F&O derivatives signals using Google Gemini LLM reasoning.
    Validates technical setups against NIFTY trend, VWAP, Supertrend, RSI, ITM Option moneyness, and risk/reward.
    """

    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.model = None
        
        if self.api_key and HAS_GEMINI_LIB:
            try:
                genai.configure(api_key=self.api_key)
                self.model = genai.GenerativeModel("gemini-1.5-flash")
                logger.info("✅ Gemini AI Analyst initialized for NIFTY 50 F&O Markets.")
            except Exception as e:
                logger.error(f"Failed to initialize Gemini AI: {e}")
                self.model = None
        else:
            logger.info("ℹ️ No GEMINI_API_KEY provided. Using NIFTY 50 F&O Quantitative Rule-Based Analyst.")

    def analyze_signal(self, signal: Signal, market_context: Optional[Dict[str, Any]] = None) -> AIAnalysisResult:
        """Evaluates whether to confirm, veto, or adjust a trading signal."""
        if self.model:
            try:
                return self._call_gemini_api(signal, market_context)
            except Exception as e:
                logger.warning(f"Gemini API request failed: {e}. Falling back to quantitative engine.")
                return self._rule_based_analysis(signal, market_context)
        else:
            return self._rule_based_analysis(signal, market_context)

    def _call_gemini_api(self, signal: Signal, market_context: Optional[Dict[str, Any]]) -> AIAnalysisResult:
        """Sends structured market prompt to Gemini 1.5 Flash."""
        prompt = f"""
You are an expert Indian Derivatives Portfolio Manager specializing in NIFTY 50 Index Futures & In-The-Money (ITM) Options.
Evaluate the following trading signal:

Symbol: {signal.symbol} (NIFTY 50 Universe)
Proposed Action: {signal.action.value}
Index Spot / Premium Price: ₹{signal.price:,.2f} INR
Strategy Source: {signal.strategy_name}
Initial Strategy Confidence: {signal.confidence:.2f}
Strategy Reasoning: {signal.reason}
Technical Indicators: {json.dumps(signal.indicators or {})}
Market Context: {json.dumps(market_context or {})}

Evaluate whether this trade setup is high probability considering:
1. Confluence of Supertrend, VWAP, EMA, and RSI on NIFTY 50 Index.
2. In-The-Money (ITM) option delta protection, theta decay risk, and false breakout avoidance.
3. Strict daily circuit parameters (Max 4 trades/day, ₹2k max loss, ₹4k target).

Respond STRICTLY in valid JSON matching this schema:
{{
    "confirmed": true/false,
    "confidence_score": float (0.0 to 1.0),
    "reasoning": "2-3 concise sentences explaining the rationale with NIFTY index & option context",
    "risk_level": "LOW" | "MODERATE" | "HIGH",
    "action_recommendation": "BUY" | "SELL" | "HOLD"
}}
"""
        response = self.model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.2
            )
        )
        data = json.loads(response.text)
        return AIAnalysisResult(
            confirmed=bool(data.get("confirmed", True)),
            confidence_score=float(data.get("confidence_score", 0.75)),
            reasoning=str(data.get("reasoning", "Gemini confirmed signal based on NIFTY 50 technical setup.")),
            risk_level=str(data.get("risk_level", "MODERATE")),
            action_recommendation=str(data.get("action_recommendation", signal.action.value))
        )

    def _rule_based_analysis(self, signal: Signal, market_context: Optional[Dict[str, Any]]) -> AIAnalysisResult:
        """Fallback quantitative validation engine calibrated for NIFTY 50 Index volatility."""
        indicators = signal.indicators or {}
        rsi = indicators.get("rsi", 50.0)
        vwap = indicators.get("vwap", signal.price)
        st_dir = indicators.get("supertrend_direction", "BULLISH")

        confirmed = True
        risk = "MODERATE"
        confidence = signal.confidence

        if signal.action == ActionType.BUY:
            if rsi > 78:  # Overheated
                confirmed = False
                reason = f"VETO: NIFTY is overextended on RSI ({rsi:.1f}). Wait for pullback near VWAP (₹{vwap:,.2f})."
                risk = "HIGH"
                confidence = 0.35
            elif signal.price > vwap and st_dir == "BULLISH":
                confirmed = True
                reason = f"TradeMind AI Engine confirms high-probability bullish setup on NIFTY 50: Price is trading above VWAP (₹{vwap:,.2f}) with green Supertrend."
                risk = "LOW"
                confidence = min(0.92, signal.confidence + 0.1)
            else:
                confirmed = True
                reason = f"TradeMind AI Engine validates NIFTY trend momentum with controlled ITM option risk."
                risk = "MODERATE"

        elif signal.action == ActionType.SELL:
            if rsi < 22:
                confirmed = False
                reason = f"VETO: NIFTY is deeply oversold on RSI ({rsi:.1f}). Potential short squeeze risk."
                risk = "HIGH"
                confidence = 0.3
            else:
                confirmed = True
                reason = f"TradeMind AI Engine confirms bearish momentum or profit-taking condition for NIFTY."
                risk = "MODERATE"
        else:
            confirmed = False
            reason = f"NIFTY is in consolidation near VWAP (₹{vwap:,.2f}). Standing aside."
            risk = "LOW"

        return AIAnalysisResult(
            confirmed=confirmed,
            confidence_score=round(confidence, 2),
            reasoning=reason,
            risk_level=risk,
            action_recommendation=signal.action.value if confirmed else ActionType.HOLD.value
        )


gemini_analyst = GeminiAnalyst()
