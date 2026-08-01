from datetime import datetime
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from app.config import settings
from app.database.models import Trade, Position, PortfolioSnapshot
from app.database.session import SessionLocal, init_db
from app.strategies.base import Signal, ActionType
from app.utils.logger import logger


class PortfolioEngine:
    """
    Paper Trading and Portfolio Management Engine for Indian Stock Markets.
    Handles virtual balances in ₹ INR, order routing, position accounting, PnL calculation, and risk limits.
    """

    def __init__(self):
        self._ensure_initial_state()

    def _ensure_initial_state(self):
        init_db()
        db: Session = SessionLocal()
        try:
            snapshot = db.query(PortfolioSnapshot).order_by(PortfolioSnapshot.id.desc()).first()
            if not snapshot:
                snapshot = PortfolioSnapshot(
                    cash_balance=settings.INITIAL_BALANCE,
                    equity=settings.INITIAL_BALANCE,
                    open_positions_count=0,
                    total_realized_pnl=0.0
                )
                db.add(snapshot)
                db.commit()
        finally:
            db.close()

    def get_portfolio_summary(self, current_prices: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        """Calculates current cash, equity, open positions, unrealized PnL in ₹ INR."""
        db: Session = SessionLocal()
        try:
            latest_snapshot = db.query(PortfolioSnapshot).order_by(PortfolioSnapshot.id.desc()).first()
            cash_balance = latest_snapshot.cash_balance if latest_snapshot else settings.INITIAL_BALANCE
            realized_pnl = latest_snapshot.total_realized_pnl if latest_snapshot else 0.0

            positions = db.query(Position).all()
            positions_data = []
            total_positions_value = 0.0
            total_unrealized_pnl = 0.0

            for pos in positions:
                curr_price = (current_prices or {}).get(pos.symbol, pos.current_price)
                pos.current_price = curr_price
                market_val = pos.quantity * curr_price
                cost_basis = pos.quantity * pos.average_entry_price
                unrealized_pnl = market_val - cost_basis
                unrealized_pnl_pct = (unrealized_pnl / cost_basis * 100.0) if cost_basis > 0 else 0.0

                pos.unrealized_pnl = unrealized_pnl
                pos.unrealized_pnl_percent = unrealized_pnl_pct

                total_positions_value += market_val
                total_unrealized_pnl += unrealized_pnl

                positions_data.append(pos.to_dict())

            db.commit()

            total_equity = cash_balance + total_positions_value
            total_return_pct = ((total_equity - settings.INITIAL_BALANCE) / settings.INITIAL_BALANCE) * 100.0

            return {
                "currency": settings.CURRENCY_SYMBOL,
                "currency_code": settings.CURRENCY_CODE,
                "initial_balance": settings.INITIAL_BALANCE,
                "cash_balance": round(cash_balance, 2),
                "portfolio_value": round(total_positions_value, 2),
                "total_equity": round(total_equity, 2),
                "total_realized_pnl": round(realized_pnl, 2),
                "total_unrealized_pnl": round(total_unrealized_pnl, 2),
                "total_return_percent": round(total_return_pct, 2),
                "open_positions_count": len(positions),
                "positions": positions_data,
                "timestamp": datetime.utcnow().isoformat()
            }
        finally:
            db.close()

    def get_open_positions(self) -> List[Position]:
        """Returns list of active open positions."""
        db: Session = SessionLocal()
        try:
            return db.query(Position).all()
        finally:
            db.close()

    def execute_signal(self, signal: Signal) -> Optional[Dict[str, Any]]:
        """Executes a paper order based on an approved signal."""
        if signal.action == ActionType.BUY:
            return self.execute_buy(
                symbol=signal.symbol,
                price=signal.price,
                strategy=signal.strategy_name,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                reason=signal.reason
            )
        elif signal.action == ActionType.SELL:
            return self.execute_sell(
                symbol=signal.symbol,
                price=signal.price,
                reason=signal.reason
            )
        return None

    @staticmethod
    def calculate_indian_statutory_charges(turnover: float, is_buy: bool = True) -> float:
        """
        Calculates genuine statutory Indian trading charges (SEBI, NSE, STT, Stamp Duty, GST).
        """
        stt = turnover * 0.001  # 0.1% STT on Delivery
        exchange_charge = turnover * 0.0000345  # 0.00345% NSE Turnover Charge
        sebi_charge = turnover * 0.000001  # ₹10 per crore
        stamp_duty = (turnover * 0.00015) if is_buy else 0.0  # 0.015% Stamp duty on buy
        gst = (exchange_charge + sebi_charge) * 0.18  # 18% GST
        return round(stt + exchange_charge + sebi_charge + stamp_duty + gst, 2)

    def execute_buy(
        self,
        symbol: str,
        price: float,
        strategy: str = "manual",
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        reason: str = ""
    ) -> Optional[Dict[str, Any]]:
        """Executes a paper BUY order in ₹ INR with 1:1 realistic Indian statutory charges."""
        if price <= 0:
            logger.warning(f"Invalid buy price ₹{price} for {symbol}")
            return None

        db: Session = SessionLocal()
        try:
            snapshot = db.query(PortfolioSnapshot).order_by(PortfolioSnapshot.id.desc()).first()
            cash = snapshot.cash_balance if snapshot else settings.INITIAL_BALANCE
            
            # Risk Sizing: Max allocation per trade (15% by default)
            max_trade_amount = (cash + (snapshot.equity if snapshot else cash)) / 2 * settings.MAX_POSITION_SIZE_RATIO
            trade_amount = min(cash * 0.95, max(200.0, max_trade_amount))

            if cash < 100.0:
                logger.warning(f"Insufficient cash (₹{cash:.2f}) to buy {symbol}")
                return None

            # Apply realistic 0.05% slippage on exchange fill
            effective_price = price * 1.0005
            quantity = trade_amount / effective_price
            gross_cost = quantity * effective_price
            charges = self.calculate_indian_statutory_charges(gross_cost, is_buy=True)
            total_deduction = gross_cost + charges

            if cash < total_deduction:
                logger.warning(f"Insufficient cash for trade + charges (₹{total_deduction:.2f})")
                return None

            # Deduct cash (cost + statutory taxes)
            new_cash = cash - total_deduction

            # Check existing position
            pos = db.query(Position).filter(Position.symbol == symbol).first()
            if pos:
                new_qty = pos.quantity + quantity
                new_avg = ((pos.quantity * pos.average_entry_price) + total_deduction) / new_qty
                pos.quantity = new_qty
                pos.average_entry_price = new_avg
                pos.current_price = price
                pos.stop_loss = stop_loss or pos.stop_loss
                pos.take_profit = take_profit or pos.take_profit
            else:
                pos = Position(
                    symbol=symbol,
                    quantity=quantity,
                    average_entry_price=effective_price + (charges / quantity if quantity > 0 else 0),
                    current_price=price,
                    stop_loss=stop_loss or (price * (1 - settings.STOP_LOSS_PERCENT)),
                    take_profit=take_profit or (price * (1 + settings.TAKE_PROFIT_PERCENT)),
                    strategy=strategy
                )
                db.add(pos)

            # Record Trade
            trade = Trade(
                symbol=symbol,
                side="BUY",
                quantity=quantity,
                entry_price=effective_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                strategy=strategy,
                status="OPEN",
                reason=f"{reason} (Taxes/Charges: ₹{charges:.2f})".strip()
            )
            db.add(trade)

            # Update Snapshot
            new_snapshot = PortfolioSnapshot(
                cash_balance=new_cash,
                equity=new_cash + (quantity * price),
                open_positions_count=db.query(Position).count(),
                total_realized_pnl=snapshot.total_realized_pnl if snapshot else 0.0
            )
            db.add(new_snapshot)
            db.commit()

            logger.info(f"✅ EXECUTED BUY: {quantity:.4f} {symbol} @ ₹{effective_price:,.2f} | Charges: ₹{charges:.2f}")
            return trade.to_dict()

        except Exception as e:
            logger.error(f"Error executing buy order for {symbol}: {e}")
            db.rollback()
            return None
        finally:
            db.close()

    def execute_sell(
        self,
        symbol: str,
        price: float,
        reason: str = ""
    ) -> Optional[Dict[str, Any]]:
        """Executes a paper SELL order in ₹ INR with 1:1 realistic Indian statutory charges."""
        if price <= 0:
            return None

        db: Session = SessionLocal()
        try:
            pos = db.query(Position).filter(Position.symbol == symbol).first()
            if not pos or pos.quantity <= 0:
                logger.info(f"No open position to sell for {symbol}")
                return None

            quantity = pos.quantity
            # Apply 0.05% slippage on exit
            effective_price = price * 0.9995
            gross_proceeds = quantity * effective_price
            charges = self.calculate_indian_statutory_charges(gross_proceeds, is_buy=False)
            net_proceeds = gross_proceeds - charges

            cost_basis = quantity * pos.average_entry_price
            realized_pnl = net_proceeds - cost_basis
            pnl_percent = (realized_pnl / cost_basis * 100.0) if cost_basis > 0 else 0.0

            snapshot = db.query(PortfolioSnapshot).order_by(PortfolioSnapshot.id.desc()).first()
            current_cash = snapshot.cash_balance if snapshot else settings.INITIAL_BALANCE
            prev_total_pnl = snapshot.total_realized_pnl if snapshot else 0.0

            new_cash = current_cash + net_proceeds
            new_total_pnl = prev_total_pnl + realized_pnl

            # Remove open position
            db.delete(pos)

            # Close existing open trade in DB
            open_trade = db.query(Trade).filter(
                Trade.symbol == symbol,
                Trade.status == "OPEN"
            ).order_by(Trade.id.desc()).first()

            exit_reason = f"{reason} (STT & Charges: ₹{charges:.2f})"
            if open_trade:
                open_trade.exit_price = effective_price
                open_trade.status = "CLOSED"
                open_trade.realized_pnl = realized_pnl
                open_trade.pnl_percent = pnl_percent
                open_trade.closed_at = datetime.utcnow()
                open_trade.reason = f"{open_trade.reason or ''} | Exit: {exit_reason}".strip(" |")
            else:
                open_trade = Trade(
                    symbol=symbol,
                    side="SELL",
                    quantity=quantity,
                    entry_price=pos.average_entry_price,
                    exit_price=effective_price,
                    status="CLOSED",
                    realized_pnl=realized_pnl,
                    pnl_percent=pnl_percent,
                    reason=exit_reason,
                    closed_at=datetime.utcnow()
                )
                db.add(open_trade)

            # Update Snapshot
            new_snapshot = PortfolioSnapshot(
                cash_balance=new_cash,
                equity=new_cash,
                open_positions_count=db.query(Position).count() - 1,
                total_realized_pnl=new_total_pnl
            )
            db.add(new_snapshot)
            db.commit()

            pnl_sign = "+" if realized_pnl >= 0 else ""
            logger.info(
                f"🚨 EXECUTED SELL: {quantity:.4f} {symbol} @ ₹{effective_price:,.2f} | "
                f"Net PnL (After ₹{charges:.2f} Taxes): {pnl_sign}₹{realized_pnl:,.2f} ({pnl_sign}{pnl_percent:.2f}%)"
            )
            return open_trade.to_dict()

        except Exception as e:
            logger.error(f"Error executing sell order for {symbol}: {e}")
            db.rollback()
            return None
        finally:
            db.close()

    def check_stop_loss_take_profit(self, current_prices: Dict[str, float]) -> List[Dict[str, Any]]:
        """Scans open positions and triggers automatic exit if SL or TP thresholds are breached."""
        closed_trades = []
        db: Session = SessionLocal()
        try:
            positions = db.query(Position).all()
            for pos in positions:
                price = current_prices.get(pos.symbol)
                if not price:
                    continue

                if pos.stop_loss and price <= pos.stop_loss:
                    logger.warning(f"🛑 Stop-Loss triggered for {pos.symbol} at ₹{price:.2f} (SL: ₹{pos.stop_loss:.2f})")
                    trade = self.execute_sell(pos.symbol, price, reason=f"Stop-Loss hit (₹{pos.stop_loss:.2f})")
                    if trade:
                        closed_trades.append(trade)

                elif pos.take_profit and price >= pos.take_profit:
                    logger.info(f"🎯 Take-Profit reached for {pos.symbol} at ₹{price:.2f} (TP: ₹{pos.take_profit:.2f})")
                    trade = self.execute_sell(pos.symbol, price, reason=f"Take-Profit reached (₹{pos.take_profit:.2f})")
                    if trade:
                        closed_trades.append(trade)
        finally:
            db.close()

        return closed_trades


portfolio_engine = PortfolioEngine()
