import pandas as pd
import numpy as np
from typing import Dict, Any, Optional


class TechnicalIndicators:
    """
    Computes technical indicators over OHLCV DataFrames.
    Includes VWAP, Supertrend, RSI, Stochastic RSI, MACD, EMA, Bollinger Bands, and ATR.
    """

    @staticmethod
    def rsi(series: pd.Series, period: int = 14) -> pd.Series:
        """Calculates Relative Strength Index (RSI)."""
        delta = series.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi.fillna(50.0)

    @staticmethod
    def stoch_rsi(series: pd.Series, period: int = 14, k_period: int = 3, d_period: int = 3) -> Dict[str, pd.Series]:
        """Calculates Stochastic RSI (%K and %D)."""
        rsi_series = TechnicalIndicators.rsi(series, period=period)
        min_rsi = rsi_series.rolling(window=period, min_periods=1).min()
        max_rsi = rsi_series.rolling(window=period, min_periods=1).max()
        
        stoch = (rsi_series - min_rsi) / (max_rsi - min_rsi).replace(0, np.nan)
        stoch_k = stoch.rolling(window=k_period, min_periods=1).mean() * 100.0
        stoch_d = stoch_k.rolling(window=d_period, min_periods=1).mean()
        return {
            "stoch_k": stoch_k.fillna(50.0),
            "stoch_d": stoch_d.fillna(50.0)
        }

    @staticmethod
    def vwap(df: pd.DataFrame) -> pd.Series:
        """
        Calculates Volume Weighted Average Price (VWAP).
        Essential for Indian equity day trading and benchmark pricing.
        """
        high = df["high"]
        low = df["low"]
        close = df["close"]
        volume = df["volume"].replace(0, 1.0)
        
        typical_price = (high + low + close) / 3.0
        vp = typical_price * volume
        
        # Cumulative sum over DataFrame
        cum_vp = vp.cumsum()
        cum_vol = volume.cumsum()
        
        vwap_series = cum_vp / cum_vol
        return vwap_series.fillna(close)

    @staticmethod
    def ema(series: pd.Series, span: int) -> pd.Series:
        """Calculates Exponential Moving Average (EMA)."""
        return series.ewm(span=span, adjust=False).mean()

    @staticmethod
    def sma(series: pd.Series, window: int) -> pd.Series:
        """Calculates Simple Moving Average (SMA)."""
        return series.rolling(window=window, min_periods=1).mean()

    @staticmethod
    def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, pd.Series]:
        """Calculates MACD Line, Signal Line, and MACD Histogram."""
        fast_ema = TechnicalIndicators.ema(series, span=fast)
        slow_ema = TechnicalIndicators.ema(series, span=slow)
        macd_line = fast_ema - slow_ema
        signal_line = TechnicalIndicators.ema(macd_line, span=signal)
        histogram = macd_line - signal_line
        return {
            "macd": macd_line,
            "macd_signal": signal_line,
            "macd_hist": histogram
        }

    @staticmethod
    def bollinger_bands(series: pd.Series, window: int = 20, num_std: float = 2.0) -> Dict[str, pd.Series]:
        """Calculates Bollinger Bands (Upper, Middle, Lower, and %B)."""
        middle = series.rolling(window=window, min_periods=1).mean()
        std = series.rolling(window=window, min_periods=1).std(ddof=0).fillna(0)
        upper = middle + (std * num_std)
        lower = middle - (std * num_std)
        
        band_width = upper - lower
        percent_b = (series - lower) / band_width.replace(0, np.nan)
        percent_b = percent_b.fillna(0.5)

        return {
            "bb_upper": upper,
            "bb_middle": middle,
            "bb_lower": lower,
            "bb_percent": percent_b
        }

    @staticmethod
    def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculates Average True Range (ATR)."""
        high = df["high"]
        low = df["low"]
        close = df["close"]
        prev_close = close.shift(1)

        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()

        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = true_range.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        return atr.fillna(true_range.mean())

    @staticmethod
    def supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> Dict[str, pd.Series]:
        """Calculates Supertrend indicator (trend direction and upper/lower bands)."""
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values
        n = len(df)
        
        atr_series = TechnicalIndicators.atr(df, period=period).values
        hl2 = (high + low) / 2.0
        
        upper_band = hl2 + (multiplier * atr_series)
        lower_band = hl2 - (multiplier * atr_series)
        
        supertrend = np.zeros(n)
        direction = np.ones(n)  # 1 for bullish (buy), -1 for bearish (sell)
        
        for i in range(1, n):
            if close[i - 1] > upper_band[i - 1]:
                upper_band[i] = max(upper_band[i], upper_band[i - 1])
            if close[i - 1] < lower_band[i - 1]:
                lower_band[i] = min(lower_band[i], lower_band[i - 1])
                
            if direction[i - 1] == 1 and close[i] < lower_band[i - 1]:
                direction[i] = -1
            elif direction[i - 1] == -1 and close[i] > upper_band[i - 1]:
                direction[i] = 1
            else:
                direction[i] = direction[i - 1]
                
            supertrend[i] = lower_band[i] if direction[i] == 1 else upper_band[i]

        return {
            "supertrend": pd.Series(supertrend, index=df.index),
            "supertrend_direction": pd.Series(direction, index=df.index)
        }


def calculate_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Enriches an OHLCV DataFrame with complete technical indicators.
    Expected columns: open, high, low, close, volume.
    """
    if df.empty or len(df) < 5:
        return df

    data = df.copy()
    close = data["close"]

    # Moving Averages
    data["ema_9"] = TechnicalIndicators.ema(close, span=9)
    data["ema_21"] = TechnicalIndicators.ema(close, span=21)
    data["ema_50"] = TechnicalIndicators.ema(close, span=50)
    data["ema_200"] = TechnicalIndicators.ema(close, span=200)
    data["sma_20"] = TechnicalIndicators.sma(close, window=20)
    data["sma_50"] = TechnicalIndicators.sma(close, window=50)

    # RSI & Stoch RSI
    data["rsi_14"] = TechnicalIndicators.rsi(close, period=14)
    stoch = TechnicalIndicators.stoch_rsi(close)
    data["stoch_k"] = stoch["stoch_k"]
    data["stoch_d"] = stoch["stoch_d"]

    # VWAP (Key for Indian Intraday / Swing)
    data["vwap"] = TechnicalIndicators.vwap(data)

    # MACD
    macd_dict = TechnicalIndicators.macd(close)
    data["macd"] = macd_dict["macd"]
    data["macd_signal"] = macd_dict["macd_signal"]
    data["macd_hist"] = macd_dict["macd_hist"]

    # Bollinger Bands
    bb_dict = TechnicalIndicators.bollinger_bands(close)
    data["bb_upper"] = bb_dict["bb_upper"]
    data["bb_middle"] = bb_dict["bb_middle"]
    data["bb_lower"] = bb_dict["bb_lower"]
    data["bb_percent"] = bb_dict["bb_percent"]

    # ATR
    data["atr_14"] = TechnicalIndicators.atr(data, period=14)

    # Supertrend
    try:
        st_dict = TechnicalIndicators.supertrend(data)
        data["supertrend"] = st_dict["supertrend"]
        data["supertrend_direction"] = st_dict["supertrend_direction"]
        data["supertrend_dir"] = st_dict["supertrend_direction"]
    except Exception:
        data["supertrend"] = data["close"]
        data["supertrend_direction"] = 1
        data["supertrend_dir"] = 1

    return data
