import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(BASE_DIR, ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Directories
    BASE_DIR: str = str(BASE_DIR)

    # General
    PROJECT_NAME: str = "TradeMind-AI (Indian Stock Market)"
    VERSION: str = "2.0.0"
    ENVIRONMENT: str = "development"

    # Currency
    CURRENCY_SYMBOL: str = "₹"
    CURRENCY_CODE: str = "INR"

    # Telegram
    TELEGRAM_TOKEN: Optional[str] = None
    CHAT_ID: Optional[str] = None

    # Account & Capital
    INITIAL_BALANCE: float = 30000.0
    MAX_POSITION_SIZE_RATIO: float = 0.35
    STOP_LOSS_PERCENT: float = 0.015
    TAKE_PROFIT_PERCENT: float = 0.035

    # Risk Parameters
    MIN_DAILY_TRADES: int = 2
    MAX_DAILY_TRADES: int = 4
    MAX_DAILY_LOSS: float = 2000.0
    MAX_DAILY_PROFIT: float = 4000.0
    NIFTY_LOT_SIZE: int = 65
    NIFTY_STRIKE_STEP: int = 50
    OPTION_STRIKE_TYPE: str = "ITM"

    # Trading Symbols & Scans
    DEFAULT_SYMBOLS: str = "^NSEI"
    SCAN_INTERVAL_MINUTES: int = 15

    # API Server
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000

    # Database
    DATABASE_URL: str = f"sqlite:///{os.path.join(BASE_DIR, 'trade.db')}"

    # Log Directory
    LOG_DIR: str = os.path.join(BASE_DIR, "logs")

settings = Settings()
