from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

from app.config import settings, is_indian_symbol, normalize_indian_symbol
from app.database.session import get_db
from app.database.models import Trade, Position, SignalLog
from app.portfolio.engine import portfolio_engine
from app.data.fetcher import data_fetcher
from app.indicators.technical import TechnicalIndicators, calculate_all_indicators
from app.strategies.supertrend_vwap import SupertrendVWAPStrategy
from app.strategies.trend_following import TrendFollowingStrategy
from app.strategies.rsi_reversal import RSIReversalStrategy
from app.ai.gemini_analyst import gemini_analyst
from app.backtesting.engine import backtest_engine
from app.scheduler.runner import scheduler_runner

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
    symbol: str = "RELIANCE.NS"
    strategy_name: str = "Supertrend_VWAP_Indian"
    period: str = "60d"
    interval: str = "1h"
    initial_balance: Optional[float] = 2000.0


@router.get("/health")
@router.get("/healthz")
def healthcheck():
    """Lightweight health check endpoint for Render and uptime monitors."""
    return {
        "status": "healthy",
        "service": "TradeMind-AI",
        "version": settings.VERSION,
        "scheduler_running": scheduler_runner.is_running
    }


@router.get("/api/status")
def get_status():
    """Returns engine health, market status, and Indian watchlist."""
    return {
        "status": "online",
        "project": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "currency": settings.CURRENCY_SYMBOL,
        "currency_code": settings.CURRENCY_CODE,
        "initial_balance": settings.INITIAL_BALANCE,
        "market": "NSE / BSE (National Stock Exchange of India)",
        "market_status_ist": data_fetcher.get_market_status_ist(),
        "watchlist": settings.DEFAULT_SYMBOLS,
        "scheduler_running": scheduler_runner.is_running
    }


@router.get("/api/indian-stocks")
def get_curated_stocks():
    """Returns the list of top Indian equities and benchmarks."""
    return data_fetcher.get_curated_indian_stocks()


@router.get("/api/trace/{symbol}")
def trace_live_stock(symbol: str):
    """Traces real-time live stock metrics, exchange data, and technical indicators for an Indian equity."""
    norm_symbol = normalize_indian_symbol(symbol)
    if not is_indian_symbol(norm_symbol):
        raise HTTPException(
            status_code=400,
            detail=f"'{symbol}' is not an Indian stock. Only NSE/BSE equities (e.g. RELIANCE.NS, TCS.NS) are supported."
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
                "supertrend_direction": "BULLISH" if last_row["supertrend_direction"] == 1 else "BEARISH",
                "ema_9": round(float(last_row["ema_9"]), 2),
                "ema_21": round(float(last_row["ema_21"]), 2),
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


@router.get("/api/market-data")
def get_all_market_data():
    """Returns real-time 24h market summaries for Indian watchlist symbols."""
    return data_fetcher.get_bulk_market_data(settings.DEFAULT_SYMBOLS)


@router.get("/api/portfolio")
def get_portfolio():
    """Returns real-time portfolio balance, open positions, and PnL in ₹ INR."""
    positions = portfolio_engine.get_open_positions()
    current_prices = {}
    for p in positions:
        try:
            current_prices[p.symbol] = data_fetcher.get_current_price(p.symbol)
        except Exception:
            pass
    return portfolio_engine.get_portfolio_summary(current_prices)


@router.get("/api/trades")
def get_trades(db: Session = Depends(get_db)):
    """Returns trade execution history."""
    trades = db.query(Trade).order_by(Trade.id.desc()).limit(50).all()
    return [t.to_dict() for t in trades]


@router.get("/api/signals")
def get_signals(db: Session = Depends(get_db)):
    """Returns recent algorithmic and AI signals."""
    signals = db.query(SignalLog).order_by(SignalLog.id.desc()).limit(50).all()
    return [s.to_dict() for s in signals]


@router.post("/api/scan")
def trigger_market_scan(background_tasks: BackgroundTasks):
    """Triggers an immediate asynchronous market scan over the Indian watchlist."""
    background_tasks.add_task(scheduler_runner.run_market_scan)
    return {"message": "Market scan triggered across NSE/BSE watchlist."}


@router.post("/api/analyze/{symbol}")
def analyze_symbol(symbol: str):
    """Runs instant multi-indicator and Gemini AI analysis on an Indian stock."""
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
    """Executes a manual paper buy order on an Indian stock."""
    norm_symbol = normalize_indian_symbol(order.symbol)
    if not is_indian_symbol(norm_symbol):
        raise HTTPException(
            status_code=400,
            detail="Only Indian Stock Market (NSE/BSE) symbols can be traded."
        )

    price = order.price or data_fetcher.get_current_price(norm_symbol)
    result = portfolio_engine.execute_buy(
        symbol=norm_symbol,
        price=price,
        strategy=order.strategy or "manual",
        reason="Manual API Buy Execution"
    )
    if not result:
        raise HTTPException(status_code=400, detail="Failed to execute buy order. Insufficient cash balance.")
    return result


@router.post("/api/trade/sell")
def manual_sell(order: SellOrderRequest):
    """Executes a manual paper sell order in ₹ INR."""
    norm_symbol = normalize_indian_symbol(order.symbol)
    price = order.price or data_fetcher.get_current_price(norm_symbol)
    result = portfolio_engine.execute_sell(
        symbol=norm_symbol,
        price=price,
        reason=order.reason or "Manual API Sell Execution"
    )
    if not result:
        raise HTTPException(status_code=400, detail="Failed to execute sell order. No open position.")
    return result


@router.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


@router.get("/", response_class=HTMLResponse)
def get_dashboard():
    """Renders the TradeMind-AI Indian Stock Market Live Tracing & Trading Dashboard."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TradeMind AI 🇮🇳 | Live Indian Stock Market (NSE / BSE)</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #060911;
            --card-bg: rgba(15, 23, 42, 0.8);
            --card-border: rgba(255, 255, 255, 0.08);
            --accent-saffron: #ff9933;
            --accent-green: #10b981;
            --accent-cyan: #38bdf8;
            --text-primary: #f8fafc;
            --text-muted: #94a3b8;
            --bull: #10b981;
            --bear: #f43f5e;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Outfit', sans-serif; }
        body { background: var(--bg); color: var(--text-primary); min-height: 100vh; padding: 20px; }
        .container { max-width: 1440px; margin: 0 auto; }
        
        /* Header */
        header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; padding-bottom: 16px; border-bottom: 1px solid var(--card-border); flex-wrap: wrap; gap: 14px; }
        .logo-group { display: flex; align-items: center; gap: 12px; }
        .logo-title { font-size: 26px; font-weight: 800; background: linear-gradient(135deg, #ff9933 0%, #ffffff 50%, #10b981 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .badge { background: rgba(255, 153, 51, 0.12); color: var(--accent-saffron); padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; border: 1px solid rgba(255, 153, 51, 0.3); }
        .badge-live { background: rgba(16, 185, 129, 0.15); color: var(--bull); border: 1px solid rgba(16, 185, 129, 0.3); }
        
        .header-actions { display: flex; gap: 10px; align-items: center; }
        button { background: linear-gradient(135deg, #ff9933, #e67e22); color: #fff; border: none; padding: 9px 16px; border-radius: 8px; font-weight: 600; cursor: pointer; transition: all 0.2s ease; box-shadow: 0 4px 14px rgba(255, 153, 51, 0.25); display: inline-flex; align-items: center; gap: 6px; }
        button:hover { opacity: 0.92; transform: translateY(-1px); }
        button.secondary { background: rgba(255,255,255,0.06); border: 1px solid var(--card-border); box-shadow: none; }
        button.secondary:hover { background: rgba(255,255,255,0.12); }
        button.bull-btn { background: linear-gradient(135deg, #10b981, #059669); box-shadow: 0 4px 14px rgba(16, 185, 129, 0.25); }

        /* KPI Banner */
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; margin-bottom: 20px; }
        .stat-card { background: var(--card-bg); border: 1px solid var(--card-border); backdrop-filter: blur(16px); border-radius: 12px; padding: 18px; }
        .stat-label { font-size: 12px; color: var(--text-muted); font-weight: 500; text-transform: uppercase; letter-spacing: 0.5px; }
        .stat-value { font-size: 26px; font-weight: 700; margin-top: 4px; font-family: 'JetBrains Mono', monospace; }
        .positive { color: var(--bull); }
        .negative { color: var(--bear); }

        /* Live Tracer Hero Section */
        .tracer-hero { background: linear-gradient(135deg, rgba(30, 41, 59, 0.7), rgba(15, 23, 42, 0.9)); border: 1px solid rgba(255, 153, 51, 0.3); border-radius: 14px; padding: 20px; margin-bottom: 20px; backdrop-filter: blur(16px); }
        .tracer-search { display: flex; gap: 10px; margin-bottom: 16px; }
        .tracer-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; }
        .tracer-kpi { background: rgba(0,0,0,0.3); border: 1px solid var(--card-border); border-radius: 10px; padding: 14px; }
        
        /* Layout */
        .layout-grid { display: grid; grid-template-columns: 2fr 1fr; gap: 20px; }
        @media (max-width: 1024px) { .layout-grid { grid-template-columns: 1fr; } }
        
        .card { background: var(--card-bg); border: 1px solid var(--card-border); backdrop-filter: blur(16px); border-radius: 14px; padding: 20px; margin-bottom: 20px; }
        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; font-size: 16px; font-weight: 600; }
        
        /* Tables */
        table { width: 100%; border-collapse: collapse; text-align: left; }
        th { font-size: 12px; color: var(--text-muted); padding: 10px; border-bottom: 1px solid var(--card-border); text-transform: uppercase; letter-spacing: 0.5px; }
        td { padding: 10px; border-bottom: 1px solid rgba(255,255,255,0.03); font-size: 13.5px; }
        tr:hover { background: rgba(255, 255, 255, 0.02); }
        .mono { font-family: 'JetBrains Mono', monospace; }
        
        .tag-buy { background: rgba(16, 185, 129, 0.15); color: var(--bull); padding: 3px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; border: 1px solid rgba(16, 185, 129, 0.3); }
        .tag-sell { background: rgba(244, 63, 94, 0.15); color: var(--bear); padding: 3px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; border: 1px solid rgba(244, 63, 94, 0.3); }
        
        select, input { background: #111a2c; border: 1px solid var(--card-border); color: #fff; padding: 9px 12px; border-radius: 8px; font-size: 13.5px; outline: none; }
        select:focus, input:focus { border-color: var(--accent-saffron); }

        .backtest-box { background: rgba(0,0,0,0.3); border: 1px solid var(--card-border); border-radius: 12px; padding: 16px; }
        .input-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)) auto; gap: 10px; margin-bottom: 14px; }

        .toast { position: fixed; bottom: 20px; right: 20px; background: #1e293b; color: #fff; padding: 12px 18px; border-radius: 8px; border-left: 4px solid var(--accent-saffron); box-shadow: 0 10px 30px rgba(0,0,0,0.5); display: none; z-index: 999; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo-group">
                <div class="logo-title">TradeMind AI 🇮🇳</div>
                <span class="badge">NSE / BSE Live Edition</span>
                <span class="badge badge-live" id="market-status-badge">Checking Market...</span>
            </div>
            <div class="header-actions">
                <button class="secondary" onclick="runScan()">⚡ Scan NSE Markets</button>
                <button class="bull-btn" onclick="openQuickTrade()">+ Paper Trade</button>
                <a href="/docs" target="_blank"><button class="secondary">API Docs</button></a>
                <button onclick="refreshData()">🔄 Refresh</button>
            </div>
        </header>

        <!-- KPI Banner (INR) -->
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-label">Virtual Cash Balance</div>
                <div class="stat-value" id="cash-balance">₹2,000.00</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Total Portfolio Equity</div>
                <div class="stat-value" id="total-equity">₹2,000.00</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Total Realized PnL</div>
                <div class="stat-value" id="realized-pnl">₹0.00</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Total Return %</div>
                <div class="stat-value" id="return-pct">0.00%</div>
            </div>
        </div>

        <!-- Real-Time Live Stock Tracer Hero -->
        <div class="tracer-hero">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; flex-wrap:wrap; gap:8px;">
                <div>
                    <span style="font-size:18px; font-weight:700; color:var(--accent-saffron);">📡 Real-Time Live NSE Stock Tracer</span>
                    <span style="font-size:12px; color:var(--text-muted); margin-left:8px;">Live National Stock Exchange Tick Feed</span>
                </div>
                <div id="tracer-timestamp" style="font-size:12px; color:var(--text-muted);">--</div>
            </div>

            <div class="tracer-search">
                <input id="tracer-input" type="text" value="RELIANCE.NS" placeholder="Enter NSE stock (e.g. RELIANCE.NS, TCS.NS, INFY.NS)" style="flex:1;">
                <button onclick="traceCurrentStock()">Trace Live Quote</button>
            </div>

            <div class="tracer-grid" id="tracer-metrics">
                <div class="tracer-kpi">
                    <div class="stat-label">Live Exchange Price</div>
                    <div class="stat-value" id="tr-price" style="color:var(--accent-saffron);">₹0.00</div>
                    <div id="tr-change" style="font-size:12px; margin-top:2px;" class="mono positive">+0.00 (0.00%)</div>
                </div>
                <div class="tracer-kpi">
                    <div class="stat-label">Day Range (High / Low)</div>
                    <div class="stat-value" id="tr-day-range" style="font-size:18px;">₹0 / ₹0</div>
                    <div id="tr-open" style="font-size:11px; color:var(--text-muted); margin-top:4px;">Open: ₹0.00 | Prev: ₹0.00</div>
                </div>
                <div class="tracer-kpi">
                    <div class="stat-label">52-Week Range</div>
                    <div class="stat-value" id="tr-52w" style="font-size:18px;">₹0 / ₹0</div>
                    <div id="tr-volume" style="font-size:11px; color:var(--text-muted); margin-top:4px;">NSE Volume: 0 shares</div>
                </div>
                <div class="tracer-kpi">
                    <div class="stat-label">VWAP & Supertrend</div>
                    <div class="stat-value" id="tr-vwap" style="font-size:18px;">₹0.00</div>
                    <div id="tr-supertrend" style="font-size:11px; margin-top:4px; font-weight:600;" class="positive">BULLISH SUPERTREND</div>
                </div>
                <div class="tracer-kpi">
                    <div class="stat-label">RSI (14) & Signal</div>
                    <div class="stat-value" id="tr-rsi" style="font-size:18px;">50.0</div>
                    <div id="tr-verdict" style="font-size:11px; margin-top:4px;"><span class="tag-buy">BUY</span> (85% Conf)</div>
                </div>
            </div>
        </div>

        <div class="layout-grid">
            <!-- Left Column -->
            <div>
                <!-- Live Watchlist Table -->
                <div class="card">
                    <div class="card-header">
                        <span>🇮🇳 Indian Equities Live Watchlist (NSE)</span>
                        <span style="font-size:12px; color:var(--text-muted);">Real Exchange Data</span>
                    </div>
                    <table>
                        <thead>
                            <tr>
                                <th>Stock</th>
                                <th>Live Price</th>
                                <th>24h Change</th>
                                <th>Day High</th>
                                <th>Day Low</th>
                                <th>Action</th>
                            </tr>
                        </thead>
                        <tbody id="market-watchlist-table">
                            <tr><td colspan="6" style="text-align:center; color:var(--text-muted);">Loading real NSE quotes...</td></tr>
                        </tbody>
                    </table>
                </div>

                <!-- Open Virtual Portfolio Positions -->
                <div class="card">
                    <div class="card-header">
                        <span>💼 Open Positions (Virtual ₹2,000 Portfolio)</span>
                        <span id="open-positions-count" class="badge">0 Open</span>
                    </div>
                    <table>
                        <thead>
                            <tr>
                                <th>Symbol</th>
                                <th>Qty</th>
                                <th>Avg Entry</th>
                                <th>Live Price</th>
                                <th>Unrealized PnL</th>
                                <th>Exit</th>
                            </tr>
                        </thead>
                        <tbody id="positions-table">
                            <tr><td colspan="6" style="text-align:center; color:var(--text-muted);">No open positions. Automated scanner is actively monitoring.</td></tr>
                        </tbody>
                    </table>
                </div>

                <!-- Backtesting Engine on Real Indian Data -->
                <div class="card">
                    <div class="card-header">
                        <span>🧪 Quantitative Backtesting Engine (Real NSE Historical Data)</span>
                    </div>
                    <div class="backtest-box">
                        <div class="input-row">
                            <div>
                                <label style="font-size:11px; color:var(--text-muted); display:block; margin-bottom:4px;">Indian Stock</label>
                                <select id="bt-symbol" style="width:100%;">
                                    <option value="RELIANCE.NS">RELIANCE.NS (Reliance)</option>
                                    <option value="TCS.NS">TCS.NS (TCS)</option>
                                    <option value="INFY.NS">INFY.NS (Infosys)</option>
                                    <option value="HDFCBANK.NS">HDFCBANK.NS (HDFC Bank)</option>
                                    <option value="ICICIBANK.NS">ICICIBANK.NS (ICICI Bank)</option>
                                    <option value="TATAMOTORS.NS">TATAMOTORS.NS (Tata Motors)</option>
                                    <option value="SBIN.NS">SBIN.NS (SBI)</option>
                                    <option value="BHARTIARTL.NS">BHARTIARTL.NS (Airtel)</option>
                                    <option value="ITC.NS">ITC.NS (ITC)</option>
                                    <option value="LT.NS">LT.NS (L&T)</option>
                                </select>
                            </div>
                            <div>
                                <label style="font-size:11px; color:var(--text-muted); display:block; margin-bottom:4px;">Strategy</label>
                                <select id="bt-strategy" style="width:100%;">
                                    <option value="Supertrend_VWAP_Indian">Supertrend + VWAP (Indian Spec)</option>
                                    <option value="EMA_MACD_Trend">EMA (9/21) + MACD Momentum</option>
                                    <option value="RSI_BB_Reversal">RSI Mean Reversion + BB</option>
                                </select>
                            </div>
                            <div>
                                <label style="font-size:11px; color:var(--text-muted); display:block; margin-bottom:4px;">Time Horizon</label>
                                <select id="bt-period" style="width:100%;">
                                    <option value="30d">Last 30 Days (1h)</option>
                                    <option value="60d" selected>Last 60 Days (1h)</option>
                                    <option value="180d">Last 6 Months (1d)</option>
                                </select>
                            </div>
                            <div style="align-self:end;">
                                <button onclick="runBacktest()" style="width:100%; height:38px;">Run Backtest</button>
                            </div>
                        </div>

                        <!-- Backtest Results Display -->
                        <div id="bt-results" style="display:none; margin-top:14px;">
                            <div class="stats-grid">
                                <div class="stat-card"><div class="stat-label">Net Strategy Return</div><div class="stat-value" id="bt-return">--</div></div>
                                <div class="stat-card"><div class="stat-label">Win Rate %</div><div class="stat-value" id="bt-winrate">--</div></div>
                                <div class="stat-card"><div class="stat-label">Profit Factor</div><div class="stat-value" id="bt-pf">--</div></div>
                                <div class="stat-card"><div class="stat-label">Max Drawdown</div><div class="stat-value" id="bt-dd">--</div></div>
                            </div>
                            <div style="font-size:12px; color:var(--text-muted); margin-top:6px;">
                                Initial Balance: <strong>₹2,000.00</strong> | Simulated Trades: <span id="bt-total-trades" style="color:#fff; font-weight:600;">0</span> | Sharpe Ratio: <span id="bt-sharpe" style="color:#fff; font-weight:600;">0.0</span>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Executed Trades -->
                <div class="card">
                    <div class="card-header">
                        <span>📜 Trade Execution Book (Audit Trail)</span>
                    </div>
                    <table>
                        <thead>
                            <tr>
                                <th>Symbol</th>
                                <th>Side</th>
                                <th>Entry Price</th>
                                <th>Exit Price</th>
                                <th>Realized PnL</th>
                                <th>Reason / Exit</th>
                            </tr>
                        </thead>
                        <tbody id="trades-table">
                            <tr><td colspan="6" style="text-align:center; color:var(--text-muted);">No historical trades recorded yet.</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Right Column -->
            <div>
                <!-- Instant Gemini AI Analyst -->
                <div class="card">
                    <div class="card-header">
                        <span>🧠 Instant Gemini AI Analyst</span>
                    </div>
                    <div style="display:flex; gap:8px; margin-bottom:10px;">
                        <input id="analyze-symbol-input" type="text" value="RELIANCE.NS" style="flex:1;">
                        <button onclick="analyzeStock()">Analyze</button>
                    </div>
                    <div id="analysis-output" style="font-size:13px; color:var(--text-muted); background:rgba(0,0,0,0.25); padding:12px; border-radius:10px; min-height:90px; border:1px solid var(--card-border);">
                        Enter any NSE stock (e.g. <code>RELIANCE.NS</code>, <code>TCS.NS</code>) to get instant Gemini AI technical confirmation & risk rating.
                    </div>
                </div>

                <!-- Live AI Signals & Telegram Previews -->
                <div class="card">
                    <div class="card-header">
                        <span>⚡ Live Signals & Reasoning Feed</span>
                    </div>
                    <div id="signals-list" style="max-height:550px; overflow-y:auto;">
                        <div style="text-align:center; color:var(--text-muted); padding:20px;">Scanning real Indian stock candles...</div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <div id="toast" class="toast">Action triggered</div>

    <script>
        function showToast(msg) {
            const t = document.getElementById('toast');
            t.innerText = msg;
            t.style.display = 'block';
            setTimeout(() => { t.style.display = 'none'; }, 3500);
        }

        async function traceCurrentStock() {
            const sym = document.getElementById('tracer-input').value.trim();
            if (!sym) return;
            
            showToast(`Tracing live exchange quote for ${sym}...`);
            try {
                const res = await fetch(`/api/trace/${sym}`);
                if (!res.ok) {
                    const err = await res.json();
                    alert(err.detail || 'Failed to trace stock.');
                    return;
                }
                const data = await res.json();
                const tr = data.trace;
                const ind = data.technical_indicators;
                const sig = data.strategy_verdict;

                document.getElementById('tracer-timestamp').innerText = `${tr.company_name} | ${tr.timestamp_ist}`;
                document.getElementById('tr-price').innerText = `₹${tr.current_price.toLocaleString('en-IN', {minimumFractionDigits: 2})}`;
                
                const changeEl = document.getElementById('tr-change');
                changeEl.innerText = `${tr.change_24h >= 0 ? '+' : ''}₹${tr.change_24h.toFixed(2)} (${tr.change_percent >= 0 ? '+' : ''}${tr.change_percent.toFixed(2)}%)`;
                changeEl.className = 'mono ' + (tr.change_24h >= 0 ? 'positive' : 'negative');

                document.getElementById('tr-day-range').innerText = `₹${tr.day_high.toFixed(2)} / ₹${tr.day_low.toFixed(2)}`;
                document.getElementById('tr-open').innerText = `Open: ₹${tr.open_price.toFixed(2)} | Prev: ₹${tr.previous_close.toFixed(2)}`;

                document.getElementById('tr-52w').innerText = `₹${tr.fifty_two_week_high.toFixed(2)} / ₹${tr.fifty_two_week_low.toFixed(2)}`;
                document.getElementById('tr-volume').innerText = `NSE Vol: ${tr.volume.toLocaleString('en-IN')} shares`;

                document.getElementById('tr-vwap').innerText = `₹${ind.vwap.toFixed(2)}`;
                const stEl = document.getElementById('tr-supertrend');
                stEl.innerText = `${ind.supertrend_direction} (₹${ind.supertrend.toFixed(2)})`;
                stEl.className = ind.supertrend_direction === 'BULLISH' ? 'positive' : 'negative';

                document.getElementById('tr-rsi').innerText = `${ind.rsi_14.toFixed(1)}`;
                document.getElementById('tr-verdict').innerHTML = `<span class="${sig.action === 'BUY' ? 'tag-buy' : 'tag-sell'}">${sig.action}</span> (${(sig.confidence*100).toFixed(0)}% Conf)`;
            } catch (e) {
                console.error(e);
            }
        }

        async function refreshData() {
            // 1. Status
            fetch('/api/status')
                .then(r => r.json())
                .then(statusData => {
                    const badge = document.getElementById('market-status-badge');
                    if (badge) badge.innerText = statusData.market_status_ist || 'ONLINE';
                }).catch(e => console.error('Status fetch:', e));

            // 2. Portfolio
            fetch('/api/portfolio')
                .then(r => r.json())
                .then(data => {
                    const cur = '₹';
                    const cb = document.getElementById('cash-balance');
                    if (cb) cb.innerText = `${cur}${Number(data.cash_balance || 0).toLocaleString('en-IN', {minimumFractionDigits: 2})}`;
                    const te = document.getElementById('total-equity');
                    if (te) te.innerText = `${cur}${Number(data.total_equity || 0).toLocaleString('en-IN', {minimumFractionDigits: 2})}`;

                    const pnlEl = document.getElementById('realized-pnl');
                    const pnl = data.total_realized_pnl || 0;
                    if (pnlEl) {
                        pnlEl.innerText = `${pnl >= 0 ? '+' : ''}${cur}${pnl.toLocaleString('en-IN', {minimumFractionDigits: 2})}`;
                        pnlEl.className = 'stat-value ' + (pnl >= 0 ? 'positive' : 'negative');
                    }

                    const retEl = document.getElementById('return-pct');
                    const ret = data.total_return_percent || 0;
                    if (retEl) {
                        retEl.innerText = `${ret >= 0 ? '+' : ''}${ret.toFixed(2)}%`;
                        retEl.className = 'stat-value ' + (ret >= 0 ? 'positive' : 'negative');
                    }

                    const opc = document.getElementById('open-positions-count');
                    if (opc) opc.innerText = `${data.open_positions_count || 0} Open`;

                    const posTable = document.getElementById('positions-table');
                    if (posTable) {
                        if (data.positions && data.positions.length > 0) {
                            posTable.innerHTML = data.positions.map(p => `
                                <tr>
                                    <td><strong>${p.symbol}</strong></td>
                                    <td class="mono">${Number(p.quantity).toFixed(4)}</td>
                                    <td class="mono">${cur}${Number(p.average_entry_price).toFixed(2)}</td>
                                    <td class="mono">${cur}${Number(p.current_price).toFixed(2)}</td>
                                    <td class="mono ${p.unrealized_pnl >= 0 ? 'positive' : 'negative'}">
                                        ${p.unrealized_pnl >= 0 ? '+' : ''}${cur}${Number(p.unrealized_pnl).toFixed(2)} (${Number(p.unrealized_pnl_percent).toFixed(2)}%)
                                    </td>
                                    <td><button class="secondary" style="padding:4px 8px; font-size:11px;" onclick="sellPosition('${p.symbol}')">Sell</button></td>
                                </tr>
                            `).join('');
                        } else {
                            posTable.innerHTML = '<tr><td colspan="6" style="text-align:center; color:var(--text-muted);">No open positions. Automated scanner is actively monitoring.</td></tr>';
                        }
                    }
                }).catch(e => console.error('Portfolio fetch:', e));

            // 3. Market Watchlist
            fetch('/api/market-data')
                .then(r => r.json())
                .then(mktData => {
                    const cur = '₹';
                    const mktTable = document.getElementById('market-watchlist-table');
                    if (mktTable && Array.isArray(mktData) && mktData.length > 0) {
                        mktTable.innerHTML = mktData.map(m => `
                            <tr>
                                <td><strong>${m.symbol}</strong><br><span style="font-size:11px; color:var(--text-muted);">${m.company_name}</span></td>
                                <td class="mono">${cur}${Number(m.current_price).toLocaleString('en-IN', {minimumFractionDigits: 2})}</td>
                                <td class="mono ${m.change_percent >= 0 ? 'positive' : 'negative'}">
                                    ${m.change_percent >= 0 ? '+' : ''}${Number(m.change_percent).toFixed(2)}%
                                </td>
                                <td class="mono" style="color:var(--text-muted);">${cur}${Number(m.day_high).toFixed(2)}</td>
                                <td class="mono" style="color:var(--text-muted);">${cur}${Number(m.day_low).toFixed(2)}</td>
                                <td>
                                    <button class="secondary" style="padding:4px 8px; font-size:11px;" onclick="selectForTrace('${m.symbol}')">Trace</button>
                                    <button class="bull-btn" style="padding:4px 8px; font-size:11px;" onclick="quickBuy('${m.symbol}', ${m.current_price})">Buy</button>
                                </td>
                            </tr>
                        `).join('');
                    }
                }).catch(e => console.error('Market data fetch:', e));

            // 4. Trade History
            fetch('/api/trades')
                .then(r => r.json())
                .then(trades => {
                    const cur = '₹';
                    const tradesTable = document.getElementById('trades-table');
                    if (tradesTable && Array.isArray(trades) && trades.length > 0) {
                        tradesTable.innerHTML = trades.slice(0, 8).map(t => `
                            <tr>
                                <td><strong>${t.symbol}</strong></td>
                                <td><span class="${t.side === 'BUY' ? 'tag-buy' : 'tag-sell'}">${t.side}</span></td>
                                <td class="mono">${cur}${Number(t.entry_price).toFixed(2)}</td>
                                <td class="mono">${t.exit_price ? cur + Number(t.exit_price).toFixed(2) : '-'}</td>
                                <td class="mono ${(t.realized_pnl || 0) >= 0 ? 'positive' : 'negative'}">
                                    ${t.realized_pnl !== null ? (t.realized_pnl >= 0 ? '+' : '') + cur + Number(t.realized_pnl).toFixed(2) : 'OPEN'}
                                </td>
                                <td style="font-size:12px; color:var(--text-muted);">${t.reason || '-'}</td>
                            </tr>
                        `).join('');
                    }
                }).catch(e => console.error('Trades fetch:', e));

            // 5. Signals Feed
            fetch('/api/signals')
                .then(r => r.json())
                .then(sigs => {
                    const sigList = document.getElementById('signals-list');
                    if (sigList && Array.isArray(sigs) && sigs.length > 0) {
                        sigList.innerHTML = sigs.slice(0, 6).map(s => `
                            <div class="signal-card" style="background:rgba(255,255,255,0.02); border:1px solid var(--card-border); border-radius:8px; padding:10px; margin-bottom:8px;">
                                <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                                    <strong>${s.symbol}</strong>
                                    <span class="${s.action === 'BUY' ? 'tag-buy' : 'tag-sell'}">${s.action}</span>
                                </div>
                                <div style="font-size:12px; color:var(--text-muted); margin-bottom:6px;">
                                    ₹${Number(s.price).toFixed(2)} | Confidence: ${(Number(s.confidence)*100).toFixed(0)}%
                                </div>
                                <div style="font-size:12px; color:#cbd5e1; line-height:1.4;">
                                    ${s.ai_reasoning || 'Quantitative trend setup confirmed.'}
                                </div>
                            </div>
                        `).join('');
                    }
                }).catch(e => console.error('Signals fetch:', e));
        }

        function selectForTrace(symbol) {
            document.getElementById('tracer-input').value = symbol;
            traceCurrentStock();
        }

        async function runScan() {
            showToast('Scanning real NSE/BSE markets...');
            await fetch('/api/scan', {method: 'POST'});
            setTimeout(refreshData, 3000);
        }

        async function quickBuy(symbol, price) {
            showToast(`Placing paper BUY order for ${symbol}...`);
            const res = await fetch('/api/trade/buy', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({symbol: symbol, price: price, strategy: 'Manual_Dashboard'})
            });
            if (res.ok) {
                showToast(`Filled BUY order for ${symbol}!`);
                refreshData();
            } else {
                alert('Order failed: Insufficient cash balance.');
            }
        }

        async function sellPosition(symbol) {
            showToast(`Selling position ${symbol}...`);
            await fetch('/api/trade/sell', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({symbol: symbol, reason: 'Manual Dashboard Exit'})
            });
            refreshData();
        }

        function openQuickTrade() {
            const sym = prompt("Enter Indian Stock Symbol (e.g. RELIANCE.NS, TCS.NS, INFY.NS, HDFCBANK.NS):", "RELIANCE.NS");
            if (sym) {
                quickBuy(sym);
            }
        }

        async function analyzeStock() {
            const sym = document.getElementById('analyze-symbol-input').value.trim();
            const output = document.getElementById('analysis-output');
            output.innerHTML = '<em>Consulting Gemini AI & Supertrend/VWAP engine...</em>';
            try {
                const res = await fetch(`/api/analyze/${sym}`, {method: 'POST'});
                if (!res.ok) {
                    const err = await res.json();
                    output.innerHTML = `<span style="color:#f43f5e;">${err.detail || 'Analysis error'}</span>`;
                    return;
                }
                const data = await res.json();
                output.innerHTML = `
                    <div style="color:#ff9933; font-weight:700; font-size:15px; margin-bottom:4px;">${data.symbol} @ ₹${data.current_price.toFixed(2)}</div>
                    <div><strong>Strategy Verdict:</strong> <span class="${data.strategy_signal.action === 'BUY' ? 'tag-buy':'tag-sell'}">${data.strategy_signal.action}</span> (${(data.strategy_signal.confidence * 100).toFixed(0)}% Confidence)</div>
                    <div style="margin-top:8px; line-height:1.4;"><strong>AI Reasoning:</strong> ${data.ai_analysis.reasoning}</div>
                    <div style="margin-top:6px; font-size:12px; color:var(--text-muted);">Risk Rating: <strong style="color:#fff;">${data.ai_analysis.risk_level}</strong></div>
                `;
            } catch(e) {
                output.innerHTML = 'Error running analysis.';
            }
        }

        async function runBacktest() {
            const sym = document.getElementById('bt-symbol').value;
            const strat = document.getElementById('bt-strategy').value;
            const period = document.getElementById('bt-period').value;
            
            const btn = document.querySelector('.backtest-box button');
            btn.innerText = 'Calculating...';
            showToast(`Running real historical backtest on ${sym}...`);
            
            try {
                const res = await fetch('/api/backtest', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        symbol: sym,
                        strategy_name: strat,
                        period: period,
                        initial_balance: 2000.0
                    })
                });
                const data = await res.json();
                
                document.getElementById('bt-results').style.display = 'block';
                const retEl = document.getElementById('bt-return');
                retEl.innerText = `${data.total_return_percent >= 0 ? '+' : ''}${data.total_return_percent}%`;
                retEl.className = 'stat-value ' + (data.total_return_percent >= 0 ? 'positive' : 'negative');
                
                document.getElementById('bt-winrate').innerText = `${data.win_rate_percent}%`;
                document.getElementById('bt-pf').innerText = `${data.profit_factor}`;
                document.getElementById('bt-dd').innerText = `${data.max_drawdown_percent}%`;
                document.getElementById('bt-total-trades').innerText = `${data.total_trades} (${data.winning_trades}W / ${data.losing_trades}L)`;
                document.getElementById('bt-sharpe').innerText = `${data.sharpe_ratio}`;
                showToast(`Backtest complete for ${sym}!`);
            } catch(e) {
                alert('Error running backtest.');
            } finally {
                btn.innerText = 'Run Backtest';
            }
        }

        // Initial trace & load
        traceCurrentStock();
        refreshData();
        setInterval(refreshData, 10000);
    </script>
</body>
</html>"""
