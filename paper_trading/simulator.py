import uuid
import datetime
from typing import Dict, List, Any, Optional
from config.settings import settings
from utils.logger import logger

class PaperSimulator:
    """In-memory Paper Trading Engine for simulating F&O order execution, PnL & Margin."""

    def __init__(self, initial_capital: float = None):
        self.initial_capital = initial_capital or settings.INITIAL_BALANCE
        self.cash_balance = self.initial_capital
        self.used_margin = 0.0
        self.realized_pnl = 0.0
        self.orders: Dict[str, Dict[str, Any]] = {}
        self.positions: Dict[str, Dict[str, Any]] = {}

    @property
    def available_margin(self) -> float:
        return self.cash_balance - self.used_margin

    @property
    def total_portfolio_value(self) -> float:
        return self.cash_balance + self.calculate_unrealized_pnl()

    def calculate_unrealized_pnl(self, current_quotes: Dict[str, float] = None) -> float:
        """Calculates total unrealized PnL based on current market quotes."""
        unrealized = 0.0
        quotes = current_quotes or {}
        for symbol, pos in self.positions.items():
            if pos["quantity"] == 0:
                continue
            ltp = quotes.get(symbol, pos["average_price"])
            if pos["direction"] == "BUY":
                unrealized += (ltp - pos["average_price"]) * pos["quantity"]
            else:
                unrealized += (pos["average_price"] - ltp) * pos["quantity"]
        return unrealized

    def place_order(
        self,
        symbol: str,
        order_type: str,
        direction: str,
        quantity: int,
        price: float = 0.0,
        trigger_price: float = 0.0,
        tag: str = "",
        current_ltp: float = 0.0
    ) -> Dict[str, Any]:
        """Places a new simulated order."""
        order_id = f"PAPER-ORD-{uuid.uuid4().hex[:8]}"
        
        # Calculate required margin (for Option Buying: full premium; Option Selling / Futures: margin percentage)
        exec_price = price if price > 0 else current_ltp
        required_margin = exec_price * quantity

        if direction == "BUY" and required_margin > self.available_margin:
            logger.warning(
                f"Order rejected: Insufficient margin. Required ₹{required_margin:.2f}, Available ₹{self.available_margin:.2f}"
            )
            order_data = {
                "order_id": order_id,
                "symbol": symbol,
                "order_type": order_type,
                "direction": direction,
                "quantity": quantity,
                "price": price,
                "trigger_price": trigger_price,
                "status": "REJECTED",
                "reason": "Insufficient margin",
                "created_at": datetime.datetime.utcnow().isoformat()
            }
            self.orders[order_id] = order_data
            return order_data

        order_data = {
            "order_id": order_id,
            "symbol": symbol,
            "order_type": order_type,
            "direction": direction,
            "quantity": quantity,
            "price": price,
            "trigger_price": trigger_price,
            "status": "PENDING",
            "tag": tag,
            "created_at": datetime.datetime.utcnow().isoformat(),
            "executed_at": None,
            "fill_price": 0.0
        }

        self.orders[order_id] = order_data

        # If MARKET order, execute immediately
        if order_type.upper() == "MARKET":
            self._execute_order(order_id, exec_price)

        return self.orders[order_id]

    def _execute_order(self, order_id: str, fill_price: float):
        """Executes an order and updates position & margin."""
        order = self.orders.get(order_id)
        if not order or order["status"] != "PENDING":
            return

        # Simulate 0.05% slippage on market fills
        slippage_pct = 0.0005
        if order["direction"] == "BUY":
            actual_fill = round(fill_price * (1 + slippage_pct), 2)
        else:
            actual_fill = round(fill_price * (1 - slippage_pct), 2)

        order["status"] = "EXECUTED"
        order["fill_price"] = actual_fill
        order["executed_at"] = datetime.datetime.utcnow().isoformat()

        symbol = order["symbol"]
        qty = order["quantity"]
        direction = order["direction"]
        total_cost = actual_fill * qty

        # Update position
        if symbol not in self.positions:
            self.positions[symbol] = {
                "symbol": symbol,
                "quantity": 0,
                "average_price": 0.0,
                "direction": direction,
                "realized_pnl": 0.0
            }

        pos = self.positions[symbol]

        if pos["quantity"] == 0:
            pos["quantity"] = qty
            pos["average_price"] = actual_fill
            pos["direction"] = direction
            if direction == "BUY":
                self.used_margin += total_cost
        elif pos["direction"] == direction:
            # Add to existing position
            new_qty = pos["quantity"] + qty
            pos["average_price"] = ((pos["average_price"] * pos["quantity"]) + total_cost) / new_qty
            pos["quantity"] = new_qty
            if direction == "BUY":
                self.used_margin += total_cost
        else:
            # Closing / reducing position
            close_qty = min(pos["quantity"], qty)
            if pos["direction"] == "BUY":
                pnl = (actual_fill - pos["average_price"]) * close_qty
                self.used_margin = max(0.0, self.used_margin - (pos["average_price"] * close_qty))
            else:
                pnl = (pos["average_price"] - actual_fill) * close_qty

            self.realized_pnl += pnl
            self.cash_balance += pnl
            pos["realized_pnl"] += pnl
            pos["quantity"] -= close_qty

            if pos["quantity"] == 0:
                pos["average_price"] = 0.0

        logger.info(
            f"Executed Order {order_id} | {direction} {qty} {symbol} @ ₹{actual_fill} | Realized PnL: ₹{self.realized_pnl:.2f}"
        )

    def process_tick(self, quotes: Dict[str, float]):
        """Processes current prices to check pending limit/stop orders."""
        for order_id, order in list(self.orders.items()):
            if order["status"] != "PENDING":
                continue
            symbol = order["symbol"]
            if symbol not in quotes:
                continue
            ltp = quotes[symbol]

            if order["order_type"] == "LIMIT":
                if order["direction"] == "BUY" and ltp <= order["price"]:
                    self._execute_order(order_id, order["price"])
                elif order["direction"] == "SELL" and ltp >= order["price"]:
                    self._execute_order(order_id, order["price"])

            elif order["order_type"] == "SL-M":
                if order["direction"] == "BUY" and ltp >= order["trigger_price"]:
                    self._execute_order(order_id, ltp)
                elif order["direction"] == "SELL" and ltp <= order["trigger_price"]:
                    self._execute_order(order_id, ltp)

    def cancel_order(self, order_id: str) -> bool:
        if order_id in self.orders and self.orders[order_id]["status"] == "PENDING":
            self.orders[order_id]["status"] = "CANCELLED"
            return True
        return False
