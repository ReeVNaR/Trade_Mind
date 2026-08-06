import os
import psutil
import datetime
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from config.settings import settings
from broker.paper_broker import PaperBroker
from risk_management.risk_manager import RiskManager
from database.connection import init_db, get_db_session
from database.models import Trade, Order
from utils.logger import logger

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Production-ready AI-powered NIFTY F&O Trading Bot REST API"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global singleton state
start_time = datetime.datetime.utcnow()
broker = PaperBroker(initial_capital=settings.INITIAL_BALANCE)
broker.connect()
risk_manager = RiskManager()
is_trading_paused = False

@app.on_event("startup")
def startup_event():
    init_db()
    logger.info("FastAPI Server Started.")

@app.get("/health")
def health_check():
    """Health check endpoint for Render and uptime monitoring."""
    uptime_seconds = int((datetime.datetime.utcnow() - start_time).total_seconds())
    return {
        "status": "healthy" if not is_trading_paused else "paused",
        "broker_status": "CONNECTED" if broker.connected else "DISCONNECTED",
        "database_status": "HEALTHY",
        "telegram_status": "ACTIVE" if settings.TELEGRAM_TOKEN else "CONSOLE_ONLY",
        "environment": settings.ENVIRONMENT,
        "uptime_seconds": uptime_seconds
    }

@app.get("/api/balance")
def get_balance():
    """Returns real-time account balance & PnL."""
    return broker.get_balance()

@app.get("/api/positions")
def get_positions():
    """Returns active open positions."""
    return broker.get_positions()

@app.get("/api/orders")
def get_orders():
    """Returns list of executed and pending orders."""
    return broker.get_orders()

@app.get("/api/trades")
def get_trades(limit: int = 50):
    """Returns historic trades recorded in database."""
    with get_db_session() as session:
        trades = session.query(Trade).order_by(Trade.entry_time.desc()).limit(limit).all()
        return [
            {
                "trade_id": t.trade_id,
                "symbol": t.symbol,
                "direction": t.direction,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "quantity": t.quantity,
                "pnl": t.pnl,
                "status": t.status,
                "strategy_name": t.strategy_name,
                "confidence_score": t.confidence_score,
                "entry_time": t.entry_time.isoformat() if t.entry_time else None
            }
            for t in trades
        ]

@app.get("/api/system-status")
def get_system_status():
    """Returns CPU, RAM, and server stats."""
    process = psutil.Process(os.getpid())
    return {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "ram_mb": round(process.memory_info().rss / (1024 * 1024), 2),
        "trading_paused": is_trading_paused
    }

@app.post("/api/pause")
def pause_trading():
    global is_trading_paused
    is_trading_paused = True
    logger.info("Trading PAUSED by API request.")
    return {"status": "paused", "message": "Trading paused successfully."}

@app.post("/api/resume")
def resume_trading():
    global is_trading_paused
    is_trading_paused = False
    logger.info("Trading RESUMED by API request.")
    return {"status": "active", "message": "Trading resumed successfully."}

@app.get("/dashboard", response_class=HTMLResponse)
def serve_dashboard():
    """Serves live web dashboard."""
    dashboard_path = os.path.join(settings.BASE_DIR, "dashboard", "index.html")
    if os.path.exists(dashboard_path):
        return FileResponse(dashboard_path)
    raise HTTPException(status_code=404, detail="Dashboard UI not found")
