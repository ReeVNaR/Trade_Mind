import sys
import os
import warnings
import argparse

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Suppress deprecation notices for cleaner output
warnings.filterwarnings("ignore", category=FutureWarning)

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database.session import init_db
from app.api.routes import router as api_router
from app.scheduler.runner import scheduler_runner
from app.telegram.bot import telegram_service
from app.utils.logger import logger


def create_app() -> FastAPI:
    """Initializes FastAPI application instance."""
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description="Autonomous AI-Powered Algorithmic Trading & Portfolio Management Engine."
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)
    return app


app = create_app()


def start_server():
    """Starts the database, background scheduler, Telegram bot, and HTTP server."""
    print("TradeMind AI Started Successfully 🚀")
    logger.info(f"Starting {settings.PROJECT_NAME} v{settings.VERSION} [{settings.ENVIRONMENT}]")
    
    # Initialize SQLite Database & Tables
    init_db()
    
    # Start periodic market scanner in background thread
    scheduler_runner.start()
    
    # Start interactive Telegram command listener
    telegram_service.start_polling()
    
    # Run uvicorn web server
    logger.info(f"Web Dashboard & API available at: http://{settings.API_HOST}:{settings.API_PORT}")
    uvicorn.run(app, host=settings.API_HOST, port=settings.API_PORT, log_level="info")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TradeMind-AI Runner")
    parser.add_argument("--verify", action="store_true", help="Run startup verification check and exit")
    parser.add_argument("--scan", action="store_true", help="Run immediate market scan and exit")
    args = parser.parse_args()

    if args.verify:
        print("TradeMind AI Started Successfully 🚀")
        init_db()
        sys.exit(0)
    elif args.scan:
        print("TradeMind AI Started Successfully 🚀")
        init_db()
        scheduler_runner.run_market_scan()
        sys.exit(0)
    else:
        start_server()
