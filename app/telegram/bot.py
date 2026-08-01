import time
import threading
import requests
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
from app.config import settings, normalize_indian_symbol, is_indian_symbol
from app.utils.logger import logger

# Indian Standard Time (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))


class TelegramService:
    """
    Two-Way Interactive Telegram Bot for Indian Stock Markets.
    - Dispatches real-time signals, AI reasoning, and portfolio updates.
    - Listens for interactive user commands (/market, /status, /portfolio, /scan, /price).
    """

    def __init__(self):
        self.token = settings.TELEGRAM_TOKEN
        self.chat_id = settings.CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.currency = settings.CURRENCY_SYMBOL
        self._is_polling = False
        self._poll_thread: Optional[threading.Thread] = None
        self._last_update_id = 0

    @property
    def is_configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def send_message(self, text: str, parse_mode: str = "Markdown", chat_id: Optional[str] = None) -> bool:
        """Sends a text message to the configured Telegram chat."""
        target_chat = chat_id or self.chat_id
        if not self.token or not target_chat:
            logger.debug(f"[Telegram Not Configured] Message:\n{text}")
            return False

        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                "chat_id": target_chat,
                "text": text,
                "parse_mode": parse_mode
            }
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                logger.info("Telegram notification sent successfully.")
                return True
            else:
                logger.error(f"Telegram API error {response.status_code}: {response.text}")
                return False
        except Exception as e:
            logger.error(f"Failed to dispatch Telegram message: {e}")
            return False

    def send_trade_signal_alert(
        self,
        symbol: str,
        action: str,
        price: float,
        strategy: str,
        confidence: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        ai_reasoning: str = "",
        risk_level: str = "MODERATE",
        ai_confirmed: bool = True
    ):
        """Broadcasts a rich trading signal alert with AI reasoning."""
        action_emoji = "🟢 *BUY*" if action.upper() == "BUY" else "🔴 *SELL*"
        status_tag = "✅ *CONFIRMED*" if ai_confirmed else "⚠️ *UNCONFIRMED / VETOED*"
        now_ist = datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")

        sl_str = f"{self.currency}{stop_loss:,.2f}" if stop_loss else "N/A"
        tp_str = f"{self.currency}{take_profit:,.2f}" if take_profit else "N/A"

        message = (
            f"⚡ *TRADEMIND AI - INDIAN STOCK SIGNAL* ⚡\n\n"
            f"📈 *Asset:* `{symbol}`\n"
            f"🎯 *Action:* {action_emoji}\n"
            f"💵 *Price:* `{self.currency}{price:,.2f}`\n"
            f"📊 *Strategy:* `{strategy}`\n"
            f"🔢 *Confidence:* `{confidence * 100:.0f}%`\n"
            f"🛑 *Stop Loss:* `{sl_str}`\n"
            f"🎯 *Take Profit:* `{tp_str}`\n"
            f"⏰ *Time:* `{now_ist}`\n\n"
            f"🧠 *Gemini AI Reasoning:*\n"
            f"_{ai_reasoning or 'Technical momentum confirmation on NSE.'}_\n\n"
            f"🛡️ *Risk Level:* `{risk_level}`\n"
            f"Status: {status_tag}"
        )
        self.send_message(message)

    def send_order_execution_alert(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        total_amount: float,
        realized_pnl: Optional[float] = None,
        reason: str = ""
    ):
        """Sends an alert when a paper trade is filled."""
        side_emoji = "🚀 *BUY EXECUTED*" if side.upper() == "BUY" else "💰 *SELL EXECUTED*"
        pnl_text = ""
        if realized_pnl is not None:
            sign = "+" if realized_pnl >= 0 else ""
            pnl_text = f"\n💵 *Realized PnL:* `{sign}{self.currency}{realized_pnl:,.2f}`"

        now_ist = datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")
        message = (
            f"{side_emoji}\n\n"
            f"📈 *Symbol:* `{symbol}`\n"
            f"🔢 *Quantity:* `{quantity:.4f}`\n"
            f"💵 *Execution Price:* `{self.currency}{price:,.2f}`\n"
            f"💼 *Total Value:* `{self.currency}{total_amount:,.2f}`"
            f"{pnl_text}\n"
            f"📝 *Reason:* _{reason or 'Automated strategy trigger'}_\n"
            f"⏰ *Time:* `{now_ist}`"
        )
        self.send_message(message)

    def send_daily_portfolio_summary(self, summary: Dict[str, Any]):
        """Dispatches an end-of-day portfolio performance overview."""
        cash = summary.get("cash_balance", 0.0)
        equity = summary.get("total_equity", 0.0)
        pnl = summary.get("total_realized_pnl", 0.0)
        unrealized = summary.get("total_unrealized_pnl", 0.0)
        return_pct = summary.get("total_return_percent", 0.0)
        positions = summary.get("positions", [])

        sign = "+" if pnl >= 0 else ""
        unrealized_sign = "+" if unrealized >= 0 else ""
        now_ist = datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")

        message = (
            f"📊 *TRADEMIND AI - DAILY PORTFOLIO SNAPSHOT* 🇮🇳\n\n"
            f"💵 *Cash Balance:* `{self.currency}{cash:,.2f}`\n"
            f"💎 *Total Equity:* `{self.currency}{equity:,.2f}`\n"
            f"📈 *Total Return:* `{sign}{return_pct:.2f}%`\n"
            f"💰 *Realized PnL:* `{sign}{self.currency}{pnl:,.2f}`\n"
            f"⏳ *Unrealized PnL:* `{unrealized_sign}{self.currency}{unrealized:,.2f}`\n"
            f"📂 *Open Positions:* `{len(positions)}`\n"
            f"⏰ *Report Time:* `{now_ist}`\n\n"
            f"🤖 *Status:* _Active & Monitoring NSE/BSE Markets._"
        )
        self.send_message(message)

    # ==========================================
    # Interactive Command Handler & Polling Loop
    # ==========================================

    def _process_user_command(self, chat_id: str, text: str):
        """Processes incoming user messages and dispatches interactive replies."""
        cmd = text.strip().lower()
        now_ist = datetime.now(IST).strftime("%d %b %Y, %I:%M:%S %p IST")
        
        # 1. Market Status Command
        if cmd in ["/market", "/status", "market", "status", "market status", "is market open"]:
            from app.data.fetcher import data_fetcher
            status_text = data_fetcher.get_market_status_ist()
            next_open = data_fetcher.get_next_market_open_ist()
            
            is_live = data_fetcher.is_market_open_now()
            status_badge = "🟢 *LIVE (Trading Session Open)*" if is_live else f"🔴 *{status_text}*"
            
            reply = (
                f"🏛️ *INDIAN STOCK MARKET STATUS* 🇮🇳\n\n"
                f"📊 *Exchange:* National Stock Exchange (NSE / BSE)\n"
                f"⚡ *Current Status:* {status_badge}\n"
                f"⏰ *Current Time:* `{now_ist}`\n"
                f"🕒 *Market Hours:* `09:15 AM – 03:30 PM IST (Mon–Fri)`\n"
                f"⏳ *Next Trading Session:* `{next_open}`\n\n"
                f"🔍 *Engine Mode:* {'🚀 Live Execution & Signal Scanning Active' if is_live else '⏸️ Live Execution Paused (Analyzing Closing Setups)'}\n"
                f"📈 *Tracked Watchlist:* `{len(settings.DEFAULT_SYMBOLS)} Indian Equities`\n\n"
                f"💡 *Quick Commands:*\n"
                f"• `/portfolio` - Cash balance & PnL\n"
                f"• `/scan` - Run on-demand market scan\n"
                f"• `/price <stock>` - Check live quote (e.g. `/price RELIANCE`)\n"
                f"• `/positions` - View open holdings"
            )
            self.send_message(reply, chat_id=chat_id)

        # 2. Portfolio & Balance Command
        elif cmd in ["/portfolio", "/balance", "/pnl", "portfolio", "balance", "pnl"]:
            from app.portfolio.engine import portfolio_engine
            from app.data.fetcher import data_fetcher
            
            current_prices = {}
            for s in settings.DEFAULT_SYMBOLS:
                try:
                    current_prices[s] = data_fetcher.get_current_price(s)
                except Exception:
                    pass
                    
            summary = portfolio_engine.get_portfolio_summary(current_prices)
            cash = summary.get("cash_balance", 0.0)
            equity = summary.get("total_equity", 0.0)
            realized_pnl = summary.get("total_realized_pnl", 0.0)
            unrealized_pnl = summary.get("total_unrealized_pnl", 0.0)
            return_pct = summary.get("total_return_percent", 0.0)
            open_count = summary.get("open_positions_count", 0)

            sign_realized = "+" if realized_pnl >= 0 else ""
            sign_unrealized = "+" if unrealized_pnl >= 0 else ""
            sign_ret = "+" if return_pct >= 0 else ""

            reply = (
                f"💼 *TRADEMIND AI - PORTFOLIO SUMMARY* 🇮🇳\n\n"
                f"💵 *Cash Balance:* `{self.currency}{cash:,.2f}`\n"
                f"💎 *Total Equity:* `{self.currency}{equity:,.2f}`\n"
                f"📈 *Total Return:* `{sign_ret}{return_pct:.2f}%`\n"
                f"💰 *Realized PnL:* `{sign_realized}{self.currency}{realized_pnl:,.2f}`\n"
                f"⏳ *Unrealized PnL:* `{sign_unrealized}{self.currency}{unrealized_pnl:,.2f}`\n"
                f"📂 *Open Positions:* `{open_count}`\n"
                f"⏰ *As of:* `{now_ist}`"
            )
            self.send_message(reply, chat_id=chat_id)

        # 3. View Open Positions
        elif cmd in ["/positions", "positions", "open positions", "holdings"]:
            from app.portfolio.engine import portfolio_engine
            summary = portfolio_engine.get_portfolio_summary()
            positions = summary.get("positions", [])
            
            if not positions:
                reply = "📂 *Open Positions:* None\n\n_Automated scanner is actively monitoring Indian equities for high-probability setups._"
            else:
                lines = ["📂 *CURRENT OPEN POSITIONS:* 🇮🇳\n"]
                for p in positions:
                    sign = "+" if p.get("unrealized_pnl", 0) >= 0 else ""
                    lines.append(
                        f"• *{p['symbol']}*\n"
                        f"  Qty: `{p['quantity']:.4f}` | Entry: `{self.currency}{p['average_entry_price']:,.2f}`\n"
                        f"  Live: `{self.currency}{p['current_price']:,.2f}` | PnL: `{sign}{self.currency}{p['unrealized_pnl']:,.2f} ({sign}{p['unrealized_pnl_percent']:.2f}%)`\n"
                        f"  SL: `{self.currency}{p['stop_loss']:,.2f}` | TP: `{self.currency}{p['take_profit']:,.2f}`"
                    )
                reply = "\n".join(lines)
            self.send_message(reply, chat_id=chat_id)

        # 4. Trigger Instant Market Scan
        elif cmd in ["/scan", "scan", "/scanmarkets", "scan markets"]:
            from app.scheduler.runner import scheduler_runner
            from app.data.fetcher import data_fetcher
            is_live = data_fetcher.is_market_open_now()
            status_text = data_fetcher.get_market_status_ist()
            
            scan_notice = (
                f"⚡ *Initiating Live Market Scan* across 18 NSE equities..."
                if is_live else
                f"⚡ *Scanning NSE Closing Setups* (Market is {status_text})...\n_Note: Real-time paper execution is paused until next market open._"
            )
            self.send_message(scan_notice, chat_id=chat_id)
            threading.Thread(target=lambda: scheduler_runner.run_market_scan(force=True), daemon=True).start()

        # 5. Price / Quote Lookup (e.g. /price RELIANCE or /price INFY.NS)
        elif cmd.startswith("/price") or cmd.startswith("price "):
            parts = text.strip().split()
            if len(parts) < 2:
                self.send_message("ℹ️ *Usage:* `/price <symbol>`\n_Example:_ `/price RELIANCE.NS` or `/price TCS`", chat_id=chat_id)
                return

            raw_sym = parts[1].upper()
            sym = normalize_indian_symbol(raw_sym)
            from app.data.fetcher import data_fetcher
            try:
                trace = data_fetcher.trace_live_stock(sym)
                chg_sign = "+" if trace.change_24h >= 0 else ""
                reply = (
                    f"📈 *{trace.company_name} ({trace.symbol})* 🇮🇳\n\n"
                    f"💵 *Live Price:* `{self.currency}{trace.current_price:,.2f}`\n"
                    f"📊 *24h Change:* `{chg_sign}{self.currency}{trace.change_24h:,.2f} ({chg_sign}{trace.change_percent:.2f}%)`\n"
                    f"📈 *Day High:* `{self.currency}{trace.day_high:,.2f}`\n"
                    f"📉 *Day Low:* `{self.currency}{trace.day_low:,.2f}`\n"
                    f"📊 *52-Week High:* `{self.currency}{trace.fifty_two_week_high:,.2f}`\n"
                    f"📊 *52-Week Low:* `{self.currency}{trace.fifty_two_week_low:,.2f}`\n"
                    f"📦 *Volume:* `{int(trace.volume):,} shares`\n"
                    f"🏛️ *Market Status:* `{trace.market_status}`\n"
                    f"⏰ *Time:* `{trace.timestamp_ist}`"
                )
                self.send_message(reply, chat_id=chat_id)
            except Exception as e:
                self.send_message(f"❌ Could not fetch quote for `{raw_sym}`: {e}", chat_id=chat_id)

        # 6. Help / Default Menu
        else:
            reply = (
                f"🤖 *TradeMind-AI Telegram Assistant* 🇮🇳\n\n"
                f"I am your autonomous algorithmic trading assistant for the Indian Stock Market.\n\n"
                f"Available Commands:\n"
                f"• `/market` - Check if market is Open, Closed, or Pre-Market\n"
                f"• `/portfolio` - View cash balance, equity & PnL\n"
                f"• `/positions` - List active paper positions\n"
                f"• `/scan` - Run immediate multi-strategy market scan\n"
                f"• `/price <symbol>` - Get live NSE quote (e.g. `/price RELIANCE.NS`)\n"
                f"• `/help` - Show this menu"
            )
            self.send_message(reply, chat_id=chat_id)

    def _poll_updates_loop(self):
        """Background thread polling for incoming Telegram messages."""
        logger.info("Telegram interactive command polling service started.")
        while self._is_polling:
            if not self.token:
                time.sleep(5)
                continue

            try:
                url = f"{self.base_url}/getUpdates"
                params = {"offset": self._last_update_id + 1, "timeout": 20}
                res = requests.get(url, params=params, timeout=25)
                
                if res.status_code == 200:
                    data = res.json()
                    if data.get("ok") and data.get("result"):
                        for item in data["result"]:
                            self._last_update_id = item["update_id"]
                            message = item.get("message")
                            if message and "text" in message:
                                chat_id = str(message["chat"]["id"])
                                text = message["text"]
                                # Process command asynchronously
                                threading.Thread(
                                    target=self._process_user_command,
                                    args=(chat_id, text),
                                    daemon=True
                                ).start()
            except Exception as e:
                logger.debug(f"Telegram polling update error: {e}")
                time.sleep(3)

    def start_polling(self):
        """Starts the interactive Telegram polling thread."""
        if not self._is_polling:
            self._is_polling = True
            self._poll_thread = threading.Thread(target=self._poll_updates_loop, daemon=True)
            self._poll_thread.start()

    def stop_polling(self):
        """Stops the interactive Telegram polling thread."""
        self._is_polling = False
        if self._poll_thread:
            self._poll_thread.join(timeout=2)


telegram_service = TelegramService()
TelegramBotService = TelegramService
