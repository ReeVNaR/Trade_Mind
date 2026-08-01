import time
import threading
import schedule
from datetime import datetime
from typing import List, Dict, Any

from app.config import settings
from app.data.fetcher import data_fetcher
from app.strategies.base import BaseStrategy, Signal, ActionType
from app.strategies.trend_following import TrendFollowingStrategy
from app.strategies.rsi_reversal import RSIReversalStrategy
from app.strategies.supertrend_vwap import SupertrendVWAPStrategy
from app.ai.gemini_analyst import gemini_analyst
from app.portfolio.engine import portfolio_engine
from app.database.session import SessionLocal
from app.database.models import SignalLog
from app.telegram.bot import telegram_service
from app.utils.logger import logger


class SchedulerRunner:
    """
    Automated Background Scheduler for Indian Stock Markets.
    Periodically fetches NSE/BSE candles, evaluates quantitative strategies,
    triggers Gemini AI reasoning, routes paper trades, and monitors SL/TP triggers.
    """

    def __init__(self):
        self.is_running = False
        self._thread = None
        self.strategies: List[BaseStrategy] = [
            SupertrendVWAPStrategy(),
            TrendFollowingStrategy(),
            RSIReversalStrategy()
        ]

    def run_market_scan(self, force: bool = False):
        """Executes a full scanning pass over the Indian watchlist."""
        is_open = data_fetcher.is_market_open_now()
        status_ist = data_fetcher.get_market_status_ist()

        if not is_open and not force:
            logger.info(f"Indian Stock Market is {status_ist}. Automated background execution paused until {data_fetcher.get_next_market_open_ist()}.")
            return

        logger.info(f"=== Starting Market Scan (NSE/BSE) | Session: {status_ist} ===")
        symbols = settings.DEFAULT_SYMBOLS
        current_prices: Dict[str, float] = {}
        signals_processed = 0

        for symbol in symbols:
            try:
                logger.info(f"Scanning market data for {symbol}...")
                df = data_fetcher.fetch_ohlcv(symbol, period="10d", interval="15m")
                if df.empty or len(df) < 20:
                    logger.warning(f"Not enough data to scan {symbol}")
                    continue

                curr_price = float(df["close"].iloc[-1])
                current_prices[symbol] = curr_price

                # Evaluate all active strategies
                for strategy in self.strategies:
                    signal = strategy.generate_signal(df, symbol)
                    if signal.action != ActionType.HOLD:
                        signals_processed += 1
                        logger.info(f"🎯 Strategy [{strategy.name}] generated {signal.action.value} signal for {symbol} @ ₹{signal.price:,.2f}")
                        
                        # AI Confirmation
                        ai_result = gemini_analyst.analyze_signal(signal, {"symbol": symbol, "current_price": curr_price})
                        
                        # Log Signal to Database
                        db = SessionLocal()
                        try:
                            log = SignalLog(
                                symbol=symbol,
                                strategy=strategy.name,
                                action=signal.action.value,
                                confidence=signal.confidence,
                                price=signal.price,
                                stop_loss=signal.stop_loss,
                                take_profit=signal.take_profit,
                                ai_reasoning=ai_result.reasoning,
                                ai_confirmed=ai_result.confirmed,
                                executed=ai_result.confirmed if is_open else False
                            )
                            db.add(log)
                            db.commit()
                        finally:
                            db.close()

                        # Dispatch Telegram Alert with Session Details
                        if is_open:
                            telegram_service.send_trade_signal_alert(
                                symbol=symbol,
                                action=signal.action.value,
                                price=signal.price,
                                strategy=strategy.name,
                                confidence=ai_result.confidence_score,
                                stop_loss=signal.stop_loss,
                                take_profit=signal.take_profit,
                                ai_reasoning=ai_result.reasoning,
                                risk_level=ai_result.risk_level,
                                ai_confirmed=ai_result.confirmed
                            )
                        else:
                            # Send AMO / Closed Market Alert only if manually forced
                            telegram_service.send_alert(
                                f"🕒 <b>AMO / AFTER-HOURS SETUP DETECTED</b>\n\n"
                                f"<b>Symbol:</b> <code>{symbol}</code>\n"
                                f"<b>Signal:</b> <b>{signal.action.value}</b> @ ₹{signal.price:,.2f}\n"
                                f"<b>Strategy:</b> {strategy.name}\n"
                                f"<b>AI Confidence:</b> {int(ai_result.confidence_score * 100)}%\n\n"
                                f"🧠 <b>AI Verdict:</b> {ai_result.reasoning}\n\n"
                                f"⚠️ <i>Market is currently {status_ist}. No live order was executed. Next session opens {data_fetcher.get_next_market_open_ist()}.</i>"
                            )

                        # Execute Paper Order ONLY if market is actively open
                        if is_open and ai_result.confirmed:
                            portfolio_engine.execute_signal(signal)

            except Exception as e:
                logger.error(f"Error during scan of {symbol}: {e}")

        # Check Stop-Loss and Take-Profit for open positions if market is live
        if is_open:
            sl_tp_trades = portfolio_engine.check_stop_loss_take_profit(current_prices)
            logger.info(f"=== Market Scan Completed: {signals_processed} signals processed, {len(sl_tp_trades)} SL/TP exits ===")
        else:
            logger.info(f"=== Market Scan Completed (Closed Session): {signals_processed} setups analyzed. Zero live orders executed. ===")

    def run_daily_summary(self):
        """Sends daily portfolio summary to Telegram."""
        summary = portfolio_engine.get_portfolio_summary()
        telegram_service.send_daily_portfolio_summary(summary)

    def _keep_alive_ping(self):
        """Pings own service URL periodically to prevent Render free-tier idle spin-down."""
        import os
        import urllib.request
        url = os.getenv("KEEP_ALIVE_URL") or os.getenv("RENDER_EXTERNAL_URL")
        if url:
            try:
                target = f"{url.rstrip('/')}/health"
                req = urllib.request.Request(target, headers={"User-Agent": "TradeMind-KeepAlive/1.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status == 200:
                        logger.debug(f"Keep-alive self-ping to {target} succeeded.")
            except Exception as e:
                logger.debug(f"Keep-alive ping attempt failed: {e}")

    def _schedule_loop(self):
        """Background daemon thread execution loop."""
        schedule.every(settings.SCAN_INTERVAL_MINUTES).minutes.do(self.run_market_scan)
        schedule.every().day.at("15:35").do(self.run_daily_summary)  # After Indian market close (15:30 IST)
        schedule.every(10).minutes.do(self._keep_alive_ping)  # Keep Render free instance awake

        logger.info(f"Scheduler active: scanning every {settings.SCAN_INTERVAL_MINUTES} min, daily summary at 15:35 IST.")
        while self.is_running:
            schedule.run_pending()
            time.sleep(1)

    def start(self):
        """Starts the background scheduler thread."""
        if not self.is_running:
            self.is_running = True
            self._thread = threading.Thread(target=self._schedule_loop, daemon=True)
            self._thread.start()
            logger.info("Background market scheduler thread started.")

    def stop(self):
        """Stops the background scheduler thread."""
        self.is_running = False
        if self._thread:
            self._thread.join(timeout=2)
            logger.info("Background market scheduler stopped.")


scheduler_runner = SchedulerRunner()
