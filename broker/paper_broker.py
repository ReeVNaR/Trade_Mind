from typing import Dict, List, Any, Optional
from broker.base import BaseBroker
from paper_trading.simulator import PaperSimulator
from paper_trading.options_pricing import BlackScholes
from utils.logger import logger
from config.settings import settings

class PaperBroker(BaseBroker):
    """Paper Broker adapter adhering to BaseBroker interface."""

    def __init__(self, initial_capital: float = None):
        self.simulator = PaperSimulator(initial_capital=initial_capital)
        self.connected = False
        self.market_quotes: Dict[str, float] = {}

    def connect(self) -> bool:
        self.connected = True
        logger.info("PaperBroker connected successfully.")
        return True

    def set_mock_quote(self, symbol: str, price: float):
        """Sets or updates mock market price for symbol and updates pending orders."""
        self.market_quotes[symbol] = price
        self.simulator.process_tick(self.market_quotes)

    def get_balance(self) -> Dict[str, float]:
        unrealized = self.simulator.calculate_unrealized_pnl(self.market_quotes)
        return {
            "initial_capital": self.simulator.initial_capital,
            "cash_balance": round(self.simulator.cash_balance, 2),
            "used_margin": round(self.simulator.used_margin, 2),
            "available_margin": round(self.simulator.available_margin, 2),
            "realized_pnl": round(self.simulator.realized_pnl, 2),
            "unrealized_pnl": round(unrealized, 2),
            "total_portfolio_value": round(self.simulator.cash_balance + unrealized, 2)
        }

    def get_positions(self) -> List[Dict[str, Any]]:
        positions = []
        for sym, pos in self.simulator.positions.items():
            if pos["quantity"] > 0:
                ltp = self.market_quotes.get(sym, pos["average_price"])
                pnl = (ltp - pos["average_price"]) * pos["quantity"] if pos["direction"] == "BUY" else (pos["average_price"] - ltp) * pos["quantity"]
                positions.append({
                    "symbol": pos["symbol"],
                    "quantity": pos["quantity"],
                    "average_price": round(pos["average_price"], 2),
                    "direction": pos["direction"],
                    "ltp": round(ltp, 2),
                    "unrealized_pnl": round(pnl, 2)
                })
        return positions

    def get_orders(self) -> List[Dict[str, Any]]:
        return list(self.simulator.orders.values())

    def place_order(
        self,
        symbol: str,
        order_type: str,
        direction: str,
        quantity: int,
        price: float = 0.0,
        trigger_price: float = 0.0,
        tag: str = ""
    ) -> Dict[str, Any]:
        ltp = self.market_quotes.get(symbol, price)
        return self.simulator.place_order(
            symbol=symbol,
            order_type=order_type,
            direction=direction,
            quantity=quantity,
            price=price,
            trigger_price=trigger_price,
            tag=tag,
            current_ltp=ltp
        )

    def cancel_order(self, order_id: str) -> bool:
        return self.simulator.cancel_order(order_id)

    def modify_order(
        self,
        order_id: str,
        price: float = 0.0,
        trigger_price: float = 0.0,
        quantity: int = 0
    ) -> bool:
        order = self.simulator.orders.get(order_id)
        if order and order["status"] == "PENDING":
            if price > 0:
                order["price"] = price
            if trigger_price > 0:
                order["trigger_price"] = trigger_price
            if quantity > 0:
                order["quantity"] = quantity
            return True
        return False

    def get_quote(self, symbol: str) -> Dict[str, Any]:
        ltp = self.market_quotes.get(symbol, 100.0)
        return {
            "symbol": symbol,
            "ltp": ltp,
            "bid": round(ltp * 0.999, 2),
            "ask": round(ltp * 1.001, 2)
        }

    def get_option_chain(self, spot_price: float, expiry_days: int = 7, iv: float = 0.15) -> List[Dict[str, Any]]:
        """Generates synthetic option chain around spot price for NIFTY strikes."""
        step = settings.NIFTY_STRIKE_STEP # 50
        atm_strike = round(spot_price / step) * step
        strikes = [atm_strike + i * step for i in range(-5, 6)]
        
        chain = []
        T = expiry_days / 365.0
        r = 0.07 # 7% risk free rate

        for strike in strikes:
            ce_price = BlackScholes.option_price(spot_price, strike, T, r, iv, "CE")
            pe_price = BlackScholes.option_price(spot_price, strike, T, r, iv, "PE")
            ce_greeks = BlackScholes.greeks(spot_price, strike, T, r, iv, "CE")
            pe_greeks = BlackScholes.greeks(spot_price, strike, T, r, iv, "PE")

            chain.append({
                "strike": strike,
                "CE": {"symbol": f"NIFTY_{strike}_CE", "price": ce_price, "greeks": ce_greeks},
                "PE": {"symbol": f"NIFTY_{strike}_PE", "price": pe_price, "greeks": pe_greeks}
            })
        return chain
