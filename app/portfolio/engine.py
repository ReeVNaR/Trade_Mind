from datetime import datetime
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from app.config import settings
from app.database.models import Trade, Position, PortfolioSnapshot
from app.database.session import SessionLocal, init_db
from app.strategies.base import Signal, ActionType
from app.data.nifty_options import get_nifty_itm_strike, NIFTY_LOT_SIZE
from app.portfolio.daily_risk import daily_risk_manager
from app.utils.logger import logger


class PortfolioEngine:
    """
    Paper Trading and Portfolio Management Engine for NIFTY F&O and Indian Markets.
    Handles virtual balances in ₹ INR (₹30,000 initial capital), order routing,
    In-The-Money (ITM) option contracts, daily risk circuit breakers, and position accounting.
    """

    def __init__(self):
        self._ensure_initial_state()

    def reset_portfolio(self, initial_capital: float = settings.INITIAL_BALANCE) -> Dict[str, Any]:
        """Resets the paper trading portfolio balance to initial capital (₹30,000 INR) and clears open positions."""
        init_db()
        db: Session = SessionLocal()
        try:
            db.query(Position).delete()
            db.query(PortfolioSnapshot).delete()
            db.query(Trade).delete()

            clean_snapshot = PortfolioSnapshot(
                cash_balance=initial_capital,
                equity=initial_capital,
                open_positions_count=0,
                total_realized_pnl=0.0
            )
            db.add(clean_snapshot)
            db.commit()
            logger.info(f"🔄 Portfolio successfully reset to initial capital: ₹{initial_capital:,.2f}")
        finally:
            db.close()

        return self.get_portfolio_summary()

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
            elif snapshot.cash_balance < settings.INITIAL_BALANCE and db.query(Position).count() == 0:
                # Synchronize to ₹30,000 initial capital
                snapshot.cash_balance = settings.INITIAL_BALANCE
                snapshot.equity = settings.INITIAL_BALANCE
                db.commit()
        finally:
            db.close()

    def get_portfolio_summary(self, current_prices: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        """Calculates current cash, equity, open positions, unrealized PnL, and daily circuit stats in ₹ INR."""
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

            # Daily Risk & Circuit Breaker status
            daily_stats = daily_risk_manager.get_daily_trade_stats(db)

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
                "daily_risk": daily_stats,
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

    def get_position(self, symbol: str) -> Optional[Position]:
        """Returns active position for a specific symbol, if open."""
        db: Session = SessionLocal()
        try:
            return db.query(Position).filter(Position.symbol == symbol).first()
        finally:
            db.close()

    def execute_signal(self, signal: Signal) -> Optional[Dict[str, Any]]:
        """
        Executes a paper order based on an approved signal.
        For NIFTY Index signals:
        - BUY (Bullish) -> Routes to In-The-Money Call Option (NIFTY [Strike] CE)
        - SELL (Bearish) -> Routes to In-The-Money Put Option (NIFTY [Strike] PE)
        """
        symbol = signal.symbol.upper()
        is_nifty_index = symbol in ["^NSEI", "NIFTY", "NIFTY50", "NIFTY 50"]

        if is_nifty_index:
            if signal.action == ActionType.BUY:
                itm = get_nifty_itm_strike(signal.price, "CE", itm_depth=1)
                opt_symbol = itm["symbol"]
                premium = itm["estimated_premium"]
                # 15% SL, 35% TP on option premium
                opt_sl = round(premium * 0.85, 2)
                opt_tp = round(premium * 1.35, 2)
                reason = f"{signal.reason} | ITM Call (Spot ₹{signal.price:,.2f}, Strike {itm['strike_price']} CE, Delta {itm['estimated_delta']})"
                return self.execute_buy(
                    symbol=opt_symbol,
                    price=premium,
                    strategy=signal.strategy_name,
                    stop_loss=opt_sl,
                    take_profit=opt_tp,
                    reason=reason
                )
            elif signal.action == ActionType.SELL:
                # First check if an open CE or index position exists to close
                open_pos = self.get_position(signal.symbol)
                if open_pos:
                    return self.execute_sell(symbol=signal.symbol, price=signal.price, reason=signal.reason)

                # Check if any open CE option exists to exit
                db = SessionLocal()
                try:
                    ce_pos = db.query(Position).filter(Position.symbol.like("NIFTY%CE%")).first()
                    if ce_pos:
                        return self.execute_sell(symbol=ce_pos.symbol, price=ce_pos.current_price, reason="Bearish Nifty Reversal Exit")
                finally:
                    db.close()

                # In Options Buying: A Bearish signal is captured by buying ITM PUT (PE) for maximum profit!
                itm = get_nifty_itm_strike(signal.price, "PE", itm_depth=1)
                opt_symbol = itm["symbol"]
                premium = itm["estimated_premium"]
                opt_sl = round(premium * 0.85, 2)
                opt_tp = round(premium * 1.35, 2)
                reason = f"{signal.reason} | ITM Put (Spot ₹{signal.price:,.2f}, Strike {itm['strike_price']} PE, Delta {itm['estimated_delta']})"
                return self.execute_buy(
                    symbol=opt_symbol,
                    price=premium,
                    strategy=signal.strategy_name,
                    stop_loss=opt_sl,
                    take_profit=opt_tp,
                    reason=reason
                )
        else:
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
        stt = turnover * 0.001  # 0.1% STT on Delivery / F&O exercise
        exchange_charge = turnover * 0.0005  # 0.05% NSE Option Turnover Charge
        sebi_charge = turnover * 0.000001  # ₹10 per crore
        stamp_duty = (turnover * 0.00003) if is_buy else 0.0  # 0.003% Stamp duty on F&O buy
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
        """
        Executes a paper BUY order in ₹ INR with Daily Risk Circuit validation
        and NIFTY F&O lot sizing.
        """
        if price <= 0:
            logger.warning(f"Invalid buy price ₹{price} for {symbol}")
            return None

        # --- Check Daily Risk Circuit Breaker ---
        can_trade, circuit_msg = daily_risk_manager.can_open_new_trade()
        if not can_trade:
            logger.warning(f"🚫 BUY ORDER REJECTED by Daily Circuit: {circuit_msg}")
            return None

        db: Session = SessionLocal()
        try:
            snapshot = db.query(PortfolioSnapshot).order_by(PortfolioSnapshot.id.desc()).first()
            cash = snapshot.cash_balance if snapshot else settings.INITIAL_BALANCE

            # Sizing: Max position allocation (35% margin per trade out of ₹30,000)
            max_trade_amount = (cash + (snapshot.equity if snapshot else cash)) / 2 * settings.MAX_POSITION_SIZE_RATIO
            trade_amount = min(cash * 0.95, max(500.0, max_trade_amount))

            if cash < 200.0:
                logger.warning(f"Insufficient cash (₹{cash:.2f}) to buy {symbol}")
                return None

            # Apply realistic 0.05% slippage on fill
            effective_price = price * 1.0005

            # If symbol is a NIFTY Option contract, align quantity to lot size (25)
            is_option = symbol.startswith("NIFTY") and (" CE" in symbol or " PE" in symbol or symbol.endswith("CE") or symbol.endswith("PE"))
            if is_option and price < 5000:
                lot_cost = effective_price * NIFTY_LOT_SIZE
                lots = max(1, int(trade_amount // lot_cost)) if lot_cost > 0 else 1
                # Ensure cash buffer
                while lots * lot_cost > cash * 0.95 and lots > 1:
                    lots -= 1
                quantity = float(lots * NIFTY_LOT_SIZE)
            else:
                quantity = trade_amount / effective_price

            gross_cost = quantity * effective_price
            charges = self.calculate_indian_statutory_charges(gross_cost, is_buy=True)
            total_deduction = gross_cost + charges

            if cash < total_deduction:
                logger.warning(f"Insufficient cash for trade + charges (₹{total_deduction:.2f} > ₹{cash:.2f})")
                return None

            # Deduct cash
            new_cash = cash - total_deduction

            # Check existing position
            pos = db.query(Position).filter(Position.symbol == symbol).first()
            if pos:
                new_qty = pos.quantity + quantity
                new_avg = ((pos.quantity * pos.average_entry_price) + total_deduction) / new_qty
                pos.quantity = new_qty
                pos.average_entry_price = new_avg
                pos.current_price = price
                pos.highest_price = max(pos.highest_price or price, price)
                pos.stop_loss = stop_loss or pos.stop_loss
                pos.take_profit = take_profit or pos.take_profit
            else:
                pos = Position(
                    symbol=symbol,
                    quantity=quantity,
                    average_entry_price=effective_price + (charges / quantity if quantity > 0 else 0),
                    current_price=price,
                    highest_price=price,
                    trailing_stop=None,
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

            logger.info(f"✅ EXECUTED BUY: {quantity:.0f} {symbol} @ ₹{effective_price:,.2f} | Charges: ₹{charges:.2f}")
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
                f"🚨 EXECUTED SELL: {quantity:.0f} {symbol} @ ₹{effective_price:,.2f} | "
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
        """
        Scans open positions, applies Dynamic Trailing Stop-Loss (TSL) to let profits run,
        and triggers automatic exit if SL or TP thresholds are breached.
        """
        closed_trades = []
        positions_to_close = []
        db: Session = SessionLocal()
        try:
            positions = db.query(Position).all()
            for pos in positions:
                price = current_prices.get(pos.symbol)
                if not price:
                    continue

                pos.current_price = price
                # Track highest price recorded during trade lifecycle
                if not pos.highest_price or price > pos.highest_price:
                    pos.highest_price = price

                # --- Dynamic Trailing Stop-Loss (TSL) ---
                # When profit >= 1.5%, ratchet trailing stop to protect gains
                profit_from_entry_pct = ((price - pos.average_entry_price) / pos.average_entry_price) * 100.0
                if profit_from_entry_pct >= 1.5:
                    trail_level = max(pos.average_entry_price * 1.008, pos.highest_price * 0.98)
                    if not pos.trailing_stop or trail_level > pos.trailing_stop:
                        pos.trailing_stop = trail_level
                        pos.stop_loss = max(pos.stop_loss or 0.0, trail_level)
                        logger.info(f"📈 Trailing Stop-Loss ratcheted for {pos.symbol} to ₹{trail_level:,.2f} (Peak ₹{pos.highest_price:,.2f})")

                # Check SL / Trailing Stop Trigger
                if pos.stop_loss and price <= pos.stop_loss:
                    is_tsl = bool(pos.trailing_stop and pos.stop_loss >= pos.average_entry_price)
                    if is_tsl:
                        exit_msg = f"Trailing Stop-Loss triggered at ₹{price:.2f} (Locked Gain from peak ₹{pos.highest_price:.2f})"
                        logger.info(f"🛡️ {exit_msg} for {pos.symbol}")
                    else:
                        exit_msg = f"Stop-Loss hit at ₹{price:.2f} (SL: ₹{pos.stop_loss:.2f})"
                        logger.warning(f"🛑 {exit_msg} for {pos.symbol}")

                    positions_to_close.append((pos.symbol, price, exit_msg))

                # Check Take-Profit Trigger
                elif pos.take_profit and price >= pos.take_profit:
                    logger.info(f"🎯 Take-Profit reached for {pos.symbol} at ₹{price:.2f} (TP: ₹{pos.take_profit:.2f})")
                    positions_to_close.append((pos.symbol, price, f"Take-Profit reached (₹{pos.take_profit:.2f})"))

            db.commit()
        finally:
            db.close()

        # Execute sell orders independently without session conflict
        for sym, p, msg in positions_to_close:
            trade = self.execute_sell(sym, p, reason=msg)
            if trade:
                closed_trades.append(trade)

        return closed_trades

    def get_trade_performance_metrics(self, limit: int = 100) -> Dict[str, Any]:
        """Calculates comprehensive trade performance and win-rate metrics for dashboard & Telegram."""
        db: Session = SessionLocal()
        try:
            trades = db.query(Trade).filter(Trade.status == "CLOSED").order_by(Trade.id.desc()).all()
            total_closed = len(trades)

            wins = [t for t in trades if (t.realized_pnl or 0.0) > 0]
            losses = [t for t in trades if (t.realized_pnl or 0.0) <= 0]

            winning_count = len(wins)
            losing_count = len(losses)

            win_rate = (winning_count / total_closed * 100.0) if total_closed > 0 else 0.0
            total_pnl = sum((t.realized_pnl or 0.0) for t in trades)

            gross_profit = sum((t.realized_pnl or 0.0) for t in wins)
            gross_loss = abs(sum((t.realized_pnl or 0.0) for t in losses))

            profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 1.0)
            avg_win = (gross_profit / winning_count) if winning_count > 0 else 0.0
            avg_loss = (gross_loss / losing_count) if losing_count > 0 else 0.0
            best_trade = max([(t.realized_pnl or 0.0) for t in trades], default=0.0)

            all_trades_raw = db.query(Trade).order_by(Trade.id.desc()).limit(limit).all()
            trades_list = [t.to_dict() for t in all_trades_raw]

            daily_stats = daily_risk_manager.get_daily_trade_stats(db)

            return {
                "currency": settings.CURRENCY_SYMBOL,
                "total_trades": total_closed,
                "winning_trades": winning_count,
                "losing_trades": losing_count,
                "win_rate_percent": round(win_rate, 2),
                "total_realized_pnl": round(total_pnl, 2),
                "gross_profit": round(gross_profit, 2),
                "gross_loss": round(gross_loss, 2),
                "profit_factor": round(profit_factor, 2),
                "average_win": round(avg_win, 2),
                "average_loss": round(avg_loss, 2),
                "best_trade": round(best_trade, 2),
                "daily_risk": daily_stats,
                "trades": trades_list
            }
        finally:
            db.close()


portfolio_engine = PortfolioEngine()
