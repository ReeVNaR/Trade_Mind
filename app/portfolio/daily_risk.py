"""
Daily Risk Management & Circuit Breaker Engine for TradeMind-AI.
Enforces:
1. Max 3 to 4 trades per day.
2. Max Daily Stop-Loss Circuit of -₹2,000 INR (10% capital protection).
3. Max Daily Profit Target Circuit of +₹4,000 INR (+20% profit locking).
"""

from datetime import datetime, date
from typing import Dict, Any, Tuple, Optional
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import Trade, Position
from app.database.session import SessionLocal
from app.utils.logger import logger

# IST Timezone
try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except Exception:
    import pytz
    IST = pytz.timezone("Asia/Kolkata")


class DailyRiskManager:
    """
    Monitors and enforces intraday trading circuits, trade frequency caps,
    and daily loss/profit limits on NIFTY F&O trades.
    """

    def __init__(self):
        self.max_daily_trades = settings.MAX_DAILY_TRADES
        self.max_daily_loss = settings.MAX_DAILY_LOSS
        self.max_daily_profit = settings.MAX_DAILY_PROFIT

    @staticmethod
    def get_today_date_ist() -> date:
        """Returns today's date in Indian Standard Time (IST)."""
        return datetime.now(IST).date()

    def get_daily_trade_stats(self, db: Optional[Session] = None) -> Dict[str, Any]:
        """Calculates today's trade count, realized PnL, and current unrealized PnL."""
        should_close = False
        if db is None:
            db = SessionLocal()
            should_close = True

        try:
            today_ist = self.get_today_date_ist()
            # Fetch all trades to filter by today's date
            all_trades = db.query(Trade).all()
            today_trades = []
            for t in all_trades:
                if t.created_at:
                    # Convert UTC or stored timestamp to date
                    t_date = t.created_at.date()
                    if t_date == today_ist:
                        today_trades.append(t)

            trades_today_count = len(today_trades)
            closed_today = [t for t in today_trades if t.status == "CLOSED"]
            daily_realized_pnl = sum((t.realized_pnl or 0.0) for t in closed_today)

            # Calculate open unrealized PnL
            open_positions = db.query(Position).all()
            daily_unrealized_pnl = sum((p.unrealized_pnl or 0.0) for p in open_positions)
            total_daily_pnl = daily_realized_pnl + daily_unrealized_pnl

            # Determine Circuit Status
            circuit_status = "ACTIVE"
            can_trade = True
            status_message = "Daily circuit active. Trading allowed within daily risk limits."

            if total_daily_pnl <= -self.max_daily_loss:
                circuit_status = "HALTED_MAX_LOSS"
                can_trade = False
                status_message = (
                    f"🛑 DAILY STOP-LOSS HIT: Total daily PnL is ₹{total_daily_pnl:,.2f} "
                    f"(Limit: -₹{self.max_daily_loss:,.2f}). Trading halted for the day to protect capital."
                )
            elif total_daily_pnl >= self.max_daily_profit:
                circuit_status = "HALTED_MAX_PROFIT"
                can_trade = False
                status_message = (
                    f"🎉 DAILY PROFIT TARGET HIT: Total daily PnL reached +₹{total_daily_pnl:,.2f} "
                    f"(Target: +₹{self.max_daily_profit:,.2f}). Gains secured, new trades paused for today."
                )
            elif trades_today_count >= self.max_daily_trades:
                circuit_status = "HALTED_MAX_TRADES"
                can_trade = False
                status_message = (
                    f"⚠️ DAILY TRADE CAP REACHED: {trades_today_count}/{self.max_daily_trades} trades taken today. "
                    f"No more trades allowed until next session."
                )

            remaining_loss = max(0.0, self.max_daily_loss + total_daily_pnl)
            remaining_target = max(0.0, self.max_daily_profit - total_daily_pnl)

            return {
                "date_ist": str(today_ist),
                "trades_today": trades_today_count,
                "max_daily_trades": self.max_daily_trades,
                "remaining_trades": max(0, self.max_daily_trades - trades_today_count),
                "daily_realized_pnl": round(daily_realized_pnl, 2),
                "daily_unrealized_pnl": round(daily_unrealized_pnl, 2),
                "total_daily_pnl": round(total_daily_pnl, 2),
                "max_daily_loss": round(self.max_daily_loss, 2),
                "max_daily_profit": round(self.max_daily_profit, 2),
                "loss_limit_remaining": round(remaining_loss, 2),
                "profit_target_remaining": round(remaining_target, 2),
                "circuit_status": circuit_status,
                "can_trade": can_trade,
                "status_message": status_message
            }
        finally:
            if should_close:
                db.close()

    def can_open_new_trade(self) -> Tuple[bool, str]:
        """
        Validates if a new trade can be executed under the daily risk & circuit rules.
        """
        stats = self.get_daily_trade_stats()
        if not stats["can_trade"]:
            logger.warning(f"Trade Execution Blocked by Daily Risk Circuit: {stats['status_message']}")
            return False, stats["status_message"]
        return True, "Approved"


daily_risk_manager = DailyRiskManager()
