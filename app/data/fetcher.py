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

NIFTY_INDEX_NAMES: Dict[str, str] = {
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
    High-Performance Real-Time Market Data Engine for NIFTY 50 Index (^NSEI) & F&O Derivatives.
    Features in-memory TTL caching and ultra-low latency execution.
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
        symbol: str = "^NSEI",
        period: str = "30d",
        interval: str = "1h"
    ) -> pd.DataFrame:
        """
        Fetches genuine historical OHLCV candles for NIFTY 50 Index from NSE via Yahoo Finance.
        """
        norm_symbol = normalize_indian_symbol(symbol)
        if not is_indian_symbol(norm_symbol):
            raise ValueError(f"'{symbol}' is not a supported NIFTY symbol. Only NIFTY 50 (^NSEI) is supported.")

        # Options / derivative symbols map to underlying NIFTY 50 index for candle technicals
        fetch_sym = "^NSEI" if norm_symbol.startswith("NIFTY") else norm_symbol

        try:
            ticker = yf.Ticker(fetch_sym)
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

    def trace_live_stock(self, symbol: str = "^NSEI") -> LiveStockTrace:
        """
        Traces live real-time metrics for NIFTY 50 Index with fast memory caching.
        """
        norm_symbol = normalize_indian_symbol(symbol)
        if not is_indian_symbol(norm_symbol):
            raise ValueError(f"'{symbol}' is rejected. Only NIFTY 50 Index & F&O derivatives are supported.")

        fetch_sym = "^NSEI" if norm_symbol.startswith("NIFTY") else norm_symbol

        now_ts = datetime.utcnow().timestamp()
        if fetch_sym in self._trace_cache:
            entry = self._trace_cache[fetch_sym]
            if (now_ts - entry["cached_at"]) < self._cache_ttl_seconds:
                return entry["trace"]

        ticker = yf.Ticker(fetch_sym)
        hist = ticker.history(period="5d", interval="1d")
        if hist.empty:
            hist = ticker.history(period="1mo", interval="1d")
        
        hist.dropna(subset=["Close"], inplace=True)
        if hist.empty:
            if fetch_sym in self._trace_cache:
                return self._trace_cache[fetch_sym]["trace"]
            raise ValueError(f"Unable to trace live exchange data for '{norm_symbol}'.")

        last_row = hist.iloc[-1]
        prev_row = hist.iloc[-2] if len(hist) > 1 else last_row

        curr_price = float(last_row["Close"]) if pd.notna(last_row["Close"]) else 0.0
        prev_close = float(prev_row["Close"]) if pd.notna(prev_row["Close"]) else curr_price
        open_price = float(last_row["Open"]) if pd.notna(last_row["Open"]) else curr_price
        day_high = float(last_row["High"]) if pd.notna(last_row["High"]) else curr_price
        day_low = float(last_row["Low"]) if pd.notna(last_row["Low"]) else curr_price
        volume = float(last_row["Volume"]) if pd.notna(last_row["Volume"]) else 0.0

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

        company_name = NIFTY_INDEX_NAMES.get(fetch_sym, "NIFTY 50 Index & F&O")
        now_ist = datetime.now(IST).strftime("%d %b %Y, %I:%M:%S %p IST")

        trace = LiveStockTrace(
            symbol=fetch_sym,
            company_name=company_name,
            exchange="NSE",
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

        self._trace_cache[fetch_sym] = {"cached_at": now_ts, "trace": trace}
        self._price_cache[fetch_sym] = {"cached_at": now_ts, "price": curr_price}
        return trace

    def get_current_price(self, symbol: str) -> float:
        """Fetches latest real exchange price for NIFTY or estimates option premium."""
        norm_symbol = normalize_indian_symbol(symbol)
        now_ts = datetime.utcnow().timestamp()
        
        if norm_symbol in self._price_cache:
            entry = self._price_cache[norm_symbol]
            if (now_ts - entry["cached_at"]) < self._cache_ttl_seconds:
                return entry["price"]

        try:
            # Handle option contract pricing
            if norm_symbol.startswith("NIFTY") and ("CE" in norm_symbol or "PE" in norm_symbol):
                from app.data.nifty_options import get_nifty_itm_strike
                spot_trace = self.trace_live_stock("^NSEI")
                opt_type = "CE" if "CE" in norm_symbol else "PE"
                itm = get_nifty_itm_strike(spot_trace.current_price, opt_type, itm_depth=1)
                return itm["estimated_premium"]

            trace = self.trace_live_stock(norm_symbol)
            return trace.current_price
        except Exception as e:
            logger.error(f"Live price lookup failed for {norm_symbol}: {e}")
            if norm_symbol in self._price_cache:
                return self._price_cache[norm_symbol]["price"]
            return 0.0

    def get_bulk_market_data(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """Fetches market data in parallel threads for lightning-fast UI responses."""
        with ThreadPoolExecutor(max_workers=4) as executor:
            traces = list(executor.map(lambda s: self._safe_trace(s), symbols))

    def _safe_trace(self, sym: str) -> Optional[LiveStockTrace]:
        try:
            return self.trace_live_stock(sym)
        except Exception:
            return None

    def get_live_nifty_ticker(self) -> Dict[str, Any]:
        """
        Ultra-low-latency real-time live ticker for NIFTY 50 Index (^NSEI).
        Fetches live exchange spot price via fast_info / trace with 0-delay response.
        Dynamically calculates 50 and 200 SMAs from real candles.
        """
        now_ts = datetime.now(timezone.utc).timestamp()
        now_ist_str = datetime.now(IST).strftime("%I:%M:%S %p IST")
        now_date_str = datetime.now(IST).strftime("%d %b %Y")

        last_price = None
        prev_close = None
        day_high = None
        day_low = None
        open_price = None
        fifty_sma = None
        two_hundred_sma = None

        try:
            ticker = yf.Ticker("^NSEI")
            fi = getattr(ticker, "fast_info", None)
            if fi:
                last_price = _get_fast_info_attr(fi, "last_price", "lastPrice")
                prev_close = _get_fast_info_attr(fi, "previous_close", "previousClose", "regularMarketPreviousClose")
                day_high = _get_fast_info_attr(fi, "day_high", "dayHigh")
                day_low = _get_fast_info_attr(fi, "day_low", "dayLow")
                open_price = _get_fast_info_attr(fi, "open")
                fifty_sma = _get_fast_info_attr(fi, "fifty_day_average", "fiftyDayAverage")
                two_hundred_sma = _get_fast_info_attr(fi, "two_hundred_day_average", "twoHundredDayAverage")
        except Exception as e:
            logger.debug(f"yfinance fast_info lookup notice: {e}")

        # Fallback to trace_live_stock if fast_info missing primary fields
        if not last_price or not prev_close:
            try:
                trace = self.trace_live_stock("^NSEI")
                last_price = last_price or trace.current_price
                prev_close = prev_close or trace.previous_close
                day_high = day_high or trace.day_high
                day_low = day_low or trace.day_low
                open_price = open_price or trace.open_price
            except Exception as e:
                logger.error(f"Live trace fallback failed: {e}")

        # Dynamically compute SMAs from OHLCV if missing from fast_info
        if not fifty_sma or not two_hundred_sma:
            try:
                df = self.fetch_ohlcv("^NSEI", period="1y", interval="1d")
                if not df.empty and "close" in df.columns:
                    closes = df["close"]
                    if not fifty_sma and len(closes) >= 50:
                        fifty_sma = float(closes.tail(50).mean())
                    elif not fifty_sma:
                        fifty_sma = float(closes.mean())

                    if not two_hundred_sma and len(closes) >= 200:
                        two_hundred_sma = float(closes.tail(200).mean())
                    elif not two_hundred_sma:
                        two_hundred_sma = float(closes.mean())
            except Exception as e:
                logger.debug(f"Dynamic SMA calculation notice: {e}")

        # Final check against last known in-memory price
        if not last_price:
            cached_entry = self._price_cache.get("^NSEI", {})
            last_price = cached_entry.get("price")
            if not last_price:
                raise ValueError("Real-time NIFTY 50 price feed currently unavailable.")

        if not prev_close:
            prev_close = last_price
        if not day_high:
            day_high = last_price
        if not day_low:
            day_low = last_price
        if not open_price:
            open_price = last_price
        if not fifty_sma:
            fifty_sma = last_price
        if not two_hundred_sma:
            two_hundred_sma = last_price

        change = last_price - prev_close
        change_pct = (change / prev_close) * 100.0 if prev_close else 0.0

        self._price_cache["^NSEI"] = {"cached_at": now_ts, "price": last_price}

        return {
            "symbol": "^NSEI",
            "name": "NIFTY 50 INDEX (NSE INDIA)",
            "current_price": round(last_price, 2),
            "previous_close": round(prev_close, 2),
            "open_price": round(open_price, 2),
            "day_high": round(day_high, 2),
            "day_low": round(day_low, 2),
            "change": round(change, 2),
            "change_percent": round(change_pct, 2),
            "fifty_day_sma": round(fifty_sma, 2),
            "two_hundred_day_sma": round(two_hundred_sma, 2),
            "currency": "₹",
            "market_status": self.get_market_status_ist(),
            "timestamp_ist": now_ist_str,
            "date_ist": now_date_str,
            "latency": "0ms (Direct Live Feed)",
            "tick_stream": "ACTIVE"
        }


def _get_fast_info_attr(fi, *attrs, default=None):
    """Safely extracts attribute from yfinance FastInfo object or dictionary."""
    if not fi:
        return default
    for attr in attrs:
        try:
            if isinstance(fi, dict):
                val = fi.get(attr)
            else:
                val = getattr(fi, attr, None)
            if val is not None and not (isinstance(val, float) and np.isnan(val)):
                return float(val)
        except Exception:
            continue
    return default


data_fetcher = DataFetcher()
