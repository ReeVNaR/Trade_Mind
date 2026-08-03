import logging
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.config import settings, is_indian_symbol, normalize_indian_symbol
from app.database.session import get_db
from app.database.models import Trade, Position, SignalLog
from app.portfolio.engine import portfolio_engine
from app.portfolio.daily_risk import daily_risk_manager
from app.data.fetcher import data_fetcher
from app.data.nifty_options import get_nifty_itm_strike, NIFTY_LOT_SIZE
from app.indicators.technical import TechnicalIndicators, calculate_all_indicators
from app.strategies.supertrend_vwap import SupertrendVWAPStrategy
from app.strategies.trend_following import TrendFollowingStrategy
from app.strategies.rsi_reversal import RSIReversalStrategy
from app.ai.gemini_analyst import gemini_analyst
from app.backtesting.engine import backtest_engine
from app.scheduler.runner import scheduler_runner
from app.telegram.bot import telegram_service

logger = logging.getLogger(__name__)
router = APIRouter()


class BuyOrderRequest(BaseModel):
    symbol: str
    price: Optional[float] = None
    strategy: Optional[str] = "manual"


class SellOrderRequest(BaseModel):
    symbol: str
    price: Optional[float] = None
    reason: Optional[str] = "manual_exit"


class BacktestRequest(BaseModel):
    symbol: str = "^NSEI"
    strategy_name: str = "Supertrend_VWAP_Indian"
    period: str = "60d"
    interval: str = "1d"
    initial_balance: Optional[float] = 30000.0


@router.get("/health")
@router.get("/healthz")
def healthcheck():
    """Lightweight health check endpoint for uptime monitors."""
    return {
        "status": "healthy",
        "service": "TradeMind-AI",
        "version": settings.VERSION,
        "scheduler_running": scheduler_runner.is_running
    }


@router.get("/api/status")
def get_status():
    """Returns engine health, market status, and NIFTY F&O universe."""
    daily_stats = daily_risk_manager.get_daily_trade_stats()
    return {
        "status": "online",
        "project": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "currency": settings.CURRENCY_SYMBOL,
        "currency_code": settings.CURRENCY_CODE,
        "initial_balance": settings.INITIAL_BALANCE,
        "market": "NSE (National Stock Exchange of India - NIFTY F&O)",
        "market_status_ist": data_fetcher.get_market_status_ist(),
        "focus_symbol": "^NSEI",
        "max_daily_trades": settings.MAX_DAILY_TRADES,
        "max_daily_loss": settings.MAX_DAILY_LOSS,
        "max_daily_profit": settings.MAX_DAILY_PROFIT,
        "daily_risk": daily_stats,
        "scheduler_running": scheduler_runner.is_running
    }


@router.get("/api/daily-risk")
def get_daily_risk():
    """Returns today's intraday risk metrics, trade cap counter, and circuit breaker status."""
    return daily_risk_manager.get_daily_trade_stats()


@router.get("/api/nifty/fno-setup")
def get_nifty_fno_setup():
    """
    Returns live NIFTY 50 spot price, technical confluence confirmation,
    and In-The-Money (ITM) Call and Put options strike recommendations.
    """
    try:
        trace = data_fetcher.trace_live_stock("^NSEI")
        spot = trace.current_price

        itm_ce = get_nifty_itm_strike(spot, "CE", itm_depth=1)
        itm_pe = get_nifty_itm_strike(spot, "PE", itm_depth=1)

        # Calculate confluence audit
        df = data_fetcher.fetch_ohlcv("^NSEI", period="30d", interval="1d")
        strat = SupertrendVWAPStrategy()
        signal = strat.generate_signal(df, "^NSEI")

        daily_stats = daily_risk_manager.get_daily_trade_stats()

        return {
            "underlying": "NIFTY 50 Index",
            "symbol": "^NSEI",
            "spot_price": round(spot, 2),
            "change_24h": round(trace.change_24h, 2),
            "change_percent": round(trace.change_percent, 2),
            "day_high": round(trace.day_high, 2),
            "day_low": round(trace.day_low, 2),
            "currency": settings.CURRENCY_SYMBOL,
            "market_status": trace.market_status,
            "signal": signal.action.value,
            "signal_confidence": round(signal.confidence * 100.0, 1),
            "signal_reason": signal.reason,
            "itm_call": itm_ce,
            "itm_put": itm_pe,
            "recommended_trade": itm_ce if signal.action.value == "BUY" else itm_pe,
            "daily_risk": daily_stats,
            "lot_size": settings.NIFTY_LOT_SIZE,
            "capital_budget": settings.INITIAL_BALANCE
        }
    except Exception as e:
        logger.error(f"Error getting NIFTY F&O setup: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/indian-stocks")
def get_curated_stocks():
    """Returns curated stocks and benchmarks list."""
    return data_fetcher.get_curated_indian_stocks()


@router.get("/api/trace/{symbol}")
def trace_live_stock(symbol: str):
    """Traces real-time live stock metrics, exchange data, and technical indicators for an Indian equity."""
    norm_symbol = normalize_indian_symbol(symbol)
    if not is_indian_symbol(norm_symbol):
        raise HTTPException(
            status_code=400,
            detail=f"'{symbol}' is not an Indian stock. Only NSE/BSE equities (e.g. RELIANCE.NS, ^NSEI) are supported."
        )

    try:
        trace = data_fetcher.trace_live_stock(norm_symbol)
        df = data_fetcher.fetch_ohlcv(norm_symbol, period="60d", interval="1d")

        # Calculate real-time indicators
        df_ind = calculate_all_indicators(df)
        last_row = df_ind.iloc[-1]

        strat = SupertrendVWAPStrategy()
        signal = strat.generate_signal(df, norm_symbol)

        return {
            "trace": trace.to_dict(),
            "technical_indicators": {
                "vwap": round(float(last_row["vwap"]), 2),
                "rsi_14": round(float(last_row["rsi_14"]), 2),
                "supertrend": round(float(last_row["supertrend"]), 2),
                "supertrend_direction": "BULLISH" if last_row.get("supertrend_dir", 1) == 1 else "BEARISH",
                "ema_9": round(float(last_row["ema_9"]), 2),
                "ema_21": round(float(last_row["ema_21"]), 2),
                "ema_50": round(float(last_row["ema_50"]), 2),
                "ema_200": round(float(last_row.get("ema_200", last_row["close"])), 2),
                "volume_surge": round(float(last_row.get("volume_surge_ratio", 1.0)), 2),
                "macd": round(float(last_row["macd"]), 2),
                "macd_signal": round(float(last_row["macd_signal"]), 2),
            },
            "strategy_verdict": {
                "action": signal.action.value,
                "confidence": signal.confidence,
                "stop_loss": signal.stop_loss,
                "take_profit": signal.take_profit,
                "reason": signal.reason
            }
        }
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Failed to trace live exchange data for '{symbol}': {str(e)}")


@router.get("/api/confirm-setup/{symbol}")
def confirm_trade_setup(symbol: str):
    """
    Performs comprehensive 6-factor confluence & AI confirmation on NIFTY or Indian setups.
    """
    norm_symbol = normalize_indian_symbol(symbol)
    if not is_indian_symbol(norm_symbol):
        raise HTTPException(
            status_code=400,
            detail=f"'{norm_symbol}' is not a valid Indian Stock Market (NSE/BSE) symbol."
        )

    try:
        df = data_fetcher.fetch_ohlcv(norm_symbol, period="30d", interval="1d")
        if df.empty or len(df) < 15:
            raise HTTPException(status_code=400, detail="Insufficient price data to perform confirmation.")

        enriched_df = calculate_all_indicators(df)
        curr = enriched_df.iloc[-1]
        price = float(curr["close"])
        vwap = float(curr["vwap"])
        st_dir = int(curr.get("supertrend_dir", 1))
        st_band = float(curr.get("supertrend", price))
        rsi = float(curr["rsi_14"])
        atr = float(curr["atr_14"]) if "atr_14" in curr else price * 0.015
        vol_surge = float(curr.get("volume_surge_ratio", 1.0))
        ema50 = float(curr.get("ema_50", price))
        ema200 = float(curr.get("ema_200", price))

        # Checklist evaluations
        st_bullish = bool(st_dir == 1)
        vwap_bullish = bool(price >= vwap * 0.999)
        vol_confirmed = bool(vol_surge >= 1.05)
        ema_bullish = bool(price >= ema50 and price >= ema200)
        rsi_bullish = bool(48 <= rsi <= 74)

        # Run primary strategy
        st_strat = SupertrendVWAPStrategy()
        signal = st_strat.generate_signal(df, norm_symbol)

        # Run AI Confirmation
        ai_result = gemini_analyst.analyze_signal(signal, {"symbol": norm_symbol, "current_price": price, "indicators": enriched_df.iloc[-1].to_dict()})

        checklist = [
            {
                "factor": "Supertrend Direction",
                "status": "PASS" if st_bullish else "FAIL",
                "detail": f"Supertrend is {'Bullish (Green)' if st_bullish else 'Bearish (Red)'} at ₹{st_band:,.2f}"
            },
            {
                "factor": "VWAP Benchmark",
                "status": "PASS" if vwap_bullish else "FAIL",
                "detail": f"Price ₹{price:,.2f} is {'ABOVE' if vwap_bullish else 'BELOW'} VWAP ₹{vwap:,.2f}"
            },
            {
                "factor": "Institutional Volume Expansion",
                "status": "PASS" if vol_confirmed else "NEUTRAL",
                "detail": f"Volume is {vol_surge:.2f}x of 20-day Volume MA (Target >= 1.05x)"
            },
            {
                "factor": "50 & 200 EMA Baseline Filter",
                "status": "PASS" if ema_bullish else "NEUTRAL",
                "detail": f"Price vs EMA50 (₹{ema50:,.2f}) and EMA200 (₹{ema200:,.2f})"
            },
            {
                "factor": "RSI(14) Momentum Sweet-Spot",
                "status": "PASS" if rsi_bullish else "NEUTRAL",
                "detail": f"RSI is {rsi:.1f} (Optimal Bullish zone: 48 – 74)"
            },
            {
                "factor": "Gemini AI Multi-Factor Conviction",
                "status": "PASS" if ai_result.confirmed else "NEUTRAL",
                "detail": ai_result.reasoning
            }
        ]

        pass_count = sum(1 for c in checklist if c["status"] == "PASS")
        conf_pct = round((pass_count / len(checklist)) * 100.0, 1)
        is_high_conviction = conf_pct >= 66.0 and signal.action.value == "BUY"

        projected_sl = signal.stop_loss or (price - 1.5 * atr)
        projected_tp = signal.take_profit or (price + 3.5 * atr)
        risk = max(0.01, price - projected_sl)
        reward = max(0.01, projected_tp - price)
        rr_ratio = round(reward / risk, 2)

        return {
            "symbol": norm_symbol,
            "current_price": round(price, 2),
            "currency": settings.CURRENCY_SYMBOL,
            "action": signal.action.value,
            "confidence_percent": conf_pct,
            "is_high_conviction": is_high_conviction,
            "risk_reward_ratio": f"1:{rr_ratio}",
            "projected_stop_loss": round(projected_sl, 2),
            "projected_take_profit": round(projected_tp, 2),
            "trailing_stop_enabled": True,
            "checklist": checklist,
            "ai_verdict": {
                "confirmed": ai_result.confirmed,
                "confidence": ai_result.confidence_score,
                "risk_level": ai_result.risk_level,
                "reasoning": ai_result.reasoning
            }
        }

    except Exception as e:
        logger.error(f"Error in confirm_trade_setup for {norm_symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/market-data")
def get_all_market_data():
    """Returns real-time 24h market summaries for Indian watchlist symbols."""
    return data_fetcher.get_bulk_market_data(settings.DEFAULT_SYMBOLS)


@router.get("/api/portfolio")
def get_portfolio():
    """Returns real-time portfolio balance, open positions, PnL, and daily risk in ₹ INR."""
    positions = portfolio_engine.get_open_positions()
    current_prices = {}
    for p in positions:
        try:
            current_prices[p.symbol] = data_fetcher.get_current_price(p.symbol)
        except Exception:
            pass
    return portfolio_engine.get_portfolio_summary(current_prices)


@router.post("/api/portfolio/reset")
def reset_portfolio_endpoint():
    """Resets virtual portfolio to fresh ₹30,000 INR initial balance and clears positions."""
    return portfolio_engine.reset_portfolio()


@router.get("/api/trades")
def get_trades(db: Session = Depends(get_db)):
    """Returns trade execution history list."""
    trades = db.query(Trade).order_by(Trade.id.desc()).limit(50).all()
    return [t.to_dict() for t in trades]


@router.get("/api/trades/history")
def get_trades_history(limit: int = 50):
    """Returns complete trade history audit log with performance metrics, win rates, and daily risk."""
    return portfolio_engine.get_trade_performance_metrics(limit=limit)


@router.get("/api/signals")
def get_signals(db: Session = Depends(get_db)):
    """Returns recent algorithmic and AI signals."""
    signals = db.query(SignalLog).order_by(SignalLog.id.desc()).limit(50).all()
    return [s.to_dict() for s in signals]


@router.post("/api/scan")
def trigger_market_scan(background_tasks: BackgroundTasks):
    """Triggers an immediate asynchronous market scan over NIFTY 50 Index."""
    background_tasks.add_task(scheduler_runner.run_market_scan, True)
    return {"message": "NIFTY 50 market scan triggered."}


@router.post("/api/analyze/{symbol}")
def analyze_symbol(symbol: str):
    """Runs instant multi-indicator and Gemini AI analysis on an Indian symbol."""
    norm_symbol = normalize_indian_symbol(symbol)
    if not is_indian_symbol(norm_symbol):
        raise HTTPException(
            status_code=400,
            detail=f"'{symbol}' is rejected. Only Indian Stock Market (NSE/BSE) equities are supported."
        )

    df = data_fetcher.fetch_ohlcv(norm_symbol, period="15d", interval="1h")
    curr_price = data_fetcher.get_current_price(norm_symbol)

    strat = SupertrendVWAPStrategy()
    sig = strat.generate_signal(df, norm_symbol)
    ai_res = gemini_analyst.analyze_signal(sig, {"symbol": norm_symbol, "current_price": curr_price})

    return {
        "symbol": norm_symbol,
        "current_price": curr_price,
        "currency": settings.CURRENCY_SYMBOL,
        "strategy_signal": {
            "action": sig.action.value,
            "confidence": sig.confidence,
            "stop_loss": sig.stop_loss,
            "take_profit": sig.take_profit,
            "reason": sig.reason,
            "indicators": sig.indicators
        },
        "ai_analysis": ai_res.to_dict()
    }


@router.post("/api/backtest")
def run_backtest_endpoint(req: BacktestRequest):
    """Executes historical backtest on specified symbol and strategy."""
    norm_symbol = normalize_indian_symbol(req.symbol)
    if not is_indian_symbol(norm_symbol):
        raise HTTPException(
            status_code=400,
            detail="Only Indian Stock Market (NSE/BSE) symbols are supported for backtesting."
        )

    result = backtest_engine.run_backtest(
        symbol=norm_symbol,
        strategy_name=req.strategy_name,
        period=req.period,
        interval=req.interval,
        initial_balance=req.initial_balance or settings.INITIAL_BALANCE
    )
    return result.to_dict()


@router.post("/api/trade/buy")
def manual_buy(order: BuyOrderRequest):
    """Manually places a paper BUY order in ₹ INR."""
    norm_symbol = normalize_indian_symbol(order.symbol)
    price = order.price or data_fetcher.get_current_price(norm_symbol)
    if price <= 0:
        raise HTTPException(status_code=400, detail=f"Cannot fetch valid market price for {norm_symbol}")

    result = portfolio_engine.execute_buy(
        symbol=norm_symbol,
        price=price,
        strategy=order.strategy or "manual_web"
    )
    if not result:
        daily_stats = daily_risk_manager.get_daily_trade_stats()
        raise HTTPException(status_code=400, detail=f"Failed to execute buy order. {daily_stats['status_message']}")
    return result


@router.post("/api/trade/sell")
def manual_sell(order: SellOrderRequest):
    """Manually places a paper SELL order to square off position in ₹ INR."""
    norm_symbol = normalize_indian_symbol(order.symbol)
    price = order.price or data_fetcher.get_current_price(norm_symbol)
    if price <= 0:
        raise HTTPException(status_code=400, detail=f"Cannot fetch valid market price for {norm_symbol}")

    result = portfolio_engine.execute_sell(
        symbol=norm_symbol,
        price=price,
        reason=order.reason or "manual_exit_web"
    )
    if not result:
        raise HTTPException(status_code=400, detail="Failed to execute sell order. No open position found.")
    return result


class BroadcastMessageRequest(BaseModel):
    message: str


@router.get("/api/telegram/subscribers")
def get_telegram_subscribers():
    """Returns all registered Telegram bot subscribers who receive live signals."""
    subs = telegram_service.get_all_subscribers(active_only=False)
    active_subs = [s for s in subs if s.get("is_active")]
    return {
        "total_subscribers": len(subs),
        "active_subscribers": len(active_subs),
        "bot_configured": telegram_service.is_configured,
        "subscribers": subs
    }


@router.post("/api/telegram/broadcast")
def broadcast_telegram_message(req: BroadcastMessageRequest):
    """Dispatches a custom broadcast notification to ALL active Telegram subscribers."""
    if not req.message or not req.message.strip():
        raise HTTPException(status_code=400, detail="Broadcast message cannot be empty.")
    success = telegram_service.send_message(req.message.strip())
    recipients = telegram_service.get_active_chat_ids()
    return {
        "success": success,
        "recipients_count": len(recipients),
        "message": req.message.strip()
    }


@router.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


@router.get("/", response_class=HTMLResponse)
def get_dashboard():
    """Renders the TradeMind-AI NIFTY 50 Futures & Options (F&O) Dashboard."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TradeMind AI 🇮🇳 | NIFTY 50 Futures & Options (F&O) Terminal</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #070b14;
            --card-bg: rgba(15, 23, 42, 0.85);
            --card-border: rgba(255, 255, 255, 0.08);
            --card-hover: rgba(30, 41, 59, 0.95);
            --accent-saffron: #ff9933;
            --accent-green: #10b981;
            --accent-cyan: #38bdf8;
            --accent-amber: #f59e0b;
            --accent-purple: #a855f7;
            --text-primary: #f8fafc;
            --text-muted: #94a3b8;
            --bull: #10b981;
            --bear: #f43f5e;
            --highlight: #6366f1;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Outfit', -apple-system, BlinkMacSystemFont, sans-serif; }
        body { background: var(--bg); color: var(--text-primary); min-height: 100vh; padding: 24px 20px; background-image: radial-gradient(circle at 10% 10%, rgba(255, 153, 51, 0.04) 0%, transparent 40%), radial-gradient(circle at 90% 90%, rgba(16, 185, 129, 0.04) 0%, transparent 40%); }
        .container { max-width: 1480px; margin: 0 auto; }
        
        /* Header */
        header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 22px; padding-bottom: 18px; border-bottom: 1px solid var(--card-border); flex-wrap: wrap; gap: 16px; }
        .logo-group { display: flex; align-items: center; gap: 14px; }
        .logo-badge { font-size: 32px; filter: drop-shadow(0 2px 8px rgba(255, 153, 51, 0.3)); }
        .logo-title { font-size: 26px; font-weight: 800; letter-spacing: -0.5px; background: linear-gradient(135deg, #ff9933 0%, #ffffff 50%, #10b981 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .logo-sub { font-size: 12px; color: var(--text-muted); font-weight: 500; }
        
        .badge { display: inline-flex; align-items: center; gap: 6px; padding: 5px 12px; border-radius: 999px; font-size: 12px; font-weight: 600; border: 1px solid rgba(255, 255, 255, 0.1); background: rgba(255, 255, 255, 0.05); }
        .badge-live { background: rgba(16, 185, 129, 0.15); color: var(--bull); border-color: rgba(16, 185, 129, 0.35); box-shadow: 0 0 12px rgba(16, 185, 129, 0.2); }
        .badge-circuit { background: rgba(255, 153, 51, 0.15); color: var(--accent-saffron); border-color: rgba(255, 153, 51, 0.35); }
        .badge-halt { background: rgba(244, 63, 94, 0.15); color: var(--bear); border-color: rgba(244, 63, 94, 0.35); animation: pulseHalt 2s infinite; }
        .badge-subs { background: rgba(56, 189, 248, 0.12); color: var(--accent-cyan); border-color: rgba(56, 189, 248, 0.3); cursor: pointer; transition: all 0.2s ease; }
        .badge-subs:hover { background: rgba(56, 189, 248, 0.2); transform: translateY(-1px); }
        .badge-tsl { background: rgba(56, 189, 248, 0.15); color: var(--accent-cyan); border: 1px solid rgba(56, 189, 248, 0.3); font-size: 11px; padding: 2px 7px; border-radius: 4px; }
        
        @keyframes pulseHalt {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.65; }
        }

        .header-actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
        button { background: linear-gradient(135deg, #ff9933, #e67e22); color: #fff; border: none; padding: 9px 16px; border-radius: 8px; font-weight: 600; font-size: 13px; cursor: pointer; transition: all 0.2s ease; box-shadow: 0 4px 14px rgba(255, 153, 51, 0.25); display: inline-flex; align-items: center; gap: 7px; }
        button:hover { opacity: 0.94; transform: translateY(-1px); }
        button.secondary { background: rgba(255,255,255,0.06); border: 1px solid var(--card-border); box-shadow: none; color: var(--text-primary); }
        button.secondary:hover { background: rgba(255,255,255,0.12); }
        button.danger-btn { background: linear-gradient(135deg, #e11d48, #be123c); box-shadow: 0 4px 14px rgba(225, 29, 72, 0.25); }
        button.bull-btn { background: linear-gradient(135deg, #10b981, #059669); box-shadow: 0 4px 14px rgba(16, 185, 129, 0.25); }
        button.bear-btn { background: linear-gradient(135deg, #f43f5e, #e11d48); box-shadow: 0 4px 14px rgba(244, 63, 94, 0.25); }
        button.cyan-btn { background: linear-gradient(135deg, #0284c7, #0369a1); box-shadow: 0 4px 14px rgba(2, 132, 199, 0.25); }
        button.purple-btn { background: linear-gradient(135deg, #8b5cf6, #7c3aed); box-shadow: 0 4px 14px rgba(139, 92, 246, 0.25); }

        /* Expiry Alert Banner */
        .expiry-banner { display: none; background: linear-gradient(90deg, rgba(245, 158, 11, 0.15), rgba(239, 68, 68, 0.15)); border: 1px solid rgba(245, 158, 11, 0.4); border-radius: 12px; padding: 14px 20px; margin-bottom: 20px; align-items: center; justify-content: space-between; gap: 12px; }
        .expiry-banner.active { display: flex; animation: fadeIn 0.3s ease; }
        .expiry-banner-text { font-size: 13px; color: #fde68a; font-weight: 500; }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(-4px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* KPI Banner */
        .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; margin-bottom: 20px; }
        .stat-card { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 14px; padding: 18px; backdrop-filter: blur(14px); transition: all 0.2s ease; }
        .stat-card:hover { border-color: rgba(255, 255, 255, 0.15); transform: translateY(-2px); }
        .stat-label { font-size: 12px; color: var(--text-muted); text-transform: uppercase; font-weight: 600; letter-spacing: 0.6px; margin-bottom: 6px; }
        .stat-value { font-size: 24px; font-weight: 700; font-family: 'JetBrains Mono', monospace; }
        .stat-sub { font-size: 11px; color: var(--text-muted); margin-top: 6px; }
        .positive { color: var(--bull); }
        .negative { color: var(--bear); }
        
        /* Daily Circuit & Risk Bar */
        .circuit-strip { background: linear-gradient(90deg, rgba(30, 41, 59, 0.85), rgba(15, 23, 42, 0.95)); border: 1px solid var(--card-border); border-radius: 14px; padding: 18px 22px; margin-bottom: 20px; display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; align-items: center; }
        .circuit-item { display: flex; flex-direction: column; }
        .circuit-title { font-size: 11px; color: var(--text-muted); text-transform: uppercase; font-weight: 600; letter-spacing: 0.5px; margin-bottom: 4px; }
        .circuit-val { font-size: 17px; font-weight: 700; font-family: 'JetBrains Mono', monospace; }

        /* Progress Bar */
        .progress-bar-container { grid-column: 1 / -1; margin-top: 8px; }
        .progress-bar-track { height: 10px; background: rgba(255,255,255,0.08); border-radius: 999px; overflow: hidden; position: relative; }
        .progress-bar-fill { height: 100%; transition: width 0.5s ease; border-radius: 999px; }

        /* Main Grid */
        .main-grid { display: grid; grid-template-columns: 2fr 1fr; gap: 20px; margin-bottom: 20px; }
        @media (max-width: 1080px) { .main-grid { grid-template-columns: 1fr; } }
        
        .card { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 14px; padding: 20px; backdrop-filter: blur(14px); margin-bottom: 20px; }
        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 12px; }
        .card-title { font-size: 17px; font-weight: 700; display: flex; align-items: center; gap: 8px; }
        
        /* NIFTY F&O Scanner Card */
        .fno-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 14px; }
        @media (max-width: 768px) { .fno-grid { grid-template-columns: 1fr; } }
        .fno-box { border-radius: 12px; padding: 18px; border: 1px solid var(--card-border); transition: all 0.2s ease; }
        .fno-box.call { background: rgba(16, 185, 129, 0.06); border-color: rgba(16, 185, 129, 0.25); }
        .fno-box.call:hover { border-color: rgba(16, 185, 129, 0.45); background: rgba(16, 185, 129, 0.09); }
        .fno-box.put { background: rgba(244, 63, 94, 0.06); border-color: rgba(244, 63, 94, 0.25); }
        .fno-box.put:hover { border-color: rgba(244, 63, 94, 0.45); background: rgba(244, 63, 94, 0.09); }
        .fno-box-title { font-size: 15px; font-weight: 700; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; }
        .fno-detail-row { display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 8px; color: var(--text-muted); }
        .fno-detail-val { font-family: 'JetBrains Mono', monospace; font-weight: 600; color: var(--text-primary); }

        /* Checklist */
        .chk-item { display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; border-radius: 8px; margin-bottom: 8px; background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.04); font-size: 13px; }
        .chk-item.pass { border-left: 3px solid var(--bull); background: rgba(16, 185, 129, 0.05); }
        .chk-item.fail { border-left: 3px solid var(--bear); background: rgba(244, 63, 94, 0.05); }
        .chk-item.neutral { border-left: 3px solid #eab308; background: rgba(234, 179, 8, 0.05); }

        /* Tables */
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th { text-align: left; padding: 12px 10px; color: var(--text-muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid var(--card-border); }
        td { padding: 12px 10px; border-bottom: 1px solid rgba(255, 255, 255, 0.04); font-family: 'JetBrains Mono', monospace; }
        tr:hover { background: rgba(255, 255, 255, 0.02); }
        .win-badge { background: rgba(16, 185, 129, 0.15); color: var(--bull); padding: 3px 8px; border-radius: 4px; font-weight: 700; font-size: 11px; }
        .loss-badge { background: rgba(244, 63, 94, 0.15); color: var(--bear); padding: 3px 8px; border-radius: 4px; font-weight: 700; font-size: 11px; }

        /* Modals */
        .modal-overlay { display: none; position: fixed; inset: 0; background: rgba(0, 0, 0, 0.75); backdrop-filter: blur(8px); z-index: 100; align-items: center; justify-content: center; }
        .modal-overlay.open { display: flex; }
        .modal-box { background: #0f172a; border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 16px; padding: 24px; max-width: 480px; width: 90%; box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5); }
        .modal-title { font-size: 18px; font-weight: 700; margin-bottom: 10px; display: flex; align-items: center; gap: 8px; }
        .modal-body { font-size: 13px; color: var(--text-muted); line-height: 1.5; margin-bottom: 20px; }
        .modal-footer { display: flex; justify-content: flex-end; gap: 10px; }
        textarea.modal-input { width: 100%; height: 100px; background: rgba(0, 0, 0, 0.3); border: 1px solid var(--card-border); border-radius: 8px; padding: 10px; color: var(--text-primary); font-size: 13px; margin: 12px 0; resize: vertical; }
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <header>
            <div class="logo-group">
                <span class="logo-badge">🇮🇳</span>
                <div>
                    <h1 class="logo-title">TradeMind AI</h1>
                    <p class="logo-sub">NIFTY 50 Futures & Options (F&O) Terminal • August 2026 Standards (65 Lot Size • Tuesday Expiry)</p>
                </div>
            </div>
            <div class="header-actions">
                <span class="badge badge-live" id="market-status-badge">🟢 NSE LIVE</span>
                <span class="badge" id="clock-badge">⏰ IST: Loading...</span>
                <span class="badge badge-circuit" id="circuit-badge">🛡️ CIRCUIT: ACTIVE</span>
                <span class="badge badge-subs" id="telegram-subscribers-badge" onclick="openBroadcastModal()">👥 0 Bot Users</span>
                <button class="secondary" onclick="refreshDashboard()">🔄 Refresh</button>
                <button class="cyan-btn" onclick="triggerScan()">⚡ Scan NIFTY</button>
                <button class="purple-btn" onclick="openBroadcastModal()">📢 Broadcast</button>
                <button class="danger-btn" onclick="openResetModal()">🔁 Reset Portfolio</button>
            </div>
        </header>

        <!-- Expiry Cutoff Banner (Displayed on Expiry Day after 2:00 PM IST) -->
        <div class="expiry-banner" id="expiry-banner">
            <div style="display: flex; align-items: center; gap: 10px;">
                <span style="font-size: 24px;">⏳</span>
                <div>
                    <b style="color: #fbbf24; font-size: 14px;">NIFTY EXPIRES TODAY (TUESDAY) — POST-2:00 PM CUTOFF ACTIVE</b>
                    <div class="expiry-banner-text">No new buy entries permitted after 2:00 PM IST to protect capital from rapid theta decay and extreme gamma volatility. Existing positions are protected by active trailing stop-loss.</div>
                </div>
            </div>
            <span class="badge badge-halt">HALTED (POST 2PM)</span>
        </div>

        <!-- KPI Banner -->
        <div class="kpi-grid">
            <div class="stat-card">
                <div class="stat-label">Virtual Capital</div>
                <div class="stat-value" id="kpi-equity">₹30,000.00</div>
                <div class="stat-sub">Starting Baseline: <span id="kpi-initial">₹30,000.00</span></div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Available Liquid Cash</div>
                <div class="stat-value" id="kpi-cash">₹30,000.00</div>
                <div class="stat-sub" style="color: var(--accent-cyan);">35% Safe Margin / Trade (~₹10,500)</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Today's Net Realized PnL</div>
                <div class="stat-value" id="kpi-today-pnl">₹0.00</div>
                <div class="stat-sub">Floor: <span class="negative">-₹2,000</span> | Target: <span class="positive">+₹4,000</span></div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Lifetime Return & Win Rate</div>
                <div class="stat-value" id="kpi-return">+0.00%</div>
                <div class="stat-sub">Win Rate: <span id="kpi-winrate" style="font-weight: 700; color: var(--bull);">0.0%</span> • PF: <span id="hist-pf">1.00</span></div>
            </div>
            <div class="stat-card">
                <div class="stat-label">NIFTY Contract Standard</div>
                <div class="stat-value" style="color: var(--accent-saffron); font-size: 20px;">65 Units / Lot</div>
                <div class="stat-sub">Expiry: <b id="kpi-expiry-day" style="color: var(--text-primary);">Tuesday</b> • 50-pt Step</div>
            </div>
        </div>

        <!-- Daily Risk & Circuit Breaker Strip -->
        <div class="circuit-strip">
            <div class="circuit-item">
                <div class="circuit-title">Intraday Trades Taken</div>
                <div class="circuit-val" id="cir-trades">0 / 4 Trades</div>
            </div>
            <div class="circuit-item">
                <div class="circuit-title">Daily Stop-Loss Floor</div>
                <div class="circuit-val negative" id="cir-max-sl">-₹2,000.00</div>
            </div>
            <div class="circuit-item">
                <div class="circuit-title">Daily Profit Target</div>
                <div class="circuit-val positive" id="cir-max-tp">+₹4,000.00</div>
            </div>
            <div class="circuit-item">
                <div class="circuit-title">Circuit Status</div>
                <div class="circuit-val" id="cir-status" style="color: var(--bull);">ACTIVE</div>
            </div>
            <div class="progress-bar-container">
                <div style="display: flex; justify-content: space-between; font-size: 11px; color: var(--text-muted); margin-bottom: 4px;">
                    <span>-₹2,000 (Max Loss Circuit)</span>
                    <span id="cir-progress-label">₹0.00 Today's PnL</span>
                    <span>+₹4,000 (Profit Target Lock)</span>
                </div>
                <div class="progress-bar-track">
                    <div class="progress-bar-fill" id="cir-progress-fill" style="width: 33.3%; background: var(--accent-cyan);"></div>
                </div>
            </div>
        </div>

        <!-- Main Grid -->
        <div class="main-grid">
            <!-- Left Column: NIFTY F&O Live Scanner -->
            <div>
                <div class="card">
                    <div class="card-header">
                        <div class="card-title">
                            <span>🎯</span> NIFTY 50 In-The-Money (ITM) Options Scanner
                        </div>
                        <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                            <span class="badge" id="nifty-spot-badge">Spot: ₹24,950.00</span>
                            <span class="badge badge-tsl" id="nifty-lot-badge">📦 65 Units / Lot</span>
                            <span class="badge badge-tsl" id="nifty-expiry-badge">📅 Tuesday Expiry</span>
                        </div>
                    </div>
                    
                    <div style="font-size: 13px; color: var(--text-muted); margin-bottom: 12px;" id="nifty-signal-text">
                        Technical Confluence: <b>BULLISH BREAKOUT</b> above 200 EMA & VWAP.
                    </div>

                    <div class="fno-grid">
                        <!-- Bullish ITM Call Box -->
                        <div class="fno-box call">
                            <div class="fno-box-title">
                                <span style="color: var(--bull);">📈 ITM CALL OPTION (CE)</span>
                                <span class="badge badge-tsl" id="call-delta-badge">Δ ~0.72</span>
                            </div>
                            <div class="fno-detail-row">
                                <span>Contract:</span>
                                <span class="fno-detail-val" id="call-contract">NIFTY 24900 CE</span>
                            </div>
                            <div class="fno-detail-row">
                                <span>Est. Premium:</span>
                                <span class="fno-detail-val" id="call-premium">₹220.00</span>
                            </div>
                            <div class="fno-detail-row">
                                <span>1-Lot Margin (<span class="lot-qty-span">65</span> Qty):</span>
                                <span class="fno-detail-val" id="call-lot-cost">₹14,300.00</span>
                            </div>
                            <div class="fno-detail-row">
                                <span>Target (+35%) / SL (-15%):</span>
                                <span class="fno-detail-val" id="call-tp-sl">₹297.00 / ₹187.00</span>
                            </div>
                            <button class="bull-btn" id="call-buy-btn" style="width: 100%; margin-top: 10px;" onclick="executeITMOrder('CE')">
                                🚀 Paper Buy ITM Call (CE)
                            </button>
                        </div>

                        <!-- Bearish ITM Put Box -->
                        <div class="fno-box put">
                            <div class="fno-box-title">
                                <span style="color: var(--bear);">📉 ITM PUT OPTION (PE)</span>
                                <span class="badge badge-tsl" id="put-delta-badge">Δ ~ -0.71</span>
                            </div>
                            <div class="fno-detail-row">
                                <span>Contract:</span>
                                <span class="fno-detail-val" id="put-contract">NIFTY 25050 PE</span>
                            </div>
                            <div class="fno-detail-row">
                                <span>Est. Premium:</span>
                                <span class="fno-detail-val" id="put-premium">₹215.00</span>
                            </div>
                            <div class="fno-detail-row">
                                <span>1-Lot Margin (<span class="lot-qty-span">65</span> Qty):</span>
                                <span class="fno-detail-val" id="put-lot-cost">₹13,975.00</span>
                            </div>
                            <div class="fno-detail-row">
                                <span>Target (+35%) / SL (-15%):</span>
                                <span class="fno-detail-val" id="put-tp-sl">₹290.00 / ₹182.00</span>
                            </div>
                            <button class="bear-btn" id="put-buy-btn" style="width: 100%; margin-top: 10px;" onclick="executeITMOrder('PE')">
                                🛡️ Paper Buy ITM Put (PE)
                            </button>
                        </div>
                    </div>
                </div>

                <!-- Open Positions Table -->
                <div class="card">
                    <div class="card-header">
                        <div class="card-title">
                            <span>📂</span> Active NIFTY F&O Positions & Dynamic Trailing SL
                        </div>
                        <span class="badge badge-tsl" id="pos-count-badge">0 Positions</span>
                    </div>
                    <div style="overflow-x: auto;">
                        <table>
                            <thead>
                                <tr>
                                    <th>Contract / Symbol</th>
                                    <th>Qty (Units)</th>
                                    <th>Entry Price</th>
                                    <th>LTP</th>
                                    <th>Stop Loss / TSL</th>
                                    <th>Target</th>
                                    <th>Unrealized PnL</th>
                                    <th>Action</th>
                                </tr>
                            </thead>
                            <tbody id="positions-tbody">
                                <tr>
                                    <td colspan="8" style="text-align: center; color: var(--text-muted); padding: 24px;">
                                        No active positions. Scanning NIFTY 50 for high-conviction ITM setups...
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>

                <!-- Trade History Audit Table -->
                <div class="card">
                    <div class="card-header">
                        <div class="card-title">
                            <span>📜</span> Lifetime Trade Book & Execution Audit
                        </div>
                        <div style="font-size: 12px; color: var(--text-muted);">
                            Best Trade: <b id="hist-best" style="color: var(--bull);">₹0.00</b>
                        </div>
                    </div>
                    <div style="overflow-x: auto;">
                        <table>
                            <thead>
                                <tr>
                                    <th>ID</th>
                                    <th>Contract</th>
                                    <th>Side</th>
                                    <th>Entry</th>
                                    <th>Exit</th>
                                    <th>Realized PnL</th>
                                    <th>Return %</th>
                                    <th>Status / Exit Reason</th>
                                </tr>
                            </thead>
                            <tbody id="trades-tbody">
                                <tr>
                                    <td colspan="8" style="text-align: center; color: var(--text-muted); padding: 24px;">
                                        No trade history recorded yet.
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- Right Column: 6-Factor Confirmation Audit & Intraday Rules -->
            <div>
                <div class="card">
                    <div class="card-header">
                        <div class="card-title">
                            <span>🛡️</span> 6-Factor Confluence Audit
                        </div>
                        <span class="badge" id="audit-score-badge">Audit: 100%</span>
                    </div>
                    <div id="checklist-container">
                        <div class="chk-item pass">
                            <span>1. Supertrend Direction</span>
                            <span class="badge badge-live">PASS</span>
                        </div>
                        <div class="chk-item pass">
                            <span>2. Institutional VWAP Baseline</span>
                            <span class="badge badge-live">PASS</span>
                        </div>
                        <div class="chk-item pass">
                            <span>3. Volume Expansion (>= 1.05x)</span>
                            <span class="badge badge-live">PASS</span>
                        </div>
                        <div class="chk-item pass">
                            <span>4. 50 & 200 EMA Filter</span>
                            <span class="badge badge-live">PASS</span>
                        </div>
                        <div class="chk-item pass">
                            <span>5. RSI(14) Momentum Filter</span>
                            <span class="badge badge-live">PASS</span>
                        </div>
                        <div class="chk-item pass">
                            <span>6. Gemini AI Deep Reasoning</span>
                            <span class="badge badge-live">PASS</span>
                        </div>
                    </div>

                    <div style="margin-top: 14px; padding: 14px; background: rgba(255,255,255,0.03); border-radius: 8px; border: 1px solid var(--card-border);">
                        <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase; font-weight: 600; margin-bottom: 4px;">🧠 AI Reason Verdict</div>
                        <div style="font-size: 13px; color: var(--text-primary); line-height: 1.5;" id="ai-verdict-text">
                            NIFTY is in a confirmed uptrend above 200 EMA and VWAP. ITM Call options provide optimal delta and lower theta decay.
                        </div>
                    </div>
                </div>

                <!-- Daily Rules Card -->
                <div class="card">
                    <div class="card-header">
                        <div class="card-title">
                            <span>⚙️</span> Intraday Risk Circuit Rules
                        </div>
                    </div>
                    <div style="font-size: 13px; color: var(--text-muted); line-height: 1.7;">
                        <p>• <b>Universe:</b> Strictly NIFTY 50 Index (F&O)</p>
                        <p>• <b>Contract Lot Size:</b> <b style="color: var(--text-primary);">65 Units</b> (NSE August 2026)</p>
                        <p>• <b>Weekly Expiry:</b> <b style="color: var(--text-primary);">Every Tuesday</b> (15:30 IST)</p>
                        <p>• <b>Expiry 2:00 PM Cutoff:</b> <b style="color: var(--accent-amber);">No new trades after 14:00 on Tuesdays</b></p>
                        <p>• <b>Capital:</b> ₹30,000 INR (35% Max per trade)</p>
                        <p>• <b>Daily Quota:</b> 3 to 4 trades max per day</p>
                        <p>• <b>Stop-Loss Circuit:</b> -₹2,000 (10% max daily loss)</p>
                        <p>• <b>Profit Target Circuit:</b> +₹4,000 (+20% gain lock)</p>
                        <p>• <b>Strike Selection:</b> In-The-Money (ITM) Delta ~0.70</p>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Portfolio Reset Modal -->
    <div class="modal-overlay" id="reset-modal">
        <div class="modal-box">
            <div class="modal-title">
                <span>🔁</span> Reset Paper Portfolio to ₹30,000
            </div>
            <div class="modal-body">
                This will clear all open positions and historical paper trades, resetting your virtual cash balance to a pristine <b>₹30,000.00 INR</b> capital. Are you sure you want to proceed?
            </div>
            <div class="modal-footer">
                <button class="secondary" onclick="closeResetModal()">Cancel</button>
                <button class="danger-btn" onclick="confirmResetPortfolio()">Confirm Reset</button>
            </div>
        </div>
    </div>

    <!-- Telegram Broadcast Modal -->
    <div class="modal-overlay" id="broadcast-modal">
        <div class="modal-box">
            <div class="modal-title">
                <span>📢</span> Broadcast to Telegram Bot Subscribers
            </div>
            <div class="modal-body">
                Send an immediate notification message to all active subscribers who have started the Telegram bot:
                <textarea class="modal-input" id="broadcast-message" placeholder="Type your broadcast announcement or market update here..."></textarea>
            </div>
            <div class="modal-footer">
                <button class="secondary" onclick="closeBroadcastModal()">Cancel</button>
                <button class="purple-btn" onclick="confirmBroadcast()">Send Broadcast 🚀</button>
            </div>
        </div>
    </div>

    <script>
        let currentFnoSetup = null;

        function updateClock() {
            const now = new Date();
            const istString = now.toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false });
            const clockEl = document.getElementById('clock-badge');
            if (clockEl) clockEl.textContent = `⏰ ${istString} IST`;
        }
        setInterval(updateClock, 1000);
        updateClock();

        async function fetchJSON(url) {
            const res = await fetch(url);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return await res.json();
        }

        async function refreshDashboard() {
            try {
                // 1. Fetch Portfolio Summary
                const port = await fetchJSON('/api/portfolio');
                document.getElementById('kpi-equity').textContent = `₹${(port.total_equity || 30000).toLocaleString('en-IN', {minimumFractionDigits: 2})}`;
                document.getElementById('kpi-initial').textContent = `₹${(port.initial_balance || 30000).toLocaleString('en-IN', {minimumFractionDigits: 2})}`;
                document.getElementById('kpi-cash').textContent = `₹${(port.cash_balance || 30000).toLocaleString('en-IN', {minimumFractionDigits: 2})}`;
                
                const ret = port.total_return_percent || 0.0;
                const retEl = document.getElementById('kpi-return');
                retEl.textContent = `${ret >= 0 ? '+' : ''}${ret.toFixed(2)}%`;
                retEl.className = `stat-value ${ret >= 0 ? 'positive' : 'negative'}`;

                // Daily Risk Stats
                const risk = port.daily_risk || {};
                const todayPnl = risk.total_daily_pnl || 0.0;
                const pnlEl = document.getElementById('kpi-today-pnl');
                pnlEl.textContent = `${todayPnl >= 0 ? '+' : ''}₹${todayPnl.toLocaleString('en-IN', {minimumFractionDigits: 2})}`;
                pnlEl.className = `stat-value ${todayPnl >= 0 ? 'positive' : 'negative'}`;

                document.getElementById('cir-trades').textContent = `${risk.trades_today || 0} / ${risk.max_daily_trades || 4} Trades`;
                
                // Circuit Status Badge
                const cirStatus = risk.circuit_status || 'ACTIVE';
                const cirEl = document.getElementById('cir-status');
                const cirBadge = document.getElementById('circuit-badge');
                
                cirEl.textContent = cirStatus;
                if (cirStatus === 'ACTIVE') {
                    cirEl.style.color = 'var(--bull)';
                    cirBadge.className = 'badge badge-circuit';
                    cirBadge.textContent = '🛡️ CIRCUIT: ACTIVE';
                } else if (cirStatus === 'HALTED_EXPIRY_AFTER_2PM') {
                    cirEl.style.color = 'var(--accent-amber)';
                    cirBadge.className = 'badge badge-halt';
                    cirBadge.textContent = '⏳ CIRCUIT: EXPIRY POST-2PM HALT';
                } else {
                    cirEl.style.color = 'var(--bear)';
                    cirBadge.className = 'badge badge-halt';
                    cirBadge.textContent = `🛑 CIRCUIT: ${cirStatus}`;
                }

                // Check Expiry Cutoff Banner
                const expiryBanner = document.getElementById('expiry-banner');
                if (risk.is_expiry_cutoff || cirStatus === 'HALTED_EXPIRY_AFTER_2PM') {
                    expiryBanner.classList.add('active');
                } else {
                    expiryBanner.classList.remove('active');
                }

                // Progress Bar: scale from -2000 (0%) to 0 (33.3%) to +4000 (100%)
                const clamped = Math.max(-2000, Math.min(4000, todayPnl));
                const pct = ((clamped + 2000) / 6000) * 100;
                document.getElementById('cir-progress-fill').style.width = `${pct}%`;
                document.getElementById('cir-progress-label').textContent = `${todayPnl >= 0 ? '+' : ''}₹${todayPnl.toLocaleString('en-IN', {minimumFractionDigits: 2})} Today's PnL`;

                // Render Open Positions
                const posTbody = document.getElementById('positions-tbody');
                const positions = port.positions || [];
                document.getElementById('pos-count-badge').textContent = `${positions.length} Positions`;

                if (positions.length === 0) {
                    posTbody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: var(--text-muted); padding: 24px;">No active positions. Scanning NIFTY 50 for high-conviction ITM setups...</td></tr>';
                } else {
                    posTbody.innerHTML = positions.map(p => {
                        const pnl = p.unrealized_pnl || 0.0;
                        const pnlPct = p.unrealized_pnl_percent || 0.0;
                        const sign = pnl >= 0 ? '+' : '';
                        const pnlClass = pnl >= 0 ? 'positive' : 'negative';
                        return `
                            <tr>
                                <td><b>${p.symbol}</b></td>
                                <td>${p.quantity.toFixed(0)}</td>
                                <td>₹${p.average_entry_price.toFixed(2)}</td>
                                <td>₹${p.current_price.toFixed(2)}</td>
                                <td>₹${(p.trailing_stop || p.stop_loss || 0).toFixed(2)}</td>
                                <td>₹${(p.take_profit || 0).toFixed(2)}</td>
                                <td class="${pnlClass}"><b>${sign}₹${pnl.toFixed(2)} (${sign}${pnlPct.toFixed(2)}%)</b></td>
                                <td><button class="secondary" style="padding: 4px 8px; font-size: 11px;" onclick="closePosition('${p.symbol}', ${p.current_price})">Exit</button></td>
                            </tr>
                        `;
                    }).join('');
                }

                // 2. Fetch NIFTY F&O Setup
                const fno = await fetchJSON('/api/nifty/fno-setup');
                currentFnoSetup = fno;
                const lotSize = fno.lot_size || 65;

                document.getElementById('nifty-spot-badge').textContent = `Spot: ₹${fno.spot_price.toLocaleString('en-IN', {minimumFractionDigits: 2})}`;
                document.getElementById('nifty-lot-badge').textContent = `📦 ${lotSize} Units / Lot`;
                
                document.querySelectorAll('.lot-qty-span').forEach(el => el.textContent = lotSize);
                
                // ITM Call
                const call = fno.itm_call;
                document.getElementById('call-contract').textContent = call.symbol;
                document.getElementById('call-premium').textContent = `₹${call.estimated_premium.toFixed(2)}`;
                document.getElementById('call-lot-cost').textContent = `₹${call.lot_cost.toLocaleString('en-IN', {minimumFractionDigits: 2})}`;
                document.getElementById('call-delta-badge').textContent = `Δ ~${call.estimated_delta}`;
                document.getElementById('call-tp-sl').textContent = `₹${(call.estimated_premium * 1.35).toFixed(2)} / ₹${(call.estimated_premium * 0.85).toFixed(2)}`;

                // ITM Put
                const put = fno.itm_put;
                document.getElementById('put-contract').textContent = put.symbol;
                document.getElementById('put-premium').textContent = `₹${put.estimated_premium.toFixed(2)}`;
                document.getElementById('put-lot-cost').textContent = `₹${put.lot_cost.toLocaleString('en-IN', {minimumFractionDigits: 2})}`;
                document.getElementById('put-delta-badge').textContent = `Δ ~${put.estimated_delta}`;
                document.getElementById('put-tp-sl').textContent = `₹${(put.estimated_premium * 1.35).toFixed(2)} / ₹${(put.estimated_premium * 0.85).toFixed(2)}`;

                if (call.expiry_display) {
                    document.getElementById('nifty-expiry-badge').textContent = `📅 ${call.expiry_display}`;
                }

                document.getElementById('nifty-signal-text').innerHTML = `Signal: <b>${fno.signal}</b> (${fno.signal_confidence}% Conviction) | Reason: <i>${fno.signal_reason || 'Algorithmic Confluence'}</i>`;

                // 3. Fetch Trade History
                const hist = await fetchJSON('/api/trades/history');
                document.getElementById('kpi-winrate').textContent = `${(hist.win_rate_percent || 0.0).toFixed(1)}%`;
                document.getElementById('hist-pf').textContent = (hist.profit_factor || 1.0).toFixed(2);
                document.getElementById('hist-best').textContent = `₹${(hist.best_trade || 0.0).toFixed(2)}`;

                const tradesTbody = document.getElementById('trades-tbody');
                const trades = hist.trades || [];
                if (trades.length === 0) {
                    tradesTbody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: var(--text-muted); padding: 24px;">No trade history recorded yet.</td></tr>';
                } else {
                    tradesTbody.innerHTML = trades.slice(0, 15).map(t => {
                        const isClosed = t.status === 'CLOSED';
                        const pnl = t.realized_pnl || 0.0;
                        const pnlPct = t.pnl_percent || 0.0;
                        const sign = pnl >= 0 ? '+' : '';
                        const badge = !isClosed ? '<span class="badge badge-tsl">OPEN</span>' : (pnl > 0 ? '<span class="win-badge">WIN</span>' : '<span class="loss-badge">LOSS</span>');
                        return `
                            <tr>
                                <td>#${t.id}</td>
                                <td><b>${t.symbol}</b></td>
                                <td>${badge} ${t.side}</td>
                                <td>₹${t.entry_price.toFixed(2)}</td>
                                <td>${t.exit_price ? '₹' + t.exit_price.toFixed(2) : '-'}</td>
                                <td class="${pnl >= 0 ? 'positive' : 'negative'}"><b>${sign}₹${pnl.toFixed(2)}</b></td>
                                <td class="${pnlPct >= 0 ? 'positive' : 'negative'}">${sign}${pnlPct.toFixed(2)}%</td>
                                <td style="font-size: 11px; color: var(--text-muted);">${t.reason || t.status}</td>
                            </tr>
                        `;
                    }).join('');
                }

                // 4. Fetch 6-Factor Confirmation Audit on ^NSEI
                const audit = await fetchJSON('/api/confirm-setup/%5ENSEI');
                document.getElementById('audit-score-badge').textContent = `Audit: ${audit.confidence_percent}%`;
                if (audit.ai_verdict && audit.ai_verdict.reasoning) {
                    document.getElementById('ai-verdict-text').textContent = audit.ai_verdict.reasoning;
                }
                const chkContainer = document.getElementById('checklist-container');
                if (audit.checklist) {
                    chkContainer.innerHTML = audit.checklist.map(c => `
                        <div class="chk-item ${c.status.toLowerCase()}">
                            <div>
                                <b>${c.factor}</b>
                                <div style="font-size: 11px; color: var(--text-muted);">${c.detail}</div>
                            </div>
                            <span class="badge ${c.status === 'PASS' ? 'badge-live' : ''}">${c.status}</span>
                        </div>
                    `).join('');
                }

                // 5. Fetch Telegram Subscribers
                try {
                    const tgData = await fetchJSON('/api/telegram/subscribers');
                    const tgBadge = document.getElementById('telegram-subscribers-badge');
                    if (tgBadge && tgData) {
                        tgBadge.innerHTML = `👥 <b>${tgData.active_subscribers}</b> Bot Users`;
                    }
                } catch (e) {}

            } catch (err) {
                console.error("Dashboard refresh error:", err);
            }
        }

        async function executeITMOrder(optType) {
            if (!currentFnoSetup) return;
            const opt = optType === 'CE' ? currentFnoSetup.itm_call : currentFnoSetup.itm_put;
            const lotSize = currentFnoSetup.lot_size || 65;
            if (!confirm(`Execute Paper Buy for ${opt.symbol} @ Est. Premium ₹${opt.estimated_premium} (1 Lot = ${lotSize} Qty = ₹${opt.lot_cost})?`)) return;

            try {
                const res = await fetch('/api/trade/buy', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        symbol: opt.symbol,
                        price: opt.estimated_premium,
                        strategy: `ITM_${optType}_Breakout`
                    })
                });
                const data = await res.json();
                if (res.ok) {
                    alert(`✅ Order Executed: ${opt.symbol} filled at ₹${opt.estimated_premium}!`);
                    refreshDashboard();
                } else {
                    alert(`❌ Order Failed: ${data.detail || 'Circuit rejection'}`);
                }
            } catch (e) {
                alert(`Error executing order: ${e.message}`);
            }
        }

        async function closePosition(symbol, price) {
            if (!confirm(`Exit position for ${symbol} at LTP ₹${price}?`)) return;
            try {
                const res = await fetch('/api/trade/sell', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({symbol: symbol, price: price, reason: "manual_dashboard_exit"})
                });
                if (res.ok) {
                    alert(`✅ Position exited successfully!`);
                    refreshDashboard();
                } else {
                    const data = await res.json();
                    alert(`❌ Exit Failed: ${data.detail}`);
                }
            } catch (e) {
                alert(`Error: ${e.message}`);
            }
        }

        async function triggerScan() {
            try {
                await fetch('/api/scan', {method: 'POST'});
                alert('⚡ NIFTY 50 Market Scan Initiated!');
                setTimeout(refreshDashboard, 2000);
            } catch (e) {
                alert(`Scan error: ${e.message}`);
            }
        }

        // Modals Logic
        function openResetModal() {
            document.getElementById('reset-modal').classList.add('open');
        }
        function closeResetModal() {
            document.getElementById('reset-modal').classList.remove('open');
        }
        async function confirmResetPortfolio() {
            try {
                const res = await fetch('/api/portfolio/reset', {method: 'POST'});
                const data = await res.json();
                if (res.ok) {
                    alert('✅ ' + (data.message || 'Portfolio successfully reset to ₹30,000 INR!'));
                    closeResetModal();
                    refreshDashboard();
                } else {
                    alert('❌ Reset Failed: ' + (data.detail || 'Error'));
                }
            } catch (e) {
                alert('Error: ' + e.message);
            }
        }

        function openBroadcastModal() {
            document.getElementById('broadcast-modal').classList.add('open');
        }
        function closeBroadcastModal() {
            document.getElementById('broadcast-modal').classList.remove('open');
        }
        async function confirmBroadcast() {
            const msg = document.getElementById('broadcast-message').value;
            if (!msg || !msg.trim()) {
                alert('Please enter a message to broadcast.');
                return;
            }
            try {
                const res = await fetch('/api/telegram/broadcast', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({message: msg})
                });
                const data = await res.json();
                if (res.ok) {
                    alert(`✅ Broadcast delivered to ${data.recipients_count} Telegram bot users!`);
                    document.getElementById('broadcast-message').value = '';
                    closeBroadcastModal();
                } else {
                    alert('❌ Broadcast Failed: ' + (data.detail || 'Error'));
                }
            } catch (e) {
                alert('Error: ' + e.message);
            }
        }

        // Initial Load & Auto Refresh every 10 seconds
        refreshDashboard();
        setInterval(refreshDashboard, 10000);
    </script>
</body>
</html>
"""
