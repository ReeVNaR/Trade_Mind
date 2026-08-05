import time
import threading
import schedule
import pandas as pd
from datetime import datetime, time as dtime
from typing import List, Dict, Any

from app.config import settings
from app.data.fetcher import data_fetcher, IST
from app.data.nifty_options import get_nifty_itm_strike, NIFTY_LOT_SIZE
from app.strategies.base import BaseStrategy, Signal, ActionType
from app.strategies.trend_following import TrendFollowingStrategy
from app.strategies.rsi_reversal import RSIReversalStrategy
from app.strategies.supertrend_vwap import SupertrendVWAPStrategy
from app.ai.gemini_analyst import gemini_analyst
from app.portfolio.engine import portfolio_engine
from app.portfolio.daily_risk import daily_risk_manager
from app.database.session import SessionLocal
from app.database.models import SignalLog
from app.telegram.bot import telegram_service
from app.utils.logger import logger


class SchedulerRunner:
    """
    Automated Background Scheduler for NIFTY 50 Futures & Options (F&O).
    Periodically fetches NIFTY 50 index candles, evaluates quantitative breakout strategies,
    triggers Gemini AI reasoning, routes In-The-Money (ITM) option paper trades,
    and enforces strict Daily Risk & Circuit Breaker limits (Max 4 trades, ₹2,000 SL, ₹4,000 Profit).
    """

    def __init__(self):
        self.is_running = False
        self._thread = None
        self.strategies: List[BaseStrategy] = [
            SupertrendVWAPStrategy(),
            TrendFollowingStrategy(),
            RSIReversalStrategy()
        ]

    def _evaluate_opportunistic_signal(self, df: pd.DataFrame, symbol: str, curr_price: float) -> Signal:
        """
        Generates an opportunistic trade signal based on dominant market directional bias
        to enforce mandatory daily trades (MIN_DAILY_TRADES) when standard strategies return HOLD.
        """
        from app.indicators.technical import calculate_all_indicators
        data = calculate_all_indicators(df)
        curr = data.iloc[-1]
        
        vwap = float(curr.get("vwap", curr_price))
        st_dir = int(curr.get("supertrend_dir", 1))
        ema9 = float(curr.get("ema_9", curr_price))
        ema21 = float(curr.get("ema_21", curr_price))
        ema50 = float(curr.get("ema_50", curr_price))
        rsi = float(curr.get("rsi_14", 50.0))
        macd_hist = float(curr.get("macd_hist", 0.0))
        atr = float(curr.get("atr_14", curr_price * 0.015))

        bullish_score = 0
        bearish_score = 0

        if st_dir == 1:
            bullish_score += 2
        else:
            bearish_score += 2

        if curr_price >= vwap:
            bullish_score += 2
        else:
            bearish_score += 2

        if ema9 >= ema21:
            bullish_score += 1
        else:
            bearish_score += 1

        if curr_price >= ema50:
            bullish_score += 1
        else:
            bearish_score += 1

        if rsi >= 50:
            bullish_score += 1
        else:
            bearish_score += 1

        if macd_hist >= 0:
            bullish_score += 1
        else:
            bearish_score += 1

        indicators_summary = {
            "price": round(curr_price, 2),
            "vwap": round(vwap, 2),
            "supertrend_direction": "BULLISH" if st_dir == 1 else "BEARISH",
            "rsi": round(rsi, 2),
            "bullish_bias_score": bullish_score,
            "bearish_bias_score": bearish_score,
            "is_mandatory_trade": True
        }

        if bullish_score >= bearish_score:
            action = ActionType.BUY
            stop_loss = curr_price - (1.5 * atr)
            take_profit = curr_price + (3.0 * atr)
            reason = (
                f"Mandatory Daily Target Enforcement (Min {settings.MIN_DAILY_TRADES} trades/day): "
                f"Bullish bias detected (Score {bullish_score} vs {bearish_score}, ST Green, Close ₹{curr_price:,.2f})."
            )
        else:
            action = ActionType.SELL
            stop_loss = curr_price + (1.5 * atr)
            take_profit = curr_price - (3.0 * atr)
            reason = (
                f"Mandatory Daily Target Enforcement (Min {settings.MIN_DAILY_TRADES} trades/day): "
                f"Bearish bias detected (Score {bearish_score} vs {bullish_score}, ST Red, Close ₹{curr_price:,.2f})."
            )

        return Signal(
            symbol=symbol,
            action=action,
            price=curr_price,
            confidence=0.68,
            strategy_name="Opportunistic_Mandatory_Daily_Target",
            stop_loss=stop_loss,
            take_profit=take_profit,
            reason=reason,
            indicators=indicators_summary
        )

    def run_market_scan(self, force: bool = False):
        """Executes a full scanning pass over NIFTY 50 Index."""
        is_open = data_fetcher.is_market_open_now()
        status_ist = data_fetcher.get_market_status_ist()

        if not is_open and not force:
            logger.info(f"Indian Stock Market is {status_ist}. Automated background execution paused until {data_fetcher.get_next_market_open_ist()}.")
            return

        # Check Daily Risk Circuit
        can_open_trades, circuit_status_msg = daily_risk_manager.can_open_new_trade()
        if not can_open_trades:
            logger.info(f"⏸️ Intraday Entry Orders Paused: {circuit_status_msg}")

        logger.info(f"=== Starting NIFTY 50 F&O Market Scan | Session: {status_ist} ===")
        symbols = settings.DEFAULT_SYMBOLS  # Strictly ['^NSEI']
        current_prices: Dict[str, float] = {}
        signals_processed = 0

        now_ist_time = datetime.now(IST).time()
        is_after_1520 = now_ist_time >= dtime(15, 20)

        for symbol in symbols:
            try:
                logger.info(f"Scanning market data for {symbol} (NIFTY 50 Index)...")
                df = data_fetcher.fetch_ohlcv(symbol, period="10d", interval="15m")
                if df.empty or len(df) < 20:
                    logger.warning(f"Not enough candle data for {symbol}, skipping scan.")
                    continue

                ticker = data_fetcher.get_live_nifty_ticker()
                curr_price = (ticker.get("current_price") if ticker else None) or float(df["close"].iloc[-1])
                current_prices[symbol] = curr_price
                executed_trade = None

                # Evaluate all active strategies
                for strategy in self.strategies:
                    signal = strategy.generate_signal(df, symbol)
                    if signal.action != ActionType.HOLD:
                        signals_processed += 1
                        logger.info(f"🎯 Strategy [{strategy.name}] generated {signal.action.value} signal for {symbol} @ ₹{signal.price:,.2f}")

                        # Calculate ITM Option details for NIFTY
                        is_call = signal.action == ActionType.BUY
                        opt_type = "CE" if is_call else "PE"
                        itm_info = get_nifty_itm_strike(curr_price, opt_type, itm_depth=1)
                        display_contract = f"{itm_info['symbol']} (Est. Premium ₹{itm_info['estimated_premium']}, Lot Qty: {NIFTY_LOT_SIZE})"

                        # AI Confirmation
                        ai_result = gemini_analyst.analyze_signal(signal, {
                            "symbol": symbol,
                            "current_price": curr_price,
                            "option_contract": display_contract
                        })

                        # Verify if market, time cutoff, and circuit permit execution
                        can_open_trades, circuit_status_msg = daily_risk_manager.can_open_new_trade(symbol=itm_info["symbol"])
                        time_allowed = not is_after_1520 or force
                        should_execute = (is_open or force) and time_allowed and ai_result.confirmed and can_open_trades

                        # Execute Paper Order ONLY if conditions are met
                        if should_execute:
                            executed_trade = portfolio_engine.execute_signal(signal)

                        # Log Signal to Database with verified execution status
                        db = SessionLocal()
                        try:
                            log = SignalLog(
                                symbol=itm_info["symbol"],
                                strategy=strategy.name,
                                action=signal.action.value,
                                confidence=signal.confidence,
                                price=itm_info["estimated_premium"],
                                stop_loss=signal.stop_loss,
                                take_profit=signal.take_profit,
                                ai_reasoning=ai_result.reasoning,
                                ai_confirmed=ai_result.confirmed,
                                executed=bool(executed_trade is not None)
                            )
                            db.add(log)
                            db.commit()
                        finally:
                            db.close()

                        # Dispatch Telegram Alert ONLY WHEN THE BOT ACTUALLY BUYS
                        if executed_trade:
                            logger.info(f"🚀 Bot successfully bought {executed_trade.get('symbol')}. Dispatching Telegram Buy Alert...")
                            telegram_service.send_bot_buy_alert(
                                trade=executed_trade,
                                strategy=strategy.name,
                                ai_result=ai_result,
                                spot_price=curr_price
                            )
                            # Single order per scan cycle to prevent over-leveraging
                            break
                        else:
                            logger.info(
                                f"ℹ️ Signal {signal.action.value} for {itm_info['symbol']} not executed "
                                f"(AI Confirmed: {ai_result.confirmed}, Market Open: {is_open}, Time OK: {time_allowed}, Circuit OK: {can_open_trades}). "
                                f"No Telegram alert sent."
                            )

                # Mandatory Daily Trade Enforcement if no standard signal triggered and trades_today < MIN_DAILY_TRADES
                if executed_trade is None:
                    daily_stats = daily_risk_manager.get_daily_trade_stats()
                    trades_today = daily_stats.get("trades_today", 0)
                    can_open_trades, circuit_status_msg = daily_risk_manager.can_open_new_trade()
                    time_allowed = not is_after_1520 or force

                    if trades_today < settings.MIN_DAILY_TRADES and (is_open or force) and time_allowed and can_open_trades:
                        logger.info(
                            f"⚡ Mandatory Daily Trade Requirement Active ({trades_today}/{settings.MIN_DAILY_TRADES} trades taken). "
                            f"Generating Opportunistic Target Trade..."
                        )
                        opp_signal = self._evaluate_opportunistic_signal(df, symbol, curr_price)
                        signals_processed += 1

                        is_call = opp_signal.action == ActionType.BUY
                        opt_type = "CE" if is_call else "PE"
                        itm_info = get_nifty_itm_strike(curr_price, opt_type, itm_depth=1)
                        display_contract = f"{itm_info['symbol']} (Est. Premium ₹{itm_info['estimated_premium']}, Lot Qty: {NIFTY_LOT_SIZE})"

                        ai_result = gemini_analyst.analyze_signal(opp_signal, {
                            "symbol": symbol,
                            "current_price": curr_price,
                            "option_contract": display_contract,
                            "is_mandatory": True
                        })

                        executed_trade = portfolio_engine.execute_signal(opp_signal)

                        db = SessionLocal()
                        try:
                            log = SignalLog(
                                symbol=itm_info["symbol"],
                                strategy=opp_signal.strategy_name,
                                action=opp_signal.action.value,
                                confidence=opp_signal.confidence,
                                price=itm_info["estimated_premium"],
                                stop_loss=opp_signal.stop_loss,
                                take_profit=opp_signal.take_profit,
                                ai_reasoning=ai_result.reasoning,
                                ai_confirmed=ai_result.confirmed,
                                executed=bool(executed_trade is not None)
                            )
                            db.add(log)
                            db.commit()
                        finally:
                            db.close()

                        if executed_trade:
                            logger.info(f"🚀 Mandatory Daily Target Trade Executed: Bought {executed_trade.get('symbol')}. Dispatching Telegram Buy Alert...")
                            telegram_service.send_bot_buy_alert(
                                trade=executed_trade,
                                strategy=opp_signal.strategy_name,
                                ai_result=ai_result,
                                spot_price=curr_price
                            )

            except Exception as e:
                logger.error(f"Error during scan of {symbol}: {e}")

        # Check Stop-Loss and Take-Profit for open positions if market is live
        if is_open:
            sl_tp_trades = portfolio_engine.check_stop_loss_take_profit(current_prices)
            logger.info(f"=== NIFTY Scan Completed: {signals_processed} setups processed, {len(sl_tp_trades)} SL/TP exits ===")
        else:
            logger.info(f"=== NIFTY Scan Completed (Closed Session): {signals_processed} setups analyzed. ===")

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
        
        # Automated Pre-Market Session Reset (09:00 IST)
        schedule.every().day.at(settings.PRE_MARKET_RESET_TIME).do(portfolio_engine.run_pre_market_reset)
        
        # Automated Intraday EOD Auto Square-Off (15:25 IST)
        if settings.AUTO_EOD_SQUARE_OFF:
            schedule.every().day.at(settings.EOD_SQUARE_OFF_TIME).do(portfolio_engine.run_eod_square_off)
        
        # Post-Market Daily Summary (15:35 IST)
        schedule.every().day.at("15:35").do(self.run_daily_summary)
        
        # Render Free-Tier Keep-Alive Ping (Every 10 min)
        schedule.every(10).minutes.do(self._keep_alive_ping)

        logger.info(
            f"Scheduler active: scanning NIFTY every {settings.SCAN_INTERVAL_MINUTES}m | "
            f"Pre-Market Reset @ {settings.PRE_MARKET_RESET_TIME} IST | "
            f"EOD Square-Off @ {settings.EOD_SQUARE_OFF_TIME} IST | "
            f"Daily Summary @ 15:35 IST."
        )
        while self.is_running:
            schedule.run_pending()
            time.sleep(1)

    def start(self):
        """Starts the background scheduler thread."""
        if not self.is_running:
            self.is_running = True
            self._thread = threading.Thread(target=self._schedule_loop, daemon=True)
            self._thread.start()
            logger.info("Background NIFTY market scheduler thread started.")

    def stop(self):
        """Stops the background scheduler thread."""
        self.is_running = False
        if self._thread:
            self._thread.join(timeout=2)
            logger.info("Background market scheduler stopped.")


scheduler_runner = SchedulerRunner()
