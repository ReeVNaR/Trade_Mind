import asyncio
import threading
import time
import datetime
from typing import Optional, Dict, Any
from market_data.fetcher import MarketDataFetcher
from strategies.option_strategies import StrategyEngine
from ai_engine.decision_engine import AIDecisionEngine
from risk_management.risk_manager import RiskManager
from orders.executor import OrderExecutor
from broker.paper_broker import PaperBroker
from telegram.notifier import TelegramNotifier
from utils.logger import logger
from config.settings import settings

class LiveMarketScanner:
    """Real-time Market Data Scanner and Trade Signal Execution Engine."""

    def __init__(
        self,
        broker: Optional[PaperBroker] = None,
        risk_manager: Optional[RiskManager] = None,
        notifier: Optional[TelegramNotifier] = None
    ):
        self.fetcher = MarketDataFetcher(symbol=settings.DEFAULT_SYMBOLS)
        self.broker = broker or PaperBroker(initial_capital=settings.INITIAL_BALANCE)
        self.risk_manager = risk_manager or RiskManager()
        self.notifier = notifier or TelegramNotifier()
        self.strategy_engine = StrategyEngine()
        self.ai_engine = AIDecisionEngine(confidence_threshold=80.0)
        self.executor = OrderExecutor(broker=self.broker, risk_manager=self.risk_manager, notifier=self.notifier)
        
        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        self.last_scan_time: Optional[str] = None
        self.last_signal: Optional[Dict[str, Any]] = None

    def start(self):
        """Starts background market scanning worker thread."""
        if self.is_running:
            logger.info("LiveMarketScanner is already running.")
            return

        self.is_running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("🚀 Live Market Scanner background thread started.")
        self.notifier.notify_startup(capital=self.broker.get_balance()["cash_balance"], mode=settings.TRADING_MODE)

    def stop(self):
        """Stops background scanner thread."""
        self.is_running = False
        logger.info("LiveMarketScanner stopping.")

    def _run_loop(self):
        """Continuous background scan loop."""
        while self.is_running:
            try:
                self.run_single_scan()
            except Exception as e:
                logger.error(f"Error during market scan loop: {e}")

            # Sleep interval (e.g. 15 seconds)
            time.sleep(15)

    def run_single_scan(self) -> Dict[str, Any]:
        """Executes a single market scan cycle on real NIFTY market data."""
        self.last_scan_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 1. Fetch Live Quote and Historical Candles from yfinance
        quote = self.fetcher.get_live_quote()
        df = self.fetcher.get_historical_candles(period="5d", interval="5m")

        if df.empty or len(df) < 5:
            logger.warning("Market scan skipped: insufficient candle data.")
            return {"status": "skipped", "reason": "insufficient_data"}

        current_spot = quote["ltp"]
        self.broker.set_mock_quote("^NSEI", current_spot)

        # 2. Get Option Chain Analytics (PCR, Max Pain)
        analytics = self.fetcher.get_option_chain_analytics(spot_price=current_spot)
        analytics["vix"] = quote["vix"]

        # 3. Evaluate Technical Strategies
        candidate_signals = self.strategy_engine.evaluate(df, analytics)

        scan_summary = {
            "timestamp": self.last_scan_time,
            "spot_price": current_spot,
            "vix": quote["vix"],
            "pcr": analytics["pcr"],
            "candidates_count": len(candidate_signals),
            "executed_trade": None
        }

        # 4. Evaluate Signals via AI Engine & Execute
        for sig in candidate_signals:
            approved, ai_sig, explanation = self.ai_engine.evaluate_signal(sig, df, analytics)
            
            if approved:
                logger.info(f"AI Approved Trade Signal: {ai_sig.direction} {ai_sig.symbol} @ ₹{ai_sig.entry_price}")
                # Execute Trade (OrderExecutor sends Telegram alert automatically)
                success, trade_res, exec_msg = self.executor.execute_signal(ai_sig, ignore_time_check=True)
                
                if success:
                    self.last_signal = {
                        "symbol": ai_sig.symbol,
                        "direction": ai_sig.direction,
                        "confidence": ai_sig.confidence,
                        "entry": ai_sig.entry_price,
                        "explanation": explanation
                    }
                    scan_summary["executed_trade"] = trade_res
                    break

        # 5. Update Open Positions Mark-to-Market
        self._check_open_positions_exits(current_spot)

        return scan_summary

    def _check_open_positions_exits(self, spot_price: float):
        """Monitors active open positions for Target or Stop Loss breaches."""
        positions = self.broker.get_positions()
        for pos in positions:
            sym = pos["symbol"]
            ltp = pos["ltp"]
            
            # Simple option exit condition check
            if pos["unrealized_pnl"] >= 2000.0:
                logger.info(f"Target Hit for position {sym} (+₹{pos['unrealized_pnl']:.2f})")
                self.broker.place_order(symbol=sym, order_type="MARKET", direction="SELL", quantity=pos["quantity"])
                self.notifier.notify_risk_event("TARGET_HIT", f"Closed {sym} with profit ₹{pos['unrealized_pnl']:.2f}")

            elif pos["unrealized_pnl"] <= -1000.0:
                logger.warning(f"Stop Loss Hit for position {sym} (-₹{abs(pos['unrealized_pnl']):.2f})")
                self.broker.place_order(symbol=sym, order_type="MARKET", direction="SELL", quantity=pos["quantity"])
                self.notifier.notify_risk_event("STOP_LOSS_HIT", f"Closed {sym} with loss ₹{pos['unrealized_pnl']:.2f}")
