import datetime
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Text, Enum as SQLEnum, ForeignKey
)
from sqlalchemy.orm import declarative_base, relationship
import enum

Base = declarative_base()

class OrderStatus(str, enum.Enum):
    PENDING = "PENDING"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"

class TradeStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"

class TradeDirection(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"

class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_id = Column(String(50), unique=True, nullable=False, index=True)
    symbol = Column(String(50), nullable=False, index=True)
    instrument_type = Column(String(20), default="OPTION") # OPTION, FUTURES, SPOT
    option_type = Column(String(10), nullable=True) # CE, PE, NONE
    strike_price = Column(Float, nullable=True)
    expiry = Column(String(20), nullable=True)
    direction = Column(String(10), nullable=False) # BUY / SELL
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    quantity = Column(Integer, nullable=False)
    stop_loss = Column(Float, nullable=False)
    target = Column(Float, nullable=False)
    trailing_stop_loss = Column(Float, nullable=True)
    status = Column(String(20), default="OPEN", index=True) # OPEN, CLOSED, CANCELLED
    pnl = Column(Float, default=0.0)
    roi_percent = Column(Float, default=0.0)
    strategy_name = Column(String(50), nullable=False)
    confidence_score = Column(Float, nullable=False)
    entry_time = Column(DateTime, default=datetime.datetime.utcnow)
    exit_time = Column(DateTime, nullable=True)
    reason = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)

    orders = relationship("Order", back_populates="trade", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Trade(id={self.trade_id}, symbol={self.symbol}, status={self.status}, pnl={self.pnl})>"

class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(50), unique=True, nullable=False, index=True)
    trade_id = Column(String(50), ForeignKey("trades.trade_id"), nullable=False)
    broker_order_id = Column(String(100), nullable=True)
    symbol = Column(String(50), nullable=False)
    order_type = Column(String(20), nullable=False) # MARKET, LIMIT, SL-M
    direction = Column(String(10), nullable=False) # BUY, SELL
    price = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False)
    status = Column(String(20), default="PENDING")
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    trade = relationship("Trade", back_populates="orders")

class LogRecord(Base):
    __tablename__ = "logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    level = Column(String(20), nullable=False)
    message = Column(Text, nullable=False)
    module = Column(String(100), nullable=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, index=True)

class DailyReport(Base):
    __tablename__ = "daily_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String(20), unique=True, nullable=False, index=True) # YYYY-MM-DD
    total_trades = Column(Integer, default=0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    win_rate = Column(Float, default=0.0)
    net_pnl = Column(Float, default=0.0)
    roi_percent = Column(Float, default=0.0)
    max_drawdown = Column(Float, default=0.0)
    best_trade_pnl = Column(Float, default=0.0)
    worst_trade_pnl = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class RiskEvent(Base):
    __tablename__ = "risk_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(50), nullable=False)
    message = Column(Text, nullable=False)
    severity = Column(String(20), default="WARNING") # INFO, WARNING, CRITICAL
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, index=True)

class StrategyPerformance(Base):
    __tablename__ = "strategy_performance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_name = Column(String(50), unique=True, nullable=False)
    total_trades = Column(Integer, default=0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    total_pnl = Column(Float, default=0.0)
    win_rate = Column(Float, default=0.0)
    profit_factor = Column(Float, default=0.0)
    last_updated = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
