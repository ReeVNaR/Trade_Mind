import os
from pathlib import Path
from typing import List
from dotenv import load_dotenv

# Base directory for TradeMind-AI
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"

# Load environment variables
load_dotenv(dotenv_path=ENV_PATH)


class Settings:
    PROJECT_NAME: str = "TradeMind-AI (Indian Stock Market)"
    VERSION: str = "2.0.0"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "production")
    
    # Currency
    CURRENCY_SYMBOL: str = "₹"
    CURRENCY_CODE: str = "INR"
    
    # Telegram Configuration
    TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "").strip()
    CHAT_ID: str = os.getenv("CHAT_ID", "").strip()
    
    # Gemini AI Configuration
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()
    
    # Virtual Portfolio (INR)
    INITIAL_BALANCE: float = float(os.getenv("INITIAL_BALANCE", "2000.0"))
    MAX_POSITION_SIZE_RATIO: float = float(os.getenv("MAX_POSITION_SIZE_RATIO", "0.20"))  # 20% max per trade
    STOP_LOSS_PERCENT: float = float(os.getenv("STOP_LOSS_PERCENT", "0.015"))            # 1.5% stop loss
    TAKE_PROFIT_PERCENT: float = float(os.getenv("TAKE_PROFIT_PERCENT", "0.035"))        # 3.5% take profit
    
    # Strictly Indian Stock Market (NSE / BSE) Watchlist Symbols
    DEFAULT_SYMBOLS_RAW: str = os.getenv(
        "DEFAULT_SYMBOLS",
        "RELIANCE.NS,TCS.NS,INFY.NS,HDFCBANK.NS,ICICIBANK.NS,SBIN.NS,BHARTIARTL.NS,ITC.NS,LT.NS,M&M.NS,MARUTI.NS,KOTAKBANK.NS,AXISBANK.NS,BAJFINANCE.NS,ASIANPAINT.NS,WIPRO.NS,^NSEI,^NSEBANK"
    )
    
    @property
    def DEFAULT_SYMBOLS(self) -> List[str]:
        return [s.strip().upper() for s in self.DEFAULT_SYMBOLS_RAW.split(",") if s.strip()]
        
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR}/trademind.db")
    
    # Scheduler
    SCAN_INTERVAL_MINUTES: int = int(os.getenv("SCAN_INTERVAL_MINUTES", "15"))
    
    # API Server
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("PORT", os.getenv("API_PORT", "8000")))
    
    # Logging
    LOG_DIR: Path = BASE_DIR / "logs"
    LOG_FILE: Path = LOG_DIR / "trademind.log"


def is_indian_symbol(symbol: str) -> bool:
    """Strictly checks if a symbol belongs to the Indian Stock Market (NSE / BSE)."""
    s = symbol.strip().upper()
    if s.endswith(".NS") or s.endswith(".BO"):
        return True
    if s in ["^NSEI", "^NSEBANK", "^CNXIT", "^BSESN", "NIFTY50", "BANKNIFTY", "NIFTY"]:
        return True
    return False


def normalize_indian_symbol(symbol: str) -> str:
    """Normalizes an Indian stock symbol (e.g. RELIANCE -> RELIANCE.NS, NIFTY -> ^NSEI)."""
    s = symbol.strip().upper()
    if s in ["NIFTY", "NIFTY50", "^NSEI"]:
        return "^NSEI"
    if s in ["BANKNIFTY", "^NSEBANK"]:
        return "^NSEBANK"
    if s.endswith(".NS") or s.endswith(".BO") or s.startswith("^"):
        return s
    # Default to National Stock Exchange (.NS)
    return f"{s}.NS"


settings = Settings()
settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
