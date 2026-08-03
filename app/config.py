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
    
    # Virtual Portfolio (INR) - Scaled to ₹30,000 Capital for NIFTY F&O
    INITIAL_BALANCE: float = float(os.getenv("INITIAL_BALANCE", "30000.0"))
    MAX_POSITION_SIZE_RATIO: float = float(os.getenv("MAX_POSITION_SIZE_RATIO", "0.35"))  # Max 35% margin per trade
    STOP_LOSS_PERCENT: float = float(os.getenv("STOP_LOSS_PERCENT", "0.015"))            # 1.5% stop loss
    TAKE_PROFIT_PERCENT: float = float(os.getenv("TAKE_PROFIT_PERCENT", "0.035"))        # 3.5% take profit
    
    # NIFTY 50 Futures & Options (F&O) & Daily Circuit Configuration
    MAX_DAILY_TRADES: int = int(os.getenv("MAX_DAILY_TRADES", "4"))                      # Max 3-4 trades per day
    MAX_DAILY_LOSS: float = float(os.getenv("MAX_DAILY_LOSS", "2000.0"))                  # Max ₹2,000 loss circuit
    MAX_DAILY_PROFIT: float = float(os.getenv("MAX_DAILY_PROFIT", "4000.0"))              # Max ₹4,000 profit circuit
    NIFTY_LOT_SIZE: int = int(os.getenv("NIFTY_LOT_SIZE", "65"))                         # NSE Nifty lot size (65 units)
    NIFTY_STRIKE_STEP: int = int(os.getenv("NIFTY_STRIKE_STEP", "50"))                   # 50-pt strike intervals
    OPTION_STRIKE_TYPE: str = os.getenv("OPTION_STRIKE_TYPE", "ITM")                     # In-The-Money options
    
    # Strictly NIFTY 50 Index Universe (No other stocks)
    DEFAULT_SYMBOLS_RAW: str = os.getenv("DEFAULT_SYMBOLS", "^NSEI")
    
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
