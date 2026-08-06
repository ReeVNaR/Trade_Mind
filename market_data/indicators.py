import pandas as pd
import numpy as np
from typing import Dict, Any, Tuple

class TechnicalIndicators:
    """Calculates quantitative technical indicators for NIFTY bars."""

    @staticmethod
    def calculate_all(df: pd.DataFrame) -> pd.DataFrame:
        """Applies all technical indicators to DataFrame."""
        if df.empty or len(df) < 5:
            return df

        df = df.copy()
        
        # Ensure column names are standard
        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            if col not in df.columns and col.lower() in df.columns:
                df[col] = df[col.lower()]

        # EMAs
        df['EMA9'] = df['Close'].ewm(span=9, adjust=False).mean()
        df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
        df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
        df['EMA200'] = df['Close'].ewm(span=200, adjust=False).mean()
        df['SMA20'] = df['Close'].rolling(window=20).mean()

        # VWAP
        if 'Volume' in df.columns and df['Volume'].sum() > 0:
            typical_price = (df['High'] + df['Low'] + df['Close']) / 3
            df['VWAP'] = (typical_price * df['Volume']).cumsum() / df['Volume'].cumsum()
        else:
            df['VWAP'] = (df['High'] + df['Low'] + df['Close']) / 3

        # RSI (14)
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, np.nan)
        df['RSI'] = 100 - (100 / (1 + rs))
        df['RSI'] = df['RSI'].fillna(50.0)

        # MACD (12, 26, 9)
        ema12 = df['Close'].ewm(span=12, adjust=False).mean()
        ema26 = df['Close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = ema12 - ema26
        df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']

        # ATR (14)
        high_low = df['High'] - df['Low']
        high_close = (df['High'] - df['Close'].shift()).abs()
        low_close = (df['Low'] - df['Close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['ATR'] = tr.rolling(window=14).mean().bfill()

        # Bollinger Bands (20, 2)
        std20 = df['Close'].rolling(window=20).std()
        df['BB_Upper'] = df['SMA20'] + (std20 * 2)
        df['BB_Lower'] = df['SMA20'] - (std20 * 2)
        df['BB_Middle'] = df['SMA20']

        # Supertrend (10, 3)
        df = TechnicalIndicators.supertrend(df, period=10, multiplier=3.0)

        # ADX (14)
        df = TechnicalIndicators.adx(df, period=14)

        return df

    @staticmethod
    def supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
        high_low = df['High'] - df['Low']
        high_close = (df['High'] - df['Close'].shift()).abs()
        low_close = (df['Low'] - df['Close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean().bfill()

        hl2 = (df['High'] + df['Low']) / 2
        basic_upper = hl2 + (multiplier * atr)
        basic_lower = hl2 - (multiplier * atr)

        final_upper = pd.Series(0.0, index=df.index)
        final_lower = pd.Series(0.0, index=df.index)
        supertrend = pd.Series(0.0, index=df.index)
        direction = pd.Series(1, index=df.index)

        for i in range(1, len(df)):
            # Upper band
            if basic_upper.iloc[i] < final_upper.iloc[i-1] or df['Close'].iloc[i-1] > final_upper.iloc[i-1]:
                final_upper.iloc[i] = basic_upper.iloc[i]
            else:
                final_upper.iloc[i] = final_upper.iloc[i-1]

            # Lower band
            if basic_lower.iloc[i] > final_lower.iloc[i-1] or df['Close'].iloc[i-1] < final_lower.iloc[i-1]:
                final_lower.iloc[i] = basic_lower.iloc[i]
            else:
                final_lower.iloc[i] = final_lower.iloc[i-1]

            # Trend direction
            if supertrend.iloc[i-1] == final_upper.iloc[i-1]:
                if df['Close'].iloc[i] > final_upper.iloc[i]:
                    direction.iloc[i] = 1
                    supertrend.iloc[i] = final_lower.iloc[i]
                else:
                    direction.iloc[i] = -1
                    supertrend.iloc[i] = final_upper.iloc[i]
            else:
                if df['Close'].iloc[i] < final_lower.iloc[i]:
                    direction.iloc[i] = -1
                    supertrend.iloc[i] = final_upper.iloc[i]
                else:
                    direction.iloc[i] = 1
                    supertrend.iloc[i] = final_lower.iloc[i]

        df['Supertrend'] = supertrend
        df['Supertrend_Direction'] = direction # 1 = Bullish, -1 = Bearish
        return df

    @staticmethod
    def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        up_move = df['High'].diff()
        down_move = df['Low'].shift() - df['Low']

        pos_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        neg_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        tr = df['ATR'] * period # Approximation
        tr = tr.replace(0, 1.0)

        pos_di = 100 * (pd.Series(pos_dm, index=df.index).rolling(period).mean() / tr)
        neg_di = 100 * (pd.Series(neg_dm, index=df.index).rolling(period).mean() / tr)

        dx = 100 * (pos_di - neg_di).abs() / (pos_di + neg_di).replace(0, np.nan)
        df['ADX'] = dx.rolling(period).mean().bfill()
        df['Plus_DI'] = pos_di.bfill()
        df['Minus_DI'] = neg_di.bfill()

        return df

class OptionAnalytics:
    """Calculates Put-Call Ratio (PCR) and Max Pain for Option Chains."""

    @staticmethod
    def calculate_pcr(chain: list) -> float:
        """Calculates Put Call Ratio (PCR) from option chain."""
        total_pe_oi = sum(item.get("PE", {}).get("oi", 1000) for item in chain)
        total_ce_oi = sum(item.get("CE", {}).get("oi", 1000) for item in chain)
        if total_ce_oi == 0:
            return 1.0
        return round(total_pe_oi / total_ce_oi, 2)

    @staticmethod
    def calculate_max_pain(chain: list) -> float:
        """Calculates Max Pain strike price where option buyers lose maximum money."""
        if not chain:
            return 0.0

        losses = {}
        for test_strike_item in chain:
            test_strike = test_strike_item["strike"]
            total_loss = 0.0
            for item in chain:
                strike = item["strike"]
                ce_oi = item.get("CE", {}).get("oi", 1000)
                pe_oi = item.get("PE", {}).get("oi", 1000)

                # Call option payout loss to seller
                if test_strike > strike:
                    total_loss += (test_strike - strike) * ce_oi
                # Put option payout loss to seller
                if test_strike < strike:
                    total_loss += (strike - test_strike) * pe_oi
            losses[test_strike] = total_loss

        max_pain_strike = min(losses, key=losses.get)
        return max_pain_strike
