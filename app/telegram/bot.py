import time
import threading
import requests
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from app.config import settings, normalize_indian_symbol, is_indian_symbol
from app.database.session import SessionLocal, init_db
from app.database.models import TelegramSubscriber
from app.utils.logger import logger

# Indian Standard Time (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))


class TelegramService:
    """
    Multi-Subscriber Interactive Telegram Bot for NIFTY 50 Futures & Options (F&O).
    - Automatically registers all users who send /start or interact with the bot.
    - Broadcasts real-time In-The-Money (ITM) option signals, order fills, and daily circuit reports
      to ALL active subscribed users.
    - Handles interactive commands (/start, /nifty, /daily, /circuit, /portfolio, /history, /scan, /stop).
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
        return bool(self.token)

    def is_admin(self, chat_id: Optional[str]) -> bool:
        """Returns True if the chat_id is the designated bot administrator (CHAT_ID=8765494577)."""
        if not chat_id:
            return False
        clean_id = str(chat_id).strip()
        admin_id = str(self.chat_id or settings.CHAT_ID or "8765494577").strip()
        return clean_id == admin_id or clean_id == "8765494577"

    def register_or_update_subscriber(
        self,
        chat_id: str,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        is_active: bool = True
    ) -> bool:
        """Saves or updates a Telegram user in the database."""
        if not chat_id:
            return False
        init_db()
        db = SessionLocal()
        try:
            sub = db.query(TelegramSubscriber).filter(TelegramSubscriber.chat_id == str(chat_id)).first()
            if sub:
                if username:
                    sub.username = username
                if first_name:
                    sub.first_name = first_name
                if last_name:
                    sub.last_name = last_name
                sub.is_active = is_active
                sub.last_interaction_at = datetime.utcnow()
            else:
                sub = TelegramSubscriber(
                    chat_id=str(chat_id),
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    is_active=is_active,
                    subscribed_at=datetime.utcnow(),
                    last_interaction_at=datetime.utcnow()
                )
                db.add(sub)
            db.commit()
            logger.info(f"Registered/updated Telegram subscriber: {chat_id} (@{username or 'unknown'}, active={is_active})")
            return True
        except Exception as e:
            logger.error(f"Error registering Telegram subscriber {chat_id}: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    def get_all_subscribers(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """Returns all registered subscribers from the database."""
        init_db()
        db = SessionLocal()
        try:
            query = db.query(TelegramSubscriber)
            if active_only:
                query = query.filter(TelegramSubscriber.is_active == True)
            return [s.to_dict() for s in query.all()]
        except Exception as e:
            logger.error(f"Error fetching telegram subscribers: {e}")
            return []
        finally:
            db.close()

    def get_active_chat_ids(self) -> List[str]:
        """Returns list of distinct active chat IDs who should receive broadcasts."""
        chat_ids = set()

        # 1. Configured default chat ID from .env
        if self.chat_id:
            chat_ids.add(str(self.chat_id).strip())

        # 2. All active subscribers from database
        subs = self.get_all_subscribers(active_only=True)
        for s in subs:
            cid = s.get("chat_id")
            if cid:
                chat_ids.add(str(cid).strip())

        return list(chat_ids)

    def send_to_chat(self, chat_id: str, text: str, parse_mode: str = "Markdown") -> bool:
        """Sends a message to a single specific chat ID."""
        if not self.token or not chat_id:
            return False

        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode
            }
            res = requests.post(url, json=payload, timeout=10)
            if res.status_code == 200:
                return True
            elif res.status_code in [403, 400]:
                # User blocked bot or chat deleted -> deactivate in DB
                logger.warning(f"Telegram user {chat_id} unreachable ({res.status_code}). Deactivating subscriber.")
                self.register_or_update_subscriber(chat_id=chat_id, is_active=False)
                return False
            else:
                logger.error(f"Telegram send error {res.status_code} for chat {chat_id}: {res.text}")
                return False
        except Exception as e:
            logger.error(f"Failed to dispatch Telegram message to {chat_id}: {e}")
            return False

    def send_message(self, text: str, parse_mode: str = "Markdown", chat_id: Optional[str] = None) -> bool:
        """
        Dispatches message via Telegram.
        - If chat_id is provided, sends directly to that user.
        - If chat_id is None, BROADCASTS to ALL people who have started the bot.
        """
        if not self.token:
            logger.debug(f"[Telegram Not Configured] Message:\n{text}")
            return False

        if chat_id:
            return self.send_to_chat(chat_id=chat_id, text=text, parse_mode=parse_mode)

        # Broadcast to all registered subscribers
        recipients = self.get_active_chat_ids()
        if not recipients:
            logger.info("No active Telegram subscribers to broadcast message to.")
            return False

        success_count = 0
        for cid in recipients:
            if self.send_to_chat(chat_id=cid, text=text, parse_mode=parse_mode):
                success_count += 1

        logger.info(f"📢 Broadcasted Telegram notification to {success_count}/{len(recipients)} subscribers.")
        return success_count > 0

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
        """Broadcasts a rich NIFTY F&O trading signal alert to ALL bot subscribers."""
        action_emoji = "🟢 *BUY (ITM CALL / CE)*" if action.upper() == "BUY" else "🔴 *BUY (ITM PUT / PE)*"
        status_tag = "✅ *CONFIRMED & ROUTED*" if ai_confirmed else "⚠️ *UNCONFIRMED / VETOED*"
        now_ist = datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")

        sl_str = f"{self.currency}{stop_loss:,.2f}" if stop_loss else "N/A"
        tp_str = f"{self.currency}{take_profit:,.2f}" if take_profit else "N/A"

        message = (
            f"⚡ *TRADEMIND AI — NIFTY 50 F&O SIGNAL* ⚡\n\n"
            f"🎯 *Contract:* `{symbol}`\n"
            f"📈 *Direction:* {action_emoji}\n"
            f"💵 *Est. Premium:* `{self.currency}{price:,.2f}`\n"
            f"📦 *Lot Size:* `{settings.NIFTY_LOT_SIZE} units`\n"
            f"📊 *Strategy:* `{strategy}`\n"
            f"🔢 *Confidence:* `{confidence * 100:.0f}%`\n"
            f"🛑 *Stop Loss:* `{sl_str}` (Max ₹2,000 daily SL floor)\n"
            f"🎯 *Take Profit:* `{tp_str}` (Max ₹4,000 daily target)\n"
            f"⏰ *Time:* `{now_ist}`\n\n"
            f"🧠 *Gemini AI Reasoning:*\n"
            f"_{ai_reasoning or 'High conviction Nifty trend setup confirmed.'}_\n\n"
            f"🛡️ *Risk Level:* `{risk_level}`\n"
            f"Status: {status_tag}"
        )
        # Dispatches to ALL active subscribers
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
        """Broadcasts trade fill alert to ALL bot subscribers."""
        side_emoji = "🚀 *NIFTY BUY FILLED*" if side.upper() == "BUY" else "💰 *NIFTY EXIT FILLED*"
        pnl_text = ""
        if realized_pnl is not None:
            sign = "+" if realized_pnl >= 0 else ""
            pnl_text = f"\n💵 *Realized PnL:* `{sign}{self.currency}{realized_pnl:,.2f}`"

        now_ist = datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")
        message = (
            f"{side_emoji}\n\n"
            f"🎯 *Contract:* `{symbol}`\n"
            f"🔢 *Quantity:* `{quantity:.0f} units` ({int(quantity / settings.NIFTY_LOT_SIZE)} Lots)\n"
            f"💵 *Execution Premium:* `{self.currency}{price:,.2f}`\n"
            f"💼 *Total Capital Used:* `{self.currency}{total_amount:,.2f}`"
            f"{pnl_text}\n"
            f"📝 *Reason:* _{reason or 'Autonomous F&O strategy execution'}_\n"
            f"⏰ *Executed At:* `{now_ist}`"
        )
        self.send_message(message)

    def send_daily_portfolio_summary(self, summary: Dict[str, Any]):
        """Dispatches daily post-market NIFTY performance summary to ALL subscribers."""
        now_ist = datetime.now(IST).strftime("%d %b %Y")
        ret_sign = "+" if summary.get('total_return_percent', 0) >= 0 else ""
        pnl_sign = "+" if summary.get('total_realized_pnl', 0) >= 0 else ""

        daily_risk = summary.get("daily_risk", {})
        daily_pnl = daily_risk.get("total_daily_pnl", 0.0)
        daily_sign = "+" if daily_pnl >= 0 else ""
        trades_today = daily_risk.get("trades_today", 0)
        circuit_status = daily_risk.get("circuit_status", "ACTIVE")

        message = (
            f"📊 *TRADEMIND AI — NIFTY DAILY REPORT* 🇮🇳\n"
            f"📅 *Date:* `{now_ist}`\n\n"
            f"💼 *Account Capital:* `{self.currency}{summary.get('total_equity', 0):,.2f}` (Initial: `{self.currency}{summary.get('initial_balance', 0):,.2f}`)\n"
            f"💵 *Liquid Cash:* `{self.currency}{summary.get('cash_balance', 0):,.2f}`\n"
            f"📈 *Today's Net PnL:* `{daily_sign}{self.currency}{daily_pnl:,.2f}`\n"
            f"🎯 *Today's Trades:* `{trades_today} / {settings.MAX_DAILY_TRADES}`\n"
            f"🛡️ *Circuit Status:* `{circuit_status}`\n"
            f"📈 *Total Lifetime Return:* `{ret_sign}{summary.get('total_return_percent', 0):.2f}%`\n"
            f"💰 *Total Realized PnL:* `{pnl_sign}{self.currency}{summary.get('total_realized_pnl', 0):,.2f}`\n"
            f"📂 *Open Positions:* `{summary.get('open_positions_count', 0)}`"
        )
        self.send_message(message)

    def send_alert(self, text: str):
        """Dispatches a generic alert notification to ALL subscribers."""
        self.send_message(text, parse_mode="HTML")

    def _process_user_command(self, chat_id: str, text: str, user_info: Optional[Dict[str, Any]] = None):
        """Processes incoming user commands sent via Telegram."""
        text = text.strip()
        cmd = text.split()[0].lower()
        now_ist = datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")
        user_info = user_info or {}

        # 0. Start & Welcome Command (Subscribes user)
        if cmd in ["/start", "start"]:
            self.register_or_update_subscriber(
                chat_id=chat_id,
                username=user_info.get("username"),
                first_name=user_info.get("first_name"),
                last_name=user_info.get("last_name"),
                is_active=True
            )
            first_name = user_info.get("first_name") or "Trader"
            admin_cmd = "\n• `/subscribers` - Manage subscribers roster (Admin Only)" if self.is_admin(chat_id) else ""
            reply = (
                f"🎉 *Welcome {first_name} to TradeMind AI!* 🇮🇳\n\n"
                f"✅ *Subscription Active:* You will now receive **all live trading signals**, execution alerts, AI reasoning, and daily PnL reports directly in this chat!\n\n"
                f"🎯 *Universe:* `NIFTY 50 Futures & Options (F&O)`\n"
                f"⚡ *Strategy:* `In-The-Money (ITM) Breakouts + Gemini AI Confluence`\n"
                f"🛡️ *Daily Risk:* `Max 4 Trades/Day | ₹2,000 Max SL | ₹4,000 Profit Target`\n\n"
                f"📌 *Available Commands:*\n"
                f"• `/nifty` - Live NIFTY spot & recommended ITM Call/Put strikes\n"
                f"• `/daily` - Daily Risk & Circuit Breaker status\n"
                f"• `/portfolio` - ₹30,000 Capital & balance overview\n"
                f"• `/positions` - Active open ITM options positions & Trailing SL\n"
                f"• `/history` - Trade audit log & win-rate metrics\n"
                f"• `/market` - Check live NSE market hours\n"
                f"• `/scan` - Run immediate NIFTY 50 scan\n"
                f"• `/stop` - Pause signal alerts{admin_cmd}\n\n"
                f"🚀 *Sit back and let AI identify high-probability setups!*"
            )
            self.send_message(reply, chat_id=chat_id)

        # Stop / Unsubscribe
        elif cmd in ["/stop", "/unsubscribe", "stop", "unsubscribe"]:
            self.register_or_update_subscriber(chat_id=chat_id, is_active=False)
            reply = (
                f"⏸️ *Alerts Paused*\n\n"
                f"You have unsubscribed from automated signal broadcasts.\n"
                f"You can still use commands (/nifty, /daily, /portfolio) or type `/start` anytime to resume live alerts."
            )
            self.send_message(reply, chat_id=chat_id)

        # Community / Subscriber Stats (ADMIN ONLY - CHAT_ID: 8765494577)
        elif cmd in ["/subscribers", "/users", "/community", "/subscribers_list"]:
            if not self.is_admin(chat_id):
                reply = "⛔ *Access Denied:* The `/subscribers` management command is restricted to the administrator (`8765494577`)."
                self.send_message(reply, chat_id=chat_id)
            else:
                subs = self.get_all_subscribers(active_only=False)
                active_subs = [s for s in subs if s.get("is_active")]
                inactive_subs = [s for s in subs if not s.get("is_active")]

                user_lines = []
                for idx, s in enumerate(subs[:25], start=1):
                    uname = f"@{s['username']}" if s.get('username') else (s.get('first_name') or 'Trader')
                    st_icon = "🟢" if s.get('is_active') else "⏸️"
                    user_lines.append(f"{idx}. {st_icon} `{s['chat_id']}` ({uname})")

                users_list_str = "\n".join(user_lines) if user_lines else "_No subscribers registered yet._"

                reply = (
                    f"👥 *TRADEMIND AI — SUBSCRIBER MANAGEMENT (ADMIN)* 🇮🇳\n\n"
                    f"• *Total Registered Users:* `{len(subs)}`\n"
                    f"• *Active Live Alert Receivers:* `{len(active_subs)}`\n"
                    f"• *Paused / Inactive:* `{len(inactive_subs)}`\n"
                    f"• *Broadcast Mode:* `Multi-User Auto-Dispatch Enabled`\n\n"
                    f"📋 *Subscribers Roster:*\n{users_list_str}\n\n"
                    f"⏰ *As of:* `{now_ist}`"
                )
                self.send_message(reply, chat_id=chat_id)

        # 1. Market Status
        elif cmd in ["/market", "/status", "market", "status"]:
            from app.data.fetcher import data_fetcher
            status_text = data_fetcher.get_market_status_ist()
            is_open = data_fetcher.is_market_open_now()
            next_open = data_fetcher.get_next_market_open_ist()
            status_emoji = "🟢 *OPEN*" if is_open else "🔴 *CLOSED*"

            reply = (
                f"🏛️ *INDIAN STOCK MARKET (NSE / BSE) STATUS* 🇮🇳\n\n"
                f"• Current Status: {status_emoji} (`{status_text}`)\n"
                f"• Focus Universe: `NIFTY 50 Index (F&O Exclusive)`\n"
                f"• Capital: `{self.currency}{settings.INITIAL_BALANCE:,.2f}`\n"
                f"• Max Daily Trades: `{settings.MAX_DAILY_TRADES}`\n"
                f"• Max Daily SL / Target: `{self.currency}{settings.MAX_DAILY_LOSS:,.2f} / +{self.currency}{settings.MAX_DAILY_PROFIT:,.2f}`\n"
                f"• Next Market Open: `{next_open}`\n"
                f"• Current Time: `{now_ist}`"
            )
            self.send_message(reply, chat_id=chat_id)

        # 2. Daily Risk & Circuit Breaker Monitor
        elif cmd in ["/daily", "/circuit", "/risk", "daily", "circuit", "risk"]:
            from app.portfolio.daily_risk import daily_risk_manager
            stats = daily_risk_manager.get_daily_trade_stats()

            pnl = stats["total_daily_pnl"]
            pnl_sign = "+" if pnl >= 0 else ""
            status_badge = {
                "ACTIVE": "🟢 *ACTIVE (Trading Enabled)*",
                "HALTED_MAX_LOSS": "🛑 *HALTED (Max Daily SL Hit)*",
                "HALTED_MAX_PROFIT": "🎉 *HALTED (Daily Profit Target Achieved)*",
                "HALTED_MAX_TRADES": "⚠️ *HALTED (Daily Trade Cap Reached)*",
                "HALTED_EXPIRY_AFTER_2PM": "⏳ *HALTED (Expiry Day Post-2PM Cutoff)*"
            }.get(stats["circuit_status"], "🟢 *ACTIVE*")

            reply = (
                f"🛡️ *NIFTY 50 DAILY RISK & CIRCUIT MONITOR* 🇮🇳\n\n"
                f"📅 *Session Date:* `{stats['date_ist']}`\n"
                f"⚡ *Circuit Status:* {status_badge}\n\n"
                f"📊 *Today's Performance:*\n"
                f"• *Today's Net PnL:* `{pnl_sign}{self.currency}{pnl:,.2f}`\n"
                f"• *Realized PnL:* `{self.currency}{stats['daily_realized_pnl']:,.2f}`\n"
                f"• *Unrealized PnL:* `{self.currency}{stats['daily_unrealized_pnl']:,.2f}`\n\n"
                f"🎯 *Daily Limits & Quotas:*\n"
                f"• *Trades Taken:* `{stats['trades_today']} / {stats['max_daily_trades']}` (`{stats['remaining_trades']} remaining`)\n"
                f"• *Max Daily Stop-Loss:* `-{self.currency}{stats['max_daily_loss']:,.2f}` (Room: `{self.currency}{stats['loss_limit_remaining']:,.2f}`)\n"
                f"• *Daily Profit Target:* `+{self.currency}{stats['max_daily_profit']:,.2f}` (Remaining: `{self.currency}{stats['profit_target_remaining']:,.2f}`)\n\n"
                f"💬 *Engine Message:*\n_{stats['status_message']}_\n\n"
                f"⏰ *As of:* `{now_ist}`"
            )
            self.send_message(reply, chat_id=chat_id)

        # 3. Live NIFTY F&O Quote & ITM Strike Recommendation
        elif cmd in ["/nifty", "/fno", "nifty", "fno"]:
            from app.data.fetcher import data_fetcher
            from app.data.nifty_options import get_nifty_itm_strike
            try:
                trace = data_fetcher.trace_live_stock("^NSEI")
                spot = trace.current_price
                chg_sign = "+" if trace.change_24h >= 0 else ""

                itm_ce = get_nifty_itm_strike(spot, "CE", itm_depth=1)
                itm_pe = get_nifty_itm_strike(spot, "PE", itm_depth=1)

                reply = (
                    f"🎯 *NIFTY 50 INDEX (F&O SCANNER)* 🇮🇳\n\n"
                    f"💵 *Live Spot:* `{self.currency}{spot:,.2f}` ({chg_sign}{trace.change_percent:.2f}%)\n"
                    f"📈 *Day Range:* `{self.currency}{trace.day_low:,.2f} – {self.currency}{trace.day_high:,.2f}`\n"
                    f"📦 *Lot Size:* `{settings.NIFTY_LOT_SIZE} units`\n"
                    f"📅 *Expiry:* `{itm_ce['expiry_display']}`\n\n"
                    f"🟢 *RECOMMENDED ITM CALL (BULLISH):*\n"
                    f"• Contract: `{itm_ce['symbol']}`\n"
                    f"• Est. Premium: `{self.currency}{itm_ce['estimated_premium']:,.2f}`\n"
                    f"• 1-Lot Cost: `{self.currency}{itm_ce['lot_cost']:,.2f}` (Delta: ~{itm_ce['estimated_delta']})\n\n"
                    f"🔴 *RECOMMENDED ITM PUT (BEARISH):*\n"
                    f"• Contract: `{itm_pe['symbol']}`\n"
                    f"• Est. Premium: `{self.currency}{itm_pe['estimated_premium']:,.2f}`\n"
                    f"• 1-Lot Cost: `{self.currency}{itm_pe['lot_cost']:,.2f}` (Delta: ~{itm_pe['estimated_delta']})\n\n"
                    f"💼 *Budget:* `{self.currency}{settings.INITIAL_BALANCE:,.2f}` (35% Max Margin/Trade)\n"
                    f"⏰ *As of:* `{now_ist}`"
                )
                self.send_message(reply, chat_id=chat_id)
            except Exception as e:
                self.send_message(f"❌ Could not fetch NIFTY live data: {e}", chat_id=chat_id)

        # 4. View Virtual Portfolio Summary
        elif cmd in ["/portfolio", "/balance", "portfolio", "balance"]:
            from app.portfolio.engine import portfolio_engine
            summary = portfolio_engine.get_portfolio_summary()
            ret_sign = "+" if summary['total_return_percent'] >= 0 else ""
            pnl_sign = "+" if summary['total_realized_pnl'] >= 0 else ""

            daily_risk = summary.get("daily_risk", {})
            daily_pnl = daily_risk.get("total_daily_pnl", 0.0)
            daily_sign = "+" if daily_pnl >= 0 else ""

            reply = (
                f"💼 *TRADEMIND AI — VIRTUAL PORTFOLIO* 🇮🇳\n\n"
                f"• *Total Equity:* `{self.currency}{summary['total_equity']:,.2f}`\n"
                f"• *Initial Capital:* `{self.currency}{summary['initial_balance']:,.2f}`\n"
                f"• *Available Cash:* `{self.currency}{summary['cash_balance']:,.2f}`\n"
                f"• *Positions Value:* `{self.currency}{summary['portfolio_value']:,.2f}`\n"
                f"• *Today's Net PnL:* `{daily_sign}{self.currency}{daily_pnl:,.2f}`\n"
                f"• *Today's Trades:* `{daily_risk.get('trades_today', 0)} / {settings.MAX_DAILY_TRADES}`\n"
                f"• *Total Lifetime Realized PnL:* `{pnl_sign}{self.currency}{summary['total_realized_pnl']:,.2f}`\n"
                f"• *Total Lifetime Return:* `{ret_sign}{summary['total_return_percent']:.2f}%`\n"
                f"• *Open F&O Positions:* `{summary['open_positions_count']}`\n\n"
                f"⏰ *As of:* `{now_ist}`"
            )
            self.send_message(reply, chat_id=chat_id)

        # 4b. Reset Portfolio Balance (Admin Only)
        elif cmd in ["/reset", "/resetportfolio", "reset"]:
            if not self.is_admin(chat_id):
                reply = "⛔ *Access Denied:* The `/reset` portfolio command is restricted to the administrator (`8765494577`)."
                self.send_message(reply, chat_id=chat_id)
            else:
                from app.portfolio.engine import portfolio_engine
                summary = portfolio_engine.reset_portfolio(settings.INITIAL_BALANCE)
                reply = (
                    f"🔄 *PORTFOLIO RESET COMPLETED* 🇮🇳\n\n"
                    f"• *Capital Restored:* `{self.currency}{summary['initial_balance']:,.2f}`\n"
                    f"• *Available Cash:* `{self.currency}{summary['cash_balance']:,.2f}`\n"
                    f"• *Open Positions:* `0`\n"
                    f"• *Realized PnL:* `₹0.00`\n\n"
                    f"✅ Paper trading account is now fresh with ₹30,000 INR starting capital."
                )
                self.send_message(reply, chat_id=chat_id)

        # 5. View Open Positions
        elif cmd in ["/positions", "positions", "open positions"]:
            from app.portfolio.engine import portfolio_engine
            summary = portfolio_engine.get_portfolio_summary()
            positions = summary.get("positions", [])

            if not positions:
                reply = "ℹ️ *No open NIFTY F&O positions.* System is scanning for high-conviction ITM setups."
            else:
                lines = [f"📂 *ACTIVE OPEN POSITIONS ({len(positions)}):*\n"]
                for p in positions:
                    sign = "+" if p['unrealized_pnl'] >= 0 else ""
                    tsl_info = f" | TSL: `{self.currency}{p['trailing_stop']:,.2f}`" if p.get('trailing_stop') else ""
                    lines.append(
                        f"• *{p['symbol']}*\n"
                        f"  Qty: `{p['quantity']:.0f}` | Avg: `{self.currency}{p['average_entry_price']:,.2f}` | LTP: `{self.currency}{p['current_price']:,.2f}`\n"
                        f"  PnL: `{sign}{self.currency}{p['unrealized_pnl']:,.2f} ({sign}{p['unrealized_pnl_percent']:.2f}%)`\n"
                        f"  SL: `{self.currency}{p['stop_loss']:,.2f}`{tsl_info} | TP: `{self.currency}{p['take_profit']:,.2f}`"
                    )
                reply = "\n".join(lines)
            self.send_message(reply, chat_id=chat_id)

        # 6. View Trade History & Performance Audit
        elif cmd in ["/history", "/trades", "/tradehistory", "history", "trades", "past trades"]:
            from app.portfolio.engine import portfolio_engine
            metrics = portfolio_engine.get_trade_performance_metrics(limit=10)

            total_closed = metrics["total_trades"]
            win_rate = metrics["win_rate_percent"]
            wins = metrics["winning_trades"]
            losses = metrics["losing_trades"]
            total_pnl = metrics["total_realized_pnl"]
            pnl_sign = "+" if total_pnl >= 0 else ""
            pf = metrics["profit_factor"]
            best = metrics["best_trade"]
            best_sign = "+" if best >= 0 else ""
            trades = metrics.get("trades", [])

            history_lines = [
                f"📜 *TRADEMIND AI — NIFTY F&O TRADE AUDIT* 🇮🇳\n",
                f"📊 *Lifetime Performance Summary:*",
                f"• *Closed Trades:* `{total_closed}` (`{wins}W / {losses}L`)",
                f"• *Win Rate:* `{win_rate:.1f}%`",
                f"• *Net Realized PnL:* `{pnl_sign}{self.currency}{total_pnl:,.2f}`",
                f"• *Profit Factor:* `{pf:.2f}`",
                f"• *Best Trade:* `{best_sign}{self.currency}{best:,.2f}`\n",
                f"📋 *Recent Trade Logs (Last {min(len(trades), 10)}):*"
            ]

            if not trades:
                history_lines.append("_No trade history yet. System is scanning for confirmed setups._")
            else:
                for idx, t in enumerate(trades[:10], start=1):
                    side = t.get("side", "TRADE")
                    sym = t.get("symbol", "N/A")
                    status = t.get("status", "OPEN")
                    entry = t.get("entry_price", 0.0)
                    exit_p = t.get("exit_price")
                    pnl = t.get("realized_pnl", 0.0)
                    pnl_pct = t.get("pnl_percent", 0.0)
                    sign = "+" if pnl >= 0 else ""

                    if status == "CLOSED":
                        badge = "🟢 *WIN*" if pnl > 0 else ("🔴 *LOSS*" if pnl < 0 else "⚪ *EVEN*")
                        reason = t.get("reason") or "Closed"
                        exit_str = f"`{self.currency}{exit_p:,.2f}`" if exit_p else "N/A"
                        history_lines.append(
                            f"{idx}. {badge} *{sym}* ({side})\n"
                            f"   • Entry: `{self.currency}{entry:,.2f}` ➔ Exit: {exit_str}\n"
                            f"   • PnL: `{sign}{self.currency}{pnl:,.2f} ({sign}{pnl_pct:.2f}%)`\n"
                            f"   • Reason: _{reason}_"
                        )
                    else:
                        history_lines.append(
                            f"{idx}. 🔵 *OPEN* *{sym}* ({side})\n"
                            f"   • Entry: `{self.currency}{entry:,.2f}` | Strategy: `{t.get('strategy', 'Algo')}`"
                        )

            history_lines.append(f"\n⏰ *As of:* `{now_ist}`")
            reply = "\n".join(history_lines)
            self.send_message(reply, chat_id=chat_id)

        # 7. Trigger Instant Market Scan
        elif cmd in ["/scan", "scan", "/scanmarkets"]:
            from app.scheduler.runner import scheduler_runner
            from app.data.fetcher import data_fetcher
            is_live = data_fetcher.is_market_open_now()
            status_text = data_fetcher.get_market_status_ist()

            scan_notice = (
                f"⚡ *Initiating Live NIFTY 50 Scan* (Market is {status_text})..."
                if is_live else
                f"⚡ *Scanning NIFTY 50 Closing Setups* (Market is {status_text})...\n_Note: Paper order execution is paused until next market open._"
            )
            self.send_message(scan_notice, chat_id=chat_id)
            threading.Thread(target=lambda: scheduler_runner.run_market_scan(force=True), daemon=True).start()

        # 8. Help / Default Menu
        else:
            admin_cmd = "\n• `/subscribers` - Manage subscribers roster (Admin Only)" if self.is_admin(chat_id) else ""
            reply = (
                f"🤖 *TradeMind-AI Telegram Assistant (NIFTY F&O)* 🇮🇳\n\n"
                f"I am your autonomous algorithmic assistant trading **NIFTY 50 Futures & Options** with ITM strike selection and strict daily risk circuits.\n\n"
                f"Available Commands:\n"
                f"• `/start` - Subscribe to all live trading signals & alerts\n"
                f"• `/nifty` - Live NIFTY 50 spot & recommended ITM Call/Put strikes\n"
                f"• `/daily` - Daily Risk & Circuit Monitor (Trades X/4, PnL vs ₹4,000 Target / ₹2,000 SL)\n"
                f"• `/portfolio` - View ₹30k capital, liquid cash & returns\n"
                f"• `/positions` - List active ITM options positions with TSL\n"
                f"• `/history` - View complete trade audit log & win rate\n"
                f"• `/market` - Check if NSE is Open, Closed, or Pre-Market\n"
                f"• `/scan` - Run immediate NIFTY multi-strategy scan\n"
                f"• `/stop` - Pause live signal broadcasts{admin_cmd}\n"
                f"• `/help` - Show this menu"
            )
            self.send_message(reply, chat_id=chat_id)

    def _poll_updates_loop(self):
        """Background thread polling for incoming Telegram messages from all users."""
        logger.info("Telegram interactive command polling service started for all users.")
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
                                user_info = message.get("from", {})

                                # Auto-register subscriber
                                self.register_or_update_subscriber(
                                    chat_id=chat_id,
                                    username=user_info.get("username"),
                                    first_name=user_info.get("first_name"),
                                    last_name=user_info.get("last_name"),
                                    is_active=True
                                )

                                threading.Thread(
                                    target=self._process_user_command,
                                    args=(chat_id, text, user_info),
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
