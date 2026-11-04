"""
Shared Technical Indicators Module
Consolidates duplicate indicator functions across modules.
"""

import pandas as pd
import urllib.request
import json


def compute_rsi(series: pd.Series, period: int = 14, nan_on_insufficient: bool = False) -> float:
    """
    Compute RSI (Relative Strength Index) for a price series.
    
    Args:
        series: Price series (typically Close prices)
        period: RSI period (default 14)
        nan_on_insufficient: If True, return NaN when insufficient data; else return 50.0
    
    Returns:
        RSI value (0-100), or NaN/50.0 if insufficient data
    """
    if len(series) < period + 1:
        return float("nan") if nan_on_insufficient else 50.0
    
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])


def compute_atr(df: pd.DataFrame, period: int = 14) -> float:
    """
    Compute ATR (Average True Range) for OHLC dataframe.
    
    Args:
        df: DataFrame with High, Low, Close columns
        period: ATR period (default 14)
    
    Returns:
        ATR value, or 0.0 if insufficient data
    """
    if len(df) < period + 1:
        return 0.0
    
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    prev_close = close.shift(1)
    
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = true_range.rolling(window=period, min_periods=period).mean()
    return float(atr.iloc[-1])


def fetch_fear_greed(default_neutral: str = "Neutral") -> tuple:
    """
    Fetch Fear & Greed Index from alternative.me API.
    
    Args:
        default_neutral: Label for default neutral state
    
    Returns:
        Tuple of (value: int, classification: str)
    """
    try:
        req = urllib.request.Request(
            "https://api.alternative.me/fng/?limit=1",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
            return int(data["data"][0]["value"]), data["data"][0]["value_classification"]
    except Exception:
        return 50, default_neutral


def compute_ema(series: pd.Series, period: int) -> pd.Series:
    """Compute Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def compute_sma(series: pd.Series, period: int) -> pd.Series:
    """Compute Simple Moving Average."""
    return series.rolling(window=period, min_periods=period).mean()


def compute_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple:
    """
    Compute MACD (Moving Average Convergence Divergence).
    
    Returns:
        Tuple of (macd_line, signal_line, histogram)
    """
    ema_fast = compute_ema(series, fast)
    ema_slow = compute_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = compute_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_bollinger_bands(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> tuple:
    """
    Compute Bollinger Bands.
    
    Returns:
        Tuple of (upper_band, middle_band, lower_band)
    """
    sma = compute_sma(series, period)
    std = series.rolling(window=period, min_periods=period).std()
    upper = sma + (std * std_dev)
    lower = sma - (std * std_dev)
    return upper, sma, lower


def compute_stochastic(high: pd.Series, low: pd.Series, close: pd.Series, 
                       k_period: int = 14, d_period: int = 3) -> tuple:
    """
    Compute Stochastic Oscillator.
    
    Returns:
        Tuple of (%K, %D)
    """
    lowest_low = low.rolling(window=k_period, min_periods=k_period).min()
    highest_high = high.rolling(window=k_period, min_periods=k_period).max()
    k = 100 * ((close - lowest_low) / (highest_high - lowest_low))
    d = k.rolling(window=d_period, min_periods=d_period).mean()
    return k, d