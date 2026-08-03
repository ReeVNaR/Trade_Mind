from datetime import datetime
from sqlalchemy import Column, Integer, Float, String, DateTime, Text, Boolean, Enum
from sqlalchemy.orm import declarative_base
import enum

Base = declarative_base()


class OrderSide(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class TradeStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), index=True, nullable=False)
    side = Column(String(10), nullable=False)  # BUY / SELL
    quantity = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    strategy = Column(String(50), nullable=False, default="manual")
    status = Column(String(20), default="OPEN")  # OPEN / CLOSED
    realized_pnl = Column(Float, default=0.0)
    pnl_percent = Column(Float, default=0.0)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": round(self.quantity, 6),
            "entry_price": round(self.entry_price, 2),
            "exit_price": round(self.exit_price, 2) if self.exit_price else None,
            "stop_loss": round(self.stop_loss, 2) if self.stop_loss else None,
            "take_profit": round(self.take_profit, 2) if self.take_profit else None,
            "strategy": self.strategy,
            "status": self.status,
            "realized_pnl": round(self.realized_pnl, 2),
            "pnl_percent": round(self.pnl_percent, 2),
            "reason": self.reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
        }


class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), unique=True, index=True, nullable=False)
    quantity = Column(Float, nullable=False)
    average_entry_price = Column(Float, nullable=False)
    current_price = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    highest_price = Column(Float, nullable=True)
    trailing_stop = Column(Float, nullable=True)
    strategy = Column(String(50), default="default")
    unrealized_pnl = Column(Float, default=0.0)
    unrealized_pnl_percent = Column(Float, default=0.0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "quantity": round(self.quantity, 6),
            "average_entry_price": round(self.average_entry_price, 2),
            "current_price": round(self.current_price, 2),
            "stop_loss": round(self.stop_loss, 2) if self.stop_loss else None,
            "take_profit": round(self.take_profit, 2) if self.take_profit else None,
            "highest_price": round(self.highest_price, 2) if self.highest_price else None,
            "trailing_stop": round(self.trailing_stop, 2) if self.trailing_stop else None,
            "strategy": self.strategy,
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "unrealized_pnl_percent": round(self.unrealized_pnl_percent, 2),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }



class SignalLog(Base):
    __tablename__ = "signal_logs"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), index=True, nullable=False)
    strategy = Column(String(50), nullable=False)
    action = Column(String(10), nullable=False)  # BUY / SELL / HOLD
    confidence = Column(Float, default=0.0)
    price = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    ai_reasoning = Column(Text, nullable=True)
    ai_confirmed = Column(Boolean, default=False)
    executed = Column(Boolean, default=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "strategy": self.strategy,
            "action": self.action,
            "confidence": round(self.confidence, 2),
            "price": round(self.price, 2),
            "stop_loss": round(self.stop_loss, 2) if self.stop_loss else None,
            "take_profit": round(self.take_profit, 2) if self.take_profit else None,
            "ai_reasoning": self.ai_reasoning,
            "ai_confirmed": self.ai_confirmed,
            "executed": self.executed,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    cash_balance = Column(Float, nullable=False)
    equity = Column(Float, nullable=False)
    open_positions_count = Column(Integer, default=0)
    total_realized_pnl = Column(Float, default=0.0)
    timestamp = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "cash_balance": round(self.cash_balance, 2),
            "equity": round(self.equity, 2),
            "open_positions_count": self.open_positions_count,
            "total_realized_pnl": round(self.total_realized_pnl, 2),
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class TelegramSubscriber(Base):
    __tablename__ = "telegram_subscribers"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(String(50), unique=True, index=True, nullable=False)
    username = Column(String(100), nullable=True)
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True)  # True = receiving live alerts
    subscribed_at = Column(DateTime, default=datetime.utcnow)
    last_interaction_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "chat_id": self.chat_id,
            "username": self.username,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "is_active": self.is_active,
            "subscribed_at": self.subscribed_at.isoformat() if self.subscribed_at else None,
            "last_interaction_at": self.last_interaction_at.isoformat() if self.last_interaction_at else None,
        }

