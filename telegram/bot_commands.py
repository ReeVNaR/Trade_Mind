import httpx
import threading
import time
import datetime
from typing import Dict, Any, Optional
from config.settings import settings
from telegram.notifier import TelegramNotifier
from utils.logger import logger

class TelegramCommandHandler:
    """Listens for Telegram chat commands (/start, /status, /balance, /positions, /scan, /pause, /resume, /report)."""

    def __init__(self, scanner=None, broker=None, risk_manager=None):
        self.token = settings.TELEGRAM_TOKEN
        self.allowed_chat_id = str(settings.CHAT_ID) if settings.CHAT_ID else None
        self.notifier = TelegramNotifier()
        self.scanner = scanner
        self.broker = broker
        self.risk_manager = risk_manager
        self.offset = 0
        self.is_running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """Starts background Telegram command listener thread."""
        if not self.token:
            logger.warning("Telegram token missing. Command listener disabled.")
            return

        if self.is_running:
            return

        self.is_running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info("📲 Telegram Bot Command Listener started. Send /help in Telegram!")

    def stop(self):
        self.is_running = False

    def _poll_loop(self):
        """Long polling loop for Telegram updates."""
        url = f"https://api.telegram.org/bot{self.token}/getUpdates"
        
        while self.is_running:
            try:
                params = {"offset": self.offset, "timeout": 10}
                resp = httpx.get(url, params=params, timeout=12.0)
                
                if resp.status_code == 200:
                    data = resp.json()
                    for update in data.get("result", []):
                        self.offset = update["update_id"] + 1
                        self._handle_update(update)
            except Exception as e:
                logger.debug(f"Telegram polling error: {e}")

            time.sleep(2)

    def _handle_update(self, update: Dict[str, Any]):
        """Processes an incoming message update from Telegram."""
        message = update.get("message", {})
        text = message.get("text", "").strip()
        chat_id = str(message.get("chat", {}).get("id", ""))

        if not text or not text.startswith("/"):
            return

        # Security check: verify chat ID if configured
        if self.allowed_chat_id and chat_id != self.allowed_chat_id:
            logger.warning(f"Unauthorized Telegram command from chat_id {chat_id}")
            return

        cmd = text.split()[0].lower()
        logger.info(f"Received Telegram command: {cmd} from chat {chat_id}")

        if cmd in ["/start", "/help"]:
            self._cmd_help(chat_id)
        elif cmd == "/status":
            self._cmd_status(chat_id)
        elif cmd in ["/balance", "/capital"]:
            self._cmd_balance(chat_id)
        elif cmd == "/positions":
            self._cmd_positions(chat_id)
        elif cmd == "/orders":
            self._cmd_orders(chat_id)
        elif cmd == "/scan":
            self._cmd_scan(chat_id)
        elif cmd == "/pause":
            self._cmd_pause(chat_id)
        elif cmd == "/resume":
            self._cmd_resume(chat_id)
        elif cmd == "/report":
            self._cmd_report(chat_id)
        else:
            self.notifier.send_message_sync(
                "❓ *Unknown Command*\nSend `/help` to view available commands."
            )

    def _cmd_help(self, chat_id: str):
        msg = (
            "🤖 *TradeMind-AI Bot Telegram Commands*\n\n"
            "📊 */status* - Market status, NIFTY spot, VIX & scanner state\n"
            "💰 */balance* - Portfolio capital, available margin & PnL\n"
            "📈 */positions* - Active open Call/Put positions & live PnL\n"
            "📋 */orders* - Recent order execution history\n"
            "⚡ */scan* - Force immediate real-time market scan\n"
            "⏸️ */pause* - Pause automated trade execution\n"
            "▶️ */resume* - Resume automated trade execution\n"
            "📈 */report* - Today's PnL & win rate summary\n"
            "❓ */help* - Show command menu"
        )
        self.notifier.send_message_sync(msg)

    def _cmd_status(self, chat_id: str):
        spot = 22500.0
        vix = 14.5
        scanner_state = "UNKNOWN"
        
        if self.scanner:
            quote = self.scanner.fetcher.get_live_quote()
            spot = quote.get("ltp", 22500.0)
            vix = quote.get("vix", 14.5)
            scanner_state = "RUNNING 🟢" if self.scanner.is_running else "PAUSED 🔴"

        msg = (
            f"📊 *SYSTEM & MARKET STATUS*\n\n"
            f"📈 *NIFTY 50 Spot*: *₹{spot:,.2f}*\n"
            f"🌋 *India VIX*: *{vix:.2f}*\n"
            f"⚙️ *Scanner State*: {scanner_state}\n"
            f"⚙️ *Trading Mode*: *{settings.TRADING_MODE}*\n"
            f"⏰ *Server Time*: {datetime.datetime.now().strftime('%H:%M:%S IST')}"
        )
        self.notifier.send_message_sync(msg)

    def _cmd_balance(self, chat_id: str):
        if not self.broker:
            self.notifier.send_message_sync("⚠️ Broker not initialized.")
            return

        bal = self.broker.get_balance()
        msg = (
            f"💰 *ACCOUNT CAPITAL SUMMARY*\n\n"
            f"💵 *Total Portfolio*: *₹{bal['total_portfolio_value']:,.2f}*\n"
            f"💳 *Cash Balance*: ₹{bal['cash_balance']:,.2f}\n"
            f"🔒 *Used Margin*: ₹{bal['used_margin']:,.2f}\n"
            f"✅ *Available Margin*: ₹{bal['available_margin']:,.2f}\n"
            f"📈 *Realized PnL*: *₹{bal['realized_pnl']:,.2f}*\n"
            f"📊 *Unrealized PnL*: *₹{bal['unrealized_pnl']:,.2f}*"
        )
        self.notifier.send_message_sync(msg)

    def _cmd_positions(self, chat_id: str):
        if not self.broker:
            return

        positions = self.broker.get_positions()
        if not positions:
            self.notifier.send_message_sync("📈 *Active Positions*: None (No open positions)")
            return

        lines = ["📈 *ACTIVE OPEN POSITIONS*\n"]
        for p in positions:
            pnl_emoji = "🟢" if p["unrealized_pnl"] >= 0 else "🔴"
            lines.append(
                f"🔹 `{p['symbol']}`\n"
                f"   Qty: {p['quantity']} | Avg: ₹{p['average_price']:.2f} | LTP: ₹{p['ltp']:.2f}\n"
                f"   {pnl_emoji} PnL: *₹{p['unrealized_pnl']:,.2f}*\n"
            )
        self.notifier.send_message_sync("\n".join(lines))

    def _cmd_orders(self, chat_id: str):
        if not self.broker:
            return

        orders = self.broker.get_orders()[-5:] # Last 5 orders
        if not orders:
            self.notifier.send_message_sync("📋 *Orders*: No orders executed today.")
            return

        lines = ["📋 *RECENT EXECUTED ORDERS*\n"]
        for o in orders:
            lines.append(
                f"🔹 `{o['symbol']}` ({o['direction']} {o['quantity']} qty)\n"
                f"   Status: *{o['status']}* | Fill Price: ₹{o.get('fill_price', 0.0):.2f}\n"
            )
        self.notifier.send_message_sync("\n".join(lines))

    def _cmd_scan(self, chat_id: str):
        self.notifier.send_message_sync("⚡ *Executing Real-Time Market Scan...*")
        if self.scanner:
            summary = self.scanner.run_single_scan()
            spot = summary.get("spot_price", 0.0)
            vix = summary.get("vix", 0.0)
            candidates = summary.get("candidates_count", 0)
            msg = (
                f"✅ *Market Scan Completed*\n\n"
                f"📈 *NIFTY Spot*: ₹{spot:,.2f}\n"
                f"🌋 *VIX*: {vix:.2f}\n"
                f"🔍 *Candidate Signals Evaluated*: {candidates}"
            )
            self.notifier.send_message_sync(msg)
        else:
            self.notifier.send_message_sync("⚠️ Scanner instance not attached.")

    def _cmd_pause(self, chat_id: str):
        if self.scanner:
            self.scanner.stop()
        self.notifier.send_message_sync("⏸️ *Automated Trading Execution PAUSED.*")

    def _cmd_resume(self, chat_id: str):
        if self.scanner:
            self.scanner.start()
        self.notifier.send_message_sync("▶️ *Automated Trading Execution RESUMED.*")

    def _cmd_report(self, chat_id: str):
        if self.risk_manager:
            pnl = self.risk_manager.daily_pnl
            trades = self.risk_manager.daily_trade_count
            msg = (
                f"📊 *TODAY'S SUMMARY REPORT*\n\n"
                f"🔢 *Total Trades*: {trades}\n"
                f"💵 *Net Realized PnL*: *₹{pnl:,.2f}*\n"
                f"🎯 *Max Daily Loss Target*: ₹{settings.MAX_DAILY_LOSS:,.2f}"
            )
            self.notifier.send_message_sync(msg)
