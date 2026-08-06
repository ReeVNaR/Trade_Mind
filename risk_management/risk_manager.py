import datetime
from typing import Dict, Any, Tuple, Optional
from config.settings import settings
from utils.logger import logger
from database.connection import get_db_session
from database.models import RiskEvent

class RiskManager:
    """Intelligent Risk Management & Circuit Breaker Engine."""

    def __init__(self):
        self.max_daily_loss = settings.MAX_DAILY_LOSS # ₹2,000
        self.max_daily_profit = settings.MAX_DAILY_PROFIT # ₹4,000
        self.max_daily_trades = settings.MAX_DAILY_TRADES # 4
        self.consecutive_loss_limit = 2
        
        # State tracking for the trading session
        self.daily_pnl = 0.0
        self.daily_trade_count = 0
        self.consecutive_losses = 0
        self.circuit_breaker_active = False
        self.circuit_reason = ""

    def reset_daily_stats(self):
        """Resets daily circuit counters at start of trading day."""
        self.daily_pnl = 0.0
        self.daily_trade_count = 0
        self.consecutive_losses = 0
        self.circuit_breaker_active = False
        self.circuit_reason = ""
        logger.info("Daily Risk Management stats reset for new session.")

    def update_trade_result(self, pnl: float):
        """Updates session counters after a trade closes."""
        self.daily_pnl += pnl
        self.daily_trade_count += 1

        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        # Check circuit conditions
        if self.daily_pnl <= -self.max_daily_loss:
            self.circuit_breaker_active = True
            self.circuit_reason = f"Max Daily Loss limit hit (-₹{abs(self.daily_pnl):.2f} <= -₹{self.max_daily_loss:.2f})"
            self._log_risk_event("CIRCUIT_BREAKER", self.circuit_reason, "CRITICAL")

        elif self.daily_pnl >= self.max_daily_profit:
            self.circuit_breaker_active = True
            self.circuit_reason = f"Max Daily Profit target hit (₹{self.daily_pnl:.2f} >= ₹{self.max_daily_profit:.2f})"
            self._log_risk_event("PROFIT_LOCK", self.circuit_reason, "INFO")

        elif self.daily_trade_count >= self.max_daily_trades:
            self.circuit_breaker_active = True
            self.circuit_reason = f"Max Daily Trades limit reached ({self.daily_trade_count}/{self.max_daily_trades})"
            self._log_risk_event("TRADE_LIMIT", self.circuit_reason, "WARNING")

        elif self.consecutive_losses >= self.consecutive_loss_limit:
            self.circuit_breaker_active = True
            self.circuit_reason = f"Consecutive Losses limit hit ({self.consecutive_losses})"
            self._log_risk_event("CONSECUTIVE_LOSSES", self.circuit_reason, "WARNING")

    def can_trade(self, available_margin: float, ignore_time_check: bool = False) -> Tuple[bool, str]:
        """Validates whether a new trade is allowed under risk parameters."""
        if self.circuit_breaker_active:
            return False, f"Circuit Breaker Active: {self.circuit_reason}"

        if self.daily_trade_count >= self.max_daily_trades:
            return False, f"Max daily trades limit reached ({self.daily_trade_count}/{self.max_daily_trades})"

        if available_margin < 1000.0:
            return False, f"Insufficient available margin (₹{available_margin:.2f} < ₹1,000)"

        # Check time-based cutoff (no new trades after 3:15 PM IST)
        if not ignore_time_check:
            now_time = datetime.datetime.now().time()
            cutoff_time = datetime.time(15, 15)
            if now_time > cutoff_time:
                return False, "Market closing soon (past 3:15 PM IST)"

        return True, "Trading Allowed"

    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss: float,
        available_margin: float,
        lot_size: int = None
    ) -> int:
        """
        Calculates optimal position quantity in NIFTY lot multiples (e.g. 65 shares per lot).
        Ensures max capital allocation ratio is respected.
        """
        lot_size = lot_size or settings.NIFTY_LOT_SIZE # 65
        max_capital_to_risk = available_margin * settings.MAX_POSITION_SIZE_RATIO # 35% of capital

        cost_per_lot = entry_price * lot_size
        if cost_per_lot <= 0 or cost_per_lot > max_capital_to_risk:
            # If 1 lot exceeds max allocation, check if single lot can still be afforded safely
            if cost_per_lot <= available_margin:
                return lot_size
            return 0

        num_lots = int(max_capital_to_risk // cost_per_lot)
        num_lots = max(1, num_lots) # Minimum 1 lot
        return num_lots * lot_size

    def update_trailing_stop_loss(
        self,
        entry_price: float,
        current_price: float,
        current_sl: float,
        direction: str = "BUY"
    ) -> float:
        """Dynamic Trailing Stop Loss logic based on price movement."""
        if direction == "BUY":
            profit = current_price - entry_price
            if profit > 0:
                # Trail SL upward by half the profit gain
                new_sl = max(current_sl, entry_price + (profit * 0.5))
                return round(new_sl, 2)
        else:
            profit = entry_price - current_price
            if profit > 0:
                new_sl = min(current_sl, entry_price - (profit * 0.5))
                return round(new_sl, 2)

        return current_sl

    def _log_risk_event(self, event_type: str, message: str, severity: str = "WARNING"):
        """Logs risk event to database and console."""
        logger.warning(f"Risk Manager Alert [{event_type}]: {message}")
        try:
            with get_db_session() as session:
                event = RiskEvent(
                    event_type=event_type,
                    message=message,
                    severity=severity
                )
                session.add(event)
        except Exception as e:
            logger.error(f"Failed to log risk event to DB: {e}")
