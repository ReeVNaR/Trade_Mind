from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional

class BaseBroker(ABC):
    """Abstract Base Class for Broker Interface."""

    @abstractmethod
    def connect(self) -> bool:
        """Connect to broker API or initialize session."""
        pass

    @abstractmethod
    def get_balance(self) -> Dict[str, float]:
        """Returns account balance summary (total capital, available margin, used margin, PnL)."""
        pass

    @abstractmethod
    def get_positions(self) -> List[Dict[str, Any]]:
        """Returns list of active open positions."""
        pass

    @abstractmethod
    def get_orders(self) -> List[Dict[str, Any]]:
        """Returns list of active and historic orders."""
        pass

    @abstractmethod
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
        """Place order with broker."""
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel pending order."""
        pass

    @abstractmethod
    def modify_order(
        self,
        order_id: str,
        price: float = 0.0,
        trigger_price: float = 0.0,
        quantity: int = 0
    ) -> bool:
        """Modify pending order."""
        pass

    @abstractmethod
    def get_quote(self, symbol: str) -> Dict[str, Any]:
        """Returns current quote (LTP, bid, ask, volume)."""
        pass
