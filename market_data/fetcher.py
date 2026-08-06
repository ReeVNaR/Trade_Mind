import yfinance as yf
import pandas as pd
import numpy as np
import datetime
from typing import Dict, Any, Optional
from utils.logger import logger
from market_data.indicators import TechnicalIndicators, OptionAnalytics
from paper_trading.options_pricing import BlackScholes
from config.settings import settings

class MarketDataFetcher:
    """Fetches market data from Yahoo Finance for NIFTY 50 and India VIX."""

    def __init__(self, symbol: str = "^NSEI"):
        self.symbol = symbol

    def get_historical_candles(self, period: str = "5d", interval: str = "5m") -> pd.DataFrame:
        """Fetches real OHLCV historical candles using yfinance for NIFTY 50."""
        try:
            ticker = yf.Ticker(self.symbol)
            df = ticker.history(period=period, interval=interval)
            if df.empty or len(df) < 5:
                logger.warning(f"Insufficient live candle data for {self.symbol}. Retrying with 1d interval.")
                df = ticker.history(period="1mo", interval="1d")

            if not df.empty:
                # Keep standard columns
                cols = [c for c in ['Open', 'High', 'Low', 'Close', 'Volume'] if c in df.columns]
                df = df[cols]
                df = TechnicalIndicators.calculate_all(df)
                return df
            
            logger.warning(f"No yfinance data for {self.symbol}. Using fallback generator.")
            return self.generate_mock_candles()
        except Exception as e:
            logger.error(f"Error fetching yfinance candles for {self.symbol}: {e}")
            return self.generate_mock_candles()

    def get_live_quote(self) -> Dict[str, Any]:
        """Fetches real-time NIFTY spot LTP and India VIX from Yahoo Finance."""
        try:
            ticker = yf.Ticker(self.symbol)
            fast_info = ticker.fast_info
            ltp = fast_info.get("lastPrice", 0.0)
            
            if not ltp or ltp <= 0.0:
                df = ticker.history(period="1d", interval="1m")
                if not df.empty:
                    ltp = float(df['Close'].iloc[-1])
                else:
                    ltp = 22500.0

            # Fetch India VIX
            vix = 14.5
            try:
                vix_ticker = yf.Ticker("^INDIAVIX")
                vix_fast = vix_ticker.fast_info
                vix_val = vix_fast.get("lastPrice", 0.0)
                if vix_val and vix_val > 0:
                    vix = float(vix_val)
                else:
                    vix_df = vix_ticker.history(period="1d", interval="1m")
                    if not vix_df.empty:
                        vix = float(vix_df['Close'].iloc[-1])
            except Exception as e_vix:
                logger.debug(f"Could not fetch VIX live, using default 14.5: {e_vix}")

            return {
                "symbol": self.symbol,
                "ltp": round(float(ltp), 2),
                "vix": round(float(vix), 2),
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        except Exception as e:
            logger.error(f"Error fetching live quote: {e}")
            return {
                "symbol": self.symbol,
                "ltp": 22500.0,
                "vix": 14.5,
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

    def generate_mock_candles(self, count: int = 100, base_price: float = 22500.0) -> pd.DataFrame:
        """Generates realistic synthetic OHLCV data for testing when market is closed or offline."""
        np.random.seed(42)
        dates = pd.date_range(end=datetime.datetime.now(), periods=count, freq="5min")
        
        returns = np.random.normal(0.0001, 0.002, count)
        price_paths = base_price * np.exp(np.cumsum(returns))

        highs = price_paths * (1 + np.abs(np.random.normal(0, 0.001, count)))
        lows = price_paths * (1 - np.abs(np.random.normal(0, 0.001, count)))
        opens = price_paths + np.random.normal(0, 1.0, count)
        closes = price_paths
        volumes = np.random.randint(10000, 100000, count)

        df = pd.DataFrame({
            'Open': opens,
            'High': highs,
            'Low': lows,
            'Close': closes,
            'Volume': volumes
        }, index=dates)

        df = TechnicalIndicators.calculate_all(df)
        return df

    def get_option_chain_analytics(self, spot_price: float) -> Dict[str, Any]:
        """Generates option chain analytics including PCR and Max Pain."""
        step = settings.NIFTY_STRIKE_STEP
        atm_strike = round(spot_price / step) * step
        strikes = [atm_strike + i * step for i in range(-5, 6)]

        chain = []
        for s in strikes:
            # Synthetic open interest build-up based on strike proximity
            distance = abs(s - spot_price)
            ce_oi = int(max(5000, 50000 - distance * 50 + np.random.randint(-2000, 2000)))
            pe_oi = int(max(5000, 48000 - distance * 45 + np.random.randint(-2000, 2000)))

            ce_price = BlackScholes.option_price(spot_price, s, 7/365.0, 0.07, 0.15, "CE")
            pe_price = BlackScholes.option_price(spot_price, s, 7/365.0, 0.07, 0.15, "PE")

            chain.append({
                "strike": s,
                "CE": {"symbol": f"NIFTY_{s}_CE", "price": ce_price, "oi": ce_oi},
                "PE": {"symbol": f"NIFTY_{s}_PE", "price": pe_price, "oi": pe_oi}
            })

        pcr = OptionAnalytics.calculate_pcr(chain)
        max_pain = OptionAnalytics.calculate_max_pain(chain)

        return {
            "spot_price": spot_price,
            "atm_strike": atm_strike,
            "pcr": pcr,
            "max_pain": max_pain,
            "chain": chain
        }
