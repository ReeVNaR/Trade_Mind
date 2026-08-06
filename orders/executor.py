import uuid
import datetime
from typing import Dict, Any, Optional, Tuple
from broker.base import BaseBroker
from risk_management.risk_manager import RiskManager
from telegram.notifier import TelegramNotifier
from database.connection import get_db_session
from database.models import Trade, Order
from strategies.base import Signal
from utils.logger import logger

class OrderExecutor:
    """Executes trades, tracks lifecycle state, updates risk manager, and persists to database."""

    def __init__(self, broker: BaseBroker, risk_manager: RiskManager, notifier: Optional[TelegramNotifier] = None):
        self.broker = broker
        self.risk_manager = risk_manager
        self.notifier = notifier or TelegramNotifier()

    def execute_signal(self, signal: Signal, ignore_time_check: bool = False) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """Full execution lifecycle for an AI-approved signal."""
        # 1. Risk Manager check
        balance = self.broker.get_balance()
        can_trade, risk_reason = self.risk_manager.can_trade(
            available_margin=balance["available_margin"],
            ignore_time_check=ignore_time_check
        )

        if not can_trade:
            logger.warning(f"Trade Execution Blocked by Risk Manager: {risk_reason}")
            self.notifier.notify_risk_event("TRADE_BLOCKED", risk_reason)
            return False, None, risk_reason

        # 2. Duplicate order check
        active_positions = self.broker.get_positions()
        for pos in active_positions:
            if pos["symbol"] == signal.symbol:
                reason = f"Duplicate position active for {signal.symbol}"
                logger.warning(reason)
                return False, None, reason

        # 3. Position Sizing
        quantity = self.risk_manager.calculate_position_size(
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            available_margin=balance["available_margin"]
        )

        if quantity <= 0:
            reason = "Position size calculated as 0 (insufficient margin)"
            logger.warning(reason)
            return False, None, reason

        # 4. Notify Telegram of Signal
        self.notifier.notify_signal(signal)

        # 5. Place Entry Order
        order_res = self.broker.place_order(
            symbol=signal.symbol,
            order_type="MARKET",
            direction=signal.direction,
            quantity=quantity,
            price=signal.entry_price,
            tag=signal.strategy_name
        )

        if order_res["status"] != "EXECUTED":
            reason = f"Order execution failed: {order_res.get('reason', 'Broker error')}"
            logger.error(reason)
            self.notifier.notify_risk_event("ORDER_FAILED", reason)
            return False, order_res, reason

        trade_uid = f"TRD-{uuid.uuid4().hex[:8]}"
        fill_price = order_res.get("fill_price", signal.entry_price)

        # 6. Notify Telegram of Execution
        self.notifier.notify_order_execution(order_res)

        # 7. Persist to Database
        try:
            with get_db_session() as session:
                trade = Trade(
                    trade_id=trade_uid,
                    symbol=signal.symbol,
                    instrument_type=signal.instrument_type,
                    option_type=signal.option_type,
                    strike_price=signal.strike_price,
                    direction=signal.direction,
                    entry_price=fill_price,
                    quantity=quantity,
                    stop_loss=signal.stop_loss,
                    target=signal.target,
                    trailing_stop_loss=signal.stop_loss,
                    status="OPEN",
                    strategy_name=signal.strategy_name,
                    confidence_score=signal.confidence,
                    reason=signal.reason
                )
                session.add(trade)

                db_order = Order(
                    order_id=order_res["order_id"],
                    trade_id=trade_uid,
                    broker_order_id=order_res["order_id"],
                    symbol=signal.symbol,
                    order_type="MARKET",
                    direction=signal.direction,
                    price=fill_price,
                    quantity=quantity,
                    status="EXECUTED"
                )
                session.add(db_order)
            
            logger.info(f"Persisted Trade {trade_uid} to Database successfully.")
        except Exception as e:
            logger.error(f"Error persisting trade to DB: {e}")

        result_data = {
            "trade_id": trade_uid,
            "order": order_res,
            "symbol": signal.symbol,
            "quantity": quantity,
            "fill_price": fill_price
        }
        return True, result_data, "Trade executed and recorded successfully"

    def close_trade(self, trade_id: str, exit_price: float, reason: str = "TARGET_OR_SL"):
        """Closes an open trade, updates risk manager, and persists PnL."""
        with get_db_session() as session:
            trade = session.query(Trade).filter_by(trade_id=trade_id, status="OPEN").first()
            if not trade:
                logger.warning(f"Trade {trade_id} not found or already closed.")
                return

            # Place exit order with broker
            exit_direction = "SELL" if trade.direction == "BUY" else "BUY"
            exit_order = self.broker.place_order(
                symbol=trade.symbol,
                order_type="MARKET",
                direction=exit_direction,
                quantity=trade.quantity,
                price=exit_price,
                tag=f"EXIT-{reason}"
            )

            actual_exit = exit_order.get("fill_price", exit_price)

            if trade.direction == "BUY":
                pnl = (actual_exit - trade.entry_price) * trade.quantity
            else:
                pnl = (trade.entry_price - actual_exit) * trade.quantity

            roi = (pnl / (trade.entry_price * trade.quantity)) * 100.0 if trade.entry_price > 0 else 0.0

            trade.status = "CLOSED"
            trade.exit_price = actual_exit
            trade.exit_time = datetime.datetime.utcnow()
            trade.pnl = round(pnl, 2)
            trade.roi_percent = round(roi, 2)
            trade.notes = f"Closed via {reason}"

            # Update Risk Manager
            self.risk_manager.update_trade_result(pnl)

            # Notify Telegram
            msg = f"🔒 *TRADE CLOSED [{reason}]*\n\n📊 *Symbol*: `{trade.symbol}`\n💵 *Entry*: ₹{trade.entry_price:.2f} | *Exit*: ₹{actual_exit:.2f}\n💰 *PnL*: *₹{pnl:,.2f}* ({roi:.2f}%)"
            self.notifier.send_message_sync(msg)

            logger.info(f"Closed Trade {trade_id} | Exit Price: ₹{actual_exit} | PnL: ₹{pnl:.2f}")
