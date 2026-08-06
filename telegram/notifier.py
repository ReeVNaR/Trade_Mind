import httpx
import asyncio
import datetime
from typing import Dict, Any, Optional
from config.settings import settings
from utils.logger import logger

class TelegramNotifier:
    """Sends rich formatted notifications to Telegram channel/user."""

    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None):
        self.token = token or settings.TELEGRAM_TOKEN
        self.chat_id = chat_id or settings.CHAT_ID
        self.api_url = f"https://api.telegram.org/bot{self.token}/sendMessage" if self.token else None

    def send_message_sync(self, text: str) -> bool:
        """Sends synchronous text message via HTTP POST."""
        if not self.api_url or not self.chat_id:
            logger.warning("Telegram token/chat_id missing. Logging alert to console instead:")
            logger.info(f"[TELEGRAM DISPATCH]\n{text}")
            return False

        try:
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "Markdown"
            }
            resp = httpx.post(self.api_url, json=payload, timeout=5.0)
            if resp.status_code == 200:
                logger.info("Telegram notification sent successfully.")
                return True
            else:
                logger.error(f"Failed to send Telegram message: {resp.status_code} - {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Error sending Telegram message: {e}")
            return False

    def notify_startup(self, capital: float, mode: str = "Paper Trading"):
        """Startup alert."""
        text = (
            f"🚀 *{settings.PROJECT_NAME} Started*\n\n"
            f"🔹 *Mode*: {mode}\n"
            f"💰 *Capital*: ₹{capital:,.2f}\n"
            f"🎯 *Max Daily Loss*: ₹{settings.MAX_DAILY_LOSS:,.2f}\n"
            f"🏆 *Max Daily Profit*: ₹{settings.MAX_DAILY_PROFIT:,.2f}\n"
            f"⏰ *Time*: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        self.send_message_sync(text)

    def notify_signal(self, signal: Any):
        """Trade signal alert."""
        text = (
            f"📢 *NEW TRADE SIGNAL*\n\n"
            f"⚡ *Strategy*: {signal.strategy_name}\n"
            f"📈 *Instrument*: `{signal.symbol}` ({signal.option_type})\n"
            f"🎯 *Direction*: {signal.direction}\n"
            f"💵 *Entry*: ₹{signal.entry_price:.2f}\n"
            f"🛑 *Stop Loss*: ₹{signal.stop_loss:.2f}\n"
            f"🎯 *Target*: ₹{signal.target:.2f}\n"
            f"🤖 *AI Confidence*: *{signal.confidence}%*\n\n"
            f"💡 *Reason*: {signal.reason}"
        )
        self.send_message_sync(text)

    def notify_order_execution(self, order: Dict[str, Any]):
        """Order execution alert."""
        text = (
            f"✅ *ORDER EXECUTED*\n\n"
            f"🆔 *Order ID*: `{order['order_id']}`\n"
            f"📊 *Symbol*: `{order['symbol']}`\n"
            f"🔄 *Type*: {order['direction']} {order['quantity']} qty\n"
            f"💵 *Fill Price*: ₹{order.get('fill_price', 0.0):.2f}\n"
            f"⏰ *Executed At*: {order.get('executed_at', '')}"
        )
        self.send_message_sync(text)

    def notify_risk_event(self, event_type: str, message: str):
        """Risk circuit event alert."""
        text = (
            f"🚨 *RISK CIRCUIT EVENT*\n\n"
            f"⚠️ *Type*: {event_type}\n"
            f"📝 *Message*: {message}\n"
            f"⏰ *Time*: {datetime.datetime.now().strftime('%H:%M:%S')}"
        )
        self.send_message_sync(text)

    def notify_daily_report(self, report: Dict[str, Any]):
        """End-of-day summary report alert."""
        text = (
            f"📊 *DAILY TRADING SUMMARY REPORT*\n\n"
            f"📅 *Date*: {report.get('date')}\n"
            f"🔢 *Total Trades*: {report.get('total_trades', 0)}\n"
            f"✅ *Wins*: {report.get('wins', 0)} | ❌ *Losses*: {report.get('losses', 0)}\n"
            f"🎯 *Win Rate*: {report.get('win_rate', 0.0):.1f}%\n"
            f"💵 *Net PnL*: *₹{report.get('net_pnl', 0.0):,.2f}*\n"
            f"📈 *ROI*: {report.get('roi_percent', 0.0):.2f}%"
        )
        self.send_message_sync(text)
