import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional

from app.config import settings
from app.data.fetcher import data_fetcher
from app.strategies.base import BaseStrategy, ActionType
from app.strategies.trend_following import TrendFollowingStrategy
from app.strategies.rsi_reversal import RSIReversalStrategy
from app.strategies.supertrend_vwap import SupertrendVWAPStrategy
from app.utils.logger import logger


@dataclass
class BacktestTrade:
    entry_time: str
    exit_time: str
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_percent: float
    exit_reason: str


@dataclass
class BacktestResult:
    symbol: str
    strategy_name: str
    initial_balance: float
    final_balance: float
    total_pnl: float
    total_return_percent: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_percent: float
    profit_factor: float
    max_drawdown_percent: float
    sharpe_ratio: float
    currency: str
    trades: List[Dict[str, Any]] = field(default_factory=list)
    equity_curve: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "strategy_name": self.strategy_name,
            "initial_balance": round(self.initial_balance, 2),
            "final_balance": round(self.final_balance, 2),
            "total_pnl": round(self.total_pnl, 2),
            "total_return_percent": round(self.total_return_percent, 2),
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate_percent": round(self.win_rate_percent, 2),
            "profit_factor": round(self.profit_factor, 2),
            "max_drawdown_percent": round(self.max_drawdown_percent, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "currency": self.currency,
            "trades_count": len(self.trades),
            "trades": self.trades[-20:],  # Return recent 20 for preview
            "equity_curve": self.equity_curve
        }


class BacktestEngine:
    """
    Simulates strategy performance on historical Indian and global stock data.
    Calculates institutional risk and return metrics.
    """

    STRATEGY_REGISTRY = {
        "Supertrend_VWAP_Indian": SupertrendVWAPStrategy,
        "EMA_MACD_Trend": TrendFollowingStrategy,
        "RSI_BB_Reversal": RSIReversalStrategy,
    }

    def run_backtest(
        self,
        symbol: str = "RELIANCE.NS",
        strategy_name: str = "Supertrend_VWAP_Indian",
        period: str = "60d",
        interval: str = "1h",
        initial_balance: float = None,
        df: Optional[pd.DataFrame] = None
    ) -> BacktestResult:
        """Runs historical backtest simulation."""
        balance = initial_balance or settings.INITIAL_BALANCE
        curr_balance = balance
        currency = settings.CURRENCY_SYMBOL

        strategy_cls = self.STRATEGY_REGISTRY.get(strategy_name, SupertrendVWAPStrategy)
        strategy = strategy_cls()

        if df is None:
            df = data_fetcher.fetch_ohlcv(symbol, period=period, interval=interval)

        if df.empty or len(df) < 30:
            return BacktestResult(
                symbol=symbol,
                strategy_name=strategy.name,
                initial_balance=balance,
                final_balance=balance,
                total_pnl=0.0,
                total_return_percent=0.0,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate_percent=0.0,
                profit_factor=0.0,
                max_drawdown_percent=0.0,
                sharpe_ratio=0.0,
                currency=currency
            )

        executed_trades: List[BacktestTrade] = []
        equity_curve: List[Dict[str, Any]] = []
        open_position = None  # Dict with entry_price, quantity, stop_loss, take_profit, entry_time

        peak_equity = balance
        max_drawdown = 0.0

        # Walk forward through candles (starting at index 25 to allow indicator warm-up)
        for i in range(25, len(df)):
            sub_df = df.iloc[:i + 1]
            curr_candle = df.iloc[i]
            curr_time = str(df.index[i])
            curr_price = float(curr_candle["close"])
            high_price = float(curr_candle["high"])
            low_price = float(curr_candle["low"])

            # 1. Check open position SL / TP
            if open_position:
                sl = open_position["stop_loss"]
                tp = open_position["take_profit"]
                exit_price = None
                exit_reason = None

                if sl and low_price <= sl:
                    exit_price = sl
                    exit_reason = "Stop Loss Hit"
                elif tp and high_price >= tp:
                    exit_price = tp
                    exit_reason = "Take Profit Hit"

                if exit_price:
                    gross = open_position["quantity"] * exit_price
                    cost = open_position["quantity"] * open_position["entry_price"]
                    pnl = gross - cost
                    pnl_pct = (pnl / cost) * 100.0
                    curr_balance += gross

                    executed_trades.append(BacktestTrade(
                        entry_time=open_position["entry_time"],
                        exit_time=curr_time,
                        symbol=symbol,
                        side="BUY",
                        entry_price=open_position["entry_price"],
                        exit_price=exit_price,
                        quantity=open_position["quantity"],
                        pnl=pnl,
                        pnl_percent=pnl_pct,
                        exit_reason=exit_reason
                    ))
                    open_position = None

            # 2. Evaluate Strategy Signal
            sig = strategy.generate_signal(sub_df, symbol)

            if sig.action == ActionType.BUY and not open_position and curr_balance > 100.0:
                trade_size = curr_balance * settings.MAX_POSITION_SIZE_RATIO
                qty = trade_size / curr_price
                curr_balance -= (qty * curr_price)
                open_position = {
                    "entry_price": curr_price,
                    "quantity": qty,
                    "stop_loss": sig.stop_loss or (curr_price * (1 - settings.STOP_LOSS_PERCENT)),
                    "take_profit": sig.take_profit or (curr_price * (1 + settings.TAKE_PROFIT_PERCENT)),
                    "entry_time": curr_time
                }

            elif sig.action == ActionType.SELL and open_position:
                gross = open_position["quantity"] * curr_price
                cost = open_position["quantity"] * open_position["entry_price"]
                pnl = gross - cost
                pnl_pct = (pnl / cost) * 100.0
                curr_balance += gross

                executed_trades.append(BacktestTrade(
                    entry_time=open_position["entry_time"],
                    exit_time=curr_time,
                    symbol=symbol,
                    side="BUY",
                    entry_price=open_position["entry_price"],
                    exit_price=curr_price,
                    quantity=open_position["quantity"],
                    pnl=pnl,
                    pnl_percent=pnl_pct,
                    exit_reason="Strategy Sell Signal"
                ))
                open_position = None

            # Track current equity & max drawdown
            pos_val = (open_position["quantity"] * curr_price) if open_position else 0.0
            total_equity = curr_balance + pos_val
            
            if total_equity > peak_equity:
                peak_equity = total_equity
            dd = ((peak_equity - total_equity) / peak_equity) * 100.0 if peak_equity > 0 else 0.0
            if dd > max_drawdown:
                max_drawdown = dd

            equity_curve.append({
                "time": curr_time,
                "equity": round(total_equity, 2)
            })

        # Close any remaining position at last price
        if open_position:
            last_price = float(df["close"].iloc[-1])
            gross = open_position["quantity"] * last_price
            cost = open_position["quantity"] * open_position["entry_price"]
            pnl = gross - cost
            pnl_pct = (pnl / cost) * 100.0
            curr_balance += gross
            executed_trades.append(BacktestTrade(
                entry_time=open_position["entry_time"],
                exit_time=str(df.index[-1]),
                symbol=symbol,
                side="BUY",
                entry_price=open_position["entry_price"],
                exit_price=last_price,
                quantity=open_position["quantity"],
                pnl=pnl,
                pnl_percent=pnl_pct,
                exit_reason="Backtest End Close"
            ))

        # Calculate Statistics
        total_pnl = curr_balance - balance
        total_return_pct = (total_pnl / balance) * 100.0
        total_trades_count = len(executed_trades)
        wins = [t for t in executed_trades if t.pnl > 0]
        losses = [t for t in executed_trades if t.pnl <= 0]
        winning_count = len(wins)
        losing_count = len(losses)
        win_rate = (winning_count / total_trades_count * 100.0) if total_trades_count > 0 else 0.0

        total_gain = sum(t.pnl for t in wins)
        total_loss = abs(sum(t.pnl for t in losses))
        profit_factor = (total_gain / total_loss) if total_loss > 0 else (99.0 if total_gain > 0 else 1.0)

        # Sharpe ratio estimate
        returns = [t.pnl_percent / 100.0 for t in executed_trades]
        if len(returns) > 1 and np.std(returns) > 0:
            sharpe = (np.mean(returns) / np.std(returns)) * np.sqrt(252)
        else:
            sharpe = 0.0

        return BacktestResult(
            symbol=symbol,
            strategy_name=strategy.name,
            initial_balance=balance,
            final_balance=curr_balance,
            total_pnl=total_pnl,
            total_return_percent=total_return_pct,
            total_trades=total_trades_count,
            winning_trades=winning_count,
            losing_trades=losing_count,
            win_rate_percent=win_rate,
            profit_factor=profit_factor,
            max_drawdown_percent=max_drawdown,
            sharpe_ratio=sharpe,
            currency=currency,
            trades=[t.__dict__ for t in executed_trades],
            equity_curve=equity_curve
        )


backtest_engine = BacktestEngine()
