import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, time, timezone, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from app.config import settings, is_indian_symbol, normalize_indian_symbol
from app.utils.logger import logger

# Indian Standard Time (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

INDIAN_COMPANY_NAMES: Dict[str, str] = {
    "RELIANCE.NS": "Reliance Industries Ltd",
    "TCS.NS": "Tata Consultancy Services",
    "INFY.NS": "Infosys Ltd",
    "HDFCBANK.NS": "HDFC Bank Ltd",
    "ICICIBANK.NS": "ICICI Bank Ltd",
    "M&M.NS": "Mahindra & Mahindra Ltd",
    "SBIN.NS": "State Bank of India",
    "BHARTIARTL.NS": "Bharti Airtel Ltd",
    "ITC.NS": "ITC Ltd",
    "LT.NS": "Larsen & Toubro Ltd",
    "KOTAKBANK.NS": "Kotak Mahindra Bank",
    "AXISBANK.NS": "Axis Bank Ltd",
    "MARUTI.NS": "Maruti Suzuki India",
    "BAJFINANCE.NS": "Bajaj Finance Ltd",
    "ASIANPAINT.NS": "Asian Paints Ltd",
    "WIPRO.NS": "Wipro Ltd",
    "SUNPHARMA.NS": "Sun Pharmaceutical",
    "TITAN.NS": "Titan Company Ltd",
    "^NSEI": "NIFTY 50 Index",
    "^NSEBANK": "NIFTY Bank Index",
}


@dataclass
class LiveStockTrace:
    symbol: str
    company_name: str
    exchange: str
    current_price: float
    previous_close: float
    open_price: float
    day_high: float
    day_low: float
    change_24h: float
    change_percent: float
    volume: float
    fifty_two_week_high: float
    fifty_two_week_low: float
    currency: str
    market_status: str
    timestamp_ist: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "company_name": self.company_name,
            "exchange": self.exchange,
            "current_price": round(self.current_price, 2),
            "previous_close": round(self.previous_close, 2),
            "open_price": round(self.open_price, 2),
            "day_high": round(self.day_high, 2),
            "day_low": round(self.day_low, 2),
            "change_24h": round(self.change_24h, 2),
            "change_percent": round(self.change_percent, 2),
            "volume": int(self.volume),
            "fifty_two_week_high": round(self.fifty_two_week_high, 2),
            "fifty_two_week_low": round(self.fifty_two_week_low, 2),
            "currency": self.currency,
            "market_status": self.market_status,
            "timestamp_ist": self.timestamp_ist,
        }


MarketData = LiveStockTrace


class DataFetcher:
    """
    High-Performance Real-Time Market Data Engine for Indian Equities (NSE / BSE).
    Features in-memory TTL caching and parallel multi-symbol resolution.
    """

    def __init__(self):
        self._trace_cache: Dict[str, Dict[str, Any]] = {}
        self._price_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl_seconds = 30  # Cache for 30s to prevent rate limits & UI freezing

    @staticmethod
    def is_market_open_now() -> bool:
        """Determines if the National Stock Exchange (NSE) regular trading session is currently open."""
        now = datetime.now(IST)
        # Saturday = 5, Sunday = 6
        if now.weekday() >= 5:
            return False
        
        market_open = time(9, 15)
        market_close = time(15, 30)
        return market_open <= now.time() <= market_close

    @staticmethod
    def get_market_status_ist() -> str:
        """Determines if the National Stock Exchange (NSE) is currently open."""
        now = datetime.now(IST)
        if now.weekday() >= 5:
            return "CLOSED (Weekend)"
        
        market_open = time(9, 15)
        market_close = time(15, 30)
        current_time = now.time()

        if market_open <= current_time <= market_close:
            return "LIVE (Market Open)"
        elif current_time < market_open:
            return "PRE-MARKET (09:00 - 09:15 IST)"
        else:
            return "AFTER-HOURS (Closed at 15:30 IST)"

    @staticmethod
    def get_next_market_open_ist() -> str:
        """Returns the date and time of the next NSE trading session."""
        now = datetime.now(IST)
        if now.weekday() == 4 and now.time() > time(15, 30):
            days_ahead = 3
        elif now.weekday() == 5:
            days_ahead = 2
        elif now.weekday() == 6:
            days_ahead = 1
        elif now.time() > time(15, 30):
            days_ahead = 1
        elif now.time() < time(9, 15):
            days_ahead = 0
        else:
            return "Market is currently OPEN (Closes at 15:30 IST)"
        
        next_open = (now + timedelta(days=days_ahead)).replace(hour=9, minute=15, second=0, microsecond=0)
        return next_open.strftime("%A, %d %b %Y at 09:15 AM IST")

    def fetch_ohlcv(
        self,
        symbol: str,
        period: str = "30d",
        interval: str = "1h"
    ) -> pd.DataFrame:
        """
        Fetches genuine historical OHLCV candles from NSE/BSE exchange via Yahoo Finance.
        """
        norm_symbol = normalize_indian_symbol(symbol)
        if not is_indian_symbol(norm_symbol):
            raise ValueError(f"'{symbol}' is not an Indian Stock Market symbol. Only NSE/BSE stocks are supported.")

        try:
            ticker = yf.Ticker(norm_symbol)
            df = ticker.history(period=period, interval=interval)
            
            if df.empty or len(df) < 2:
                df = ticker.history(period="60d", interval="1d")
                
            if df.empty or len(df) < 2:
                raise ValueError(f"No real exchange market data returned from NSE for '{norm_symbol}'.")

            df.columns = [c.lower() for c in df.columns]
            required_cols = ["open", "high", "low", "close", "volume"]
            for col in required_cols:
                if col not in df.columns:
                    raise ValueError(f"Missing '{col}' in exchange response for {norm_symbol}.")

            clean_df = df[required_cols].copy()
            clean_df.dropna(inplace=True)
            return clean_df

        except Exception as e:
            logger.error(f"Live exchange data fetch error for {norm_symbol}: {e}")
            raise

    def trace_live_stock(self, symbol: str) -> LiveStockTrace:
        """
        Traces live real-time metrics for an Indian stock with fast memory caching.
        """
        norm_symbol = normalize_indian_symbol(symbol)
        if not is_indian_symbol(norm_symbol):
            raise ValueError(f"'{symbol}' is rejected. Only Indian Stock Market (NSE/BSE) equities are supported.")

        now_ts = datetime.utcnow().timestamp()
        if norm_symbol in self._trace_cache:
            entry = self._trace_cache[norm_symbol]
            if (now_ts - entry["cached_at"]) < self._cache_ttl_seconds:
                return entry["trace"]

        ticker = yf.Ticker(norm_symbol)
        hist = ticker.history(period="5d", interval="1d")
        if hist.empty:
            hist = ticker.history(period="1mo", interval="1d")
        
        if hist.empty:
            if norm_symbol in self._trace_cache:
                return self._trace_cache[norm_symbol]["trace"]
            raise ValueError(f"Unable to trace live exchange data for '{norm_symbol}'.")


        last_row = hist.iloc[-1]
        prev_row = hist.iloc[-2] if len(hist) > 1 else last_row

        curr_price = float(last_row["Close"])
        prev_close = float(prev_row["Close"])
        open_price = float(last_row["Open"])
        day_high = float(last_row["High"])
        day_low = float(last_row["Low"])
        volume = float(last_row["Volume"])

        change = curr_price - prev_close
        change_pct = (change / prev_close) * 100.0 if prev_close else 0.0

        fifty_two_high = day_high
        fifty_two_low = day_low
        try:
            if hasattr(ticker, "fast_info"):
                fifty_two_high = float(ticker.fast_info.get("year_high", day_high) or day_high)
                fifty_two_low = float(ticker.fast_info.get("year_low", day_low) or day_low)
        except Exception:
            pass

        exchange = "BSE" if norm_symbol.endswith(".BO") else "NSE"
        company_name = INDIAN_COMPANY_NAMES.get(norm_symbol, norm_symbol.replace(".NS", "").replace(".BO", "") + " Ltd")
        now_ist = datetime.now(IST).strftime("%d %b %Y, %I:%M:%S %p IST")

        trace = LiveStockTrace(
            symbol=norm_symbol,
            company_name=company_name,
            exchange=exchange,
            current_price=curr_price,
            previous_close=prev_close,
            open_price=open_price,
            day_high=day_high,
            day_low=day_low,
            change_24h=change,
            change_percent=change_pct,
            volume=volume,
            fifty_two_week_high=fifty_two_high,
            fifty_two_week_low=fifty_two_low,
            currency="₹",
            market_status=self.get_market_status_ist(),
            timestamp_ist=now_ist
        )

        self._trace_cache[norm_symbol] = {"cached_at": now_ts, "trace": trace}
        self._price_cache[norm_symbol] = {"cached_at": now_ts, "price": curr_price}
        return trace

    def get_current_price(self, symbol: str) -> float:
        """Fetches latest real exchange price for an Indian stock."""
        norm_symbol = normalize_indian_symbol(symbol)
        now_ts = datetime.utcnow().timestamp()
        
        if norm_symbol in self._price_cache:
            entry = self._price_cache[norm_symbol]
            if (now_ts - entry["cached_at"]) < self._cache_ttl_seconds:
                return entry["price"]

        try:
            trace = self.trace_live_stock(norm_symbol)
            return trace.current_price
        except Exception as e:
            logger.error(f"Live price lookup failed for {norm_symbol}: {e}")
            if norm_symbol in self._price_cache:
                return self._price_cache[norm_symbol]["price"]
            return 0.0

    def get_bulk_market_data(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """Fetches market data in parallel threads for lightning-fast UI responses."""
        with ThreadPoolExecutor(max_workers=8) as executor:
            traces = list(executor.map(lambda s: self._safe_trace(s), symbols))
        return [t.to_dict() for t in traces if t is not None]

    def _safe_trace(self, sym: str) -> Optional[LiveStockTrace]:
        try:
            return self.trace_live_stock(sym)
        except Exception:
            return None

    def get_curated_indian_stocks(self) -> List[Dict[str, Any]]:
        """Returns a list of premier Indian companies across major sectors."""
        sectors = [
            {"symbol": "RELIANCE.NS", "name": "Reliance Industries", "sector": "Energy & Conglomerate"},
            {"symbol": "TCS.NS", "name": "Tata Consultancy Services", "sector": "Information Technology"},
            {"symbol": "INFY.NS", "name": "Infosys", "sector": "Information Technology"},
            {"symbol": "HDFCBANK.NS", "name": "HDFC Bank", "sector": "Banking & Finance"},
            {"symbol": "ICICIBANK.NS", "name": "ICICI Bank", "sector": "Banking & Finance"},
            {"symbol": "M&M.NS", "name": "Mahindra & Mahindra", "sector": "Automobile"},
            {"symbol": "SBIN.NS", "name": "State Bank of India", "sector": "Public Sector Banking"},
            {"symbol": "BHARTIARTL.NS", "name": "Bharti Airtel", "sector": "Telecommunications"},
            {"symbol": "ITC.NS", "name": "ITC Ltd", "sector": "FMCG & Consumer"},
            {"symbol": "LT.NS", "name": "Larsen & Toubro", "sector": "Infrastructure & Defense"},
            {"symbol": "MARUTI.NS", "name": "Maruti Suzuki", "sector": "Automobile"},
            {"symbol": "BAJFINANCE.NS", "name": "Bajaj Finance", "sector": "Financial Services"},
            {"symbol": "ASIANPAINT.NS", "name": "Asian Paints", "sector": "Paints & Consumer"},
            {"symbol": "WIPRO.NS", "name": "Wipro", "sector": "Information Technology"},
            {"symbol": "^NSEI", "name": "NIFTY 50 Benchmark", "sector": "Broad Market Index"},
            {"symbol": "^NSEBANK", "name": "NIFTY Bank Benchmark", "sector": "Banking Sector Index"},
        ]
        return sectors


data_fetcher = DataFetcher()
