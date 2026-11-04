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


def compute_heiken_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute Heiken Ashi candles from regular OHLC data.
    
    Heiken Ashi candles smooth price action and make trends more visible:
    - HA_Close = (Open + High + Low + Close) / 4
    - HA_Open = (Previous HA_Open + Previous HA_Close) / 2
    - HA_High = max(High, HA_Open, HA_Close)
    - HA_Low = min(Low, HA_Open, HA_Close)
    
    Returns:
        DataFrame with HA_Open, HA_High, HA_Low, HA_Close columns
    """
    if df is None or df.empty or len(df) < 2:
        return pd.DataFrame()
    
    ha_df = pd.DataFrame(index=df.index)
    
    # HA_Close = (Open + High + Low + Close) / 4
    ha_df["HA_Close"] = (df["Open"] + df["High"] + df["Low"] + df["Close"]) / 4
    
    # HA_Open = (Previous HA_Open + Previous HA_Close) / 2
    ha_open = [0.0] * len(df)
    ha_open[0] = (df["Open"].iloc[0] + df["Close"].iloc[0]) / 2
    for i in range(1, len(df)):
        ha_open[i] = (ha_open[i-1] + ha_df["HA_Close"].iloc[i-1]) / 2
    ha_df["HA_Open"] = ha_open
    
    # HA_High = max(High, HA_Open, HA_Close)
    ha_df["HA_High"] = pd.concat([df["High"], ha_df["HA_Open"], ha_df["HA_Close"]], axis=1).max(axis=1)
    
    # HA_Low = min(Low, HA_Open, HA_Close)
    ha_df["HA_Low"] = pd.concat([df["Low"], ha_df["HA_Open"], ha_df["HA_Close"]], axis=1).min(axis=1)
    
    return ha_df


def compute_heiken_ashi_trend(ha_df: pd.DataFrame, lookback: int = 5) -> dict:
    """
    Analyze Heiken Ashi trend from HA candles.
    
    Returns:
        dict with trend info: direction, strength, consecutive_bars
    """
    if ha_df is None or ha_df.empty or len(ha_df) < 2:
        return {"direction": "NEUTRAL", "strength": 0, "consecutive": 0}
    
    # Determine trend from HA candles
    ha_close = ha_df["HA_Close"]
    ha_open = ha_df["HA_Open"]
    
    # Green candles = HA_Close > HA_Open
    green = ha_close > ha_open
    red = ha_close < ha_open
    
    # Count consecutive green/red
    consecutive_green = 0
    consecutive_red = 0
    for is_green in reversed(green.tolist()):
        if is_green:
            consecutive_green += 1
        else:
            break
    for is_red in reversed((~green).tolist()):
        if is_red:
            consecutive_red += 1
        else:
            break
    
    if consecutive_green >= 3:
        return {"direction": "BULLISH", "strength": min(consecutive_green / 10.0, 1.0), "consecutive": consecutive_green}
    elif consecutive_red >= 3:
        return {"direction": "BEARISH", "strength": min(consecutive_red / 10.0, 1.0), "consecutive": consecutive_red}
    else:
        return {"direction": "NEUTRAL", "strength": 0.0, "consecutive": max(consecutive_green, consecutive_red)}


def detect_standard_patterns(df: pd.DataFrame, lookback: int = 3) -> dict:
    """
    Detect 8 standard candle patterns:
    1. Bullish/Bearish Engulfing
    2. Bullish/Bearish Harami
    3. Morning Star / Evening Star
    4. Piercing Line / Dark Cloud Cover
    5. Three White Soldiers / Three Black Crows
    6. Tweezer Top / Bottom
    
    Returns:
        dict with pattern name, signal (BUY/SELL/NEUTRAL), strength, description
    """
    if df is None or df.empty or len(df) < 3:
        return {"patterns": [], "signal": "NEUTRAL", "strength": 0.0}
    
    patterns = []
    recent = df.tail(lookback + 2)  # Need extra for patterns like morning star
    
    for i in range(-lookback, 0):
        if abs(i) >= len(df):
            continue
            
        candle = df.iloc[i]
        prev = df.iloc[i-1] if i-1 >= -len(df) else None
        prev2 = df.iloc[i-2] if i-2 >= -len(df) else None
        
        o, h, l, c = candle["Open"], candle["High"], candle["Low"], candle["Close"]
        body = abs(c - o)
        range_val = h - l
        
        if range_val == 0:
            continue
            
        body_ratio = body / range_val
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        is_bullish = c > o
        is_bearish = c < o
        
        # 1. ENGULFING
        if prev is not None:
            prev_o, prev_c = prev["Open"], prev["Close"]
            prev_body = abs(prev_c - prev_o)
            prev_range = prev["High"] - prev["Low"]
            
            if prev_range > 0:
                # Bullish Engulfing: prev bearish, current bullish, current body engulfs prev body
                if prev_c < prev_o and c > o and c >= prev_o and o <= prev_c and body > prev_body * 1.1:
                    patterns.append({
                        "name": "BULLISH_ENGULFING",
                        "signal": "BUY",
                        "strength": 0.8,
                        "description": "Bullish engulfing - strong reversal signal"
                    })
                # Bearish Engulfing
                elif prev_c > prev_o and c < o and c <= prev_o and o >= prev_c and body > prev_body * 1.1:
                    patterns.append({
                        "name": "BEARISH_ENGULFING",
                        "signal": "SELL",
                        "strength": 0.8,
                        "description": "Bearish engulfing - strong reversal signal"
                    })
        
        # HARAMI
        if prev is not None:
            prev_o, prev_c = prev["Open"], prev["Close"]
            prev_body = abs(prev_c - prev_o)
            prev_range = prev["High"] - prev["Low"]
            
            if prev_range > 0 and body_ratio < 0.5 and body < prev_body * 0.5:
                if prev_c > prev_o and c < o and o < prev_c and c > prev_o:
                    patterns.append({
                        "name": "BEARISH_HARAMI",
                        "signal": "SELL",
                        "strength": 0.6,
                        "description": "Bearish harami - potential reversal"
                    })
                elif prev_c < prev_o and c > o and o > prev_c and c < prev_o:
                    patterns.append({
                        "name": "BULLISH_HARAMI",
                        "signal": "BUY",
                        "strength": 0.6,
                        "description": "Bullish harami - potential reversal"
                    })
        
        # PIERCING LINE / DARK CLOUD COVER (2-candle patterns)
        if prev is not None:
            prev_o, prev_c = prev["Open"], prev["Close"]
            prev_mid = (prev_o + prev_c) / 2
            
            # Piercing Line: prev bearish, current bullish, closes above prev midpoint
            if prev_c < prev_o and c > o and c > prev_mid and o < prev_c:
                patterns.append({
                    "name": "PIERCING_LINE",
                    "signal": "BUY",
                    "strength": 0.7,
                    "description": "Piercing line - bullish reversal"
                })
            # Dark Cloud Cover: prev bullish, current bearish, closes below prev midpoint
            elif prev_c > prev_o and c < o and c < prev_mid and o > prev_c:
                patterns.append({
                    "name": "DARK_CLOUD_COVER",
                    "signal": "SELL",
                    "strength": 0.7,
                    "description": "Dark cloud cover - bearish reversal"
                })
        
        # MORNING STAR / EVENING STAR (3-candle patterns)
        if prev is not None and prev2 is not None:
            prev_o, prev_c = prev["Open"], prev["Close"]
            prev2_o, prev2_c = prev2["Open"], prev2["Close"]
            
            # Morning Star: prev2 bearish, prev small (doji/spinning top), current bullish closing above prev2 midpoint
            if prev2_c < prev2_o and abs(prev_c - prev_o) / (prev["High"] - prev["Low"]) < 0.3:
                prev2_mid = (prev2_o + prev2_c) / 2
                if c > o and c > prev2_mid:
                    patterns.append({
                        "name": "MORNING_STAR",
                        "signal": "BUY",
                        "strength": 0.9,
                        "description": "Morning star - strong bullish reversal"
                    })
            
            # Evening Star: prev2 bullish, prev small, current bearish closing below prev2 midpoint
            elif prev2_c > prev2_o and abs(prev_c - prev_o) / (prev["High"] - prev["Low"]) < 0.3:
                prev2_mid = (prev2_o + prev2_c) / 2
                if c < o and c < prev2_mid:
                    patterns.append({
                        "name": "EVENING_STAR",
                        "signal": "SELL",
                        "strength": 0.9,
                        "description": "Evening star - strong bearish reversal"
                    })
        
        # THREE WHITE SOLDIERS / THREE BLACK CROWS (3-candle patterns)
        if len(df) >= 3:
            c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
            
            # Three White Soldiers: 3 consecutive bullish candles, each closing higher
            if (c1["Close"] > c1["Open"] and c2["Close"] > c2["Open"] and c3["Close"] > c3["Open"] and
                c3["Close"] > c2["Close"] > c1["Close"] and
                c1["Close"] > c1["Open"] and c2["Close"] > c2["Open"] and c3["Close"] > c3["Open"]):
                patterns.append({
                    "name": "THREE_WHITE_SOLDIERS",
                    "signal": "BUY",
                    "strength": 0.85,
                    "description": "Three white soldiers - strong bullish continuation"
                })
            
            # Three Black Crows: 3 consecutive bearish candles, each closing lower
            if (c1["Close"] < c1["Open"] and c2["Close"] < c2["Open"] and c3["Close"] < c3["Open"] and
                c3["Close"] < c2["Close"] < c1["Close"] and
                c1["Close"] < c1["Open"] and c2["Close"] < c2["Open"] and c3["Close"] < c3["Open"]):
                patterns.append({
                    "name": "THREE_BLACK_CROWS",
                    "signal": "SELL",
                    "strength": 0.85,
                    "description": "Three black crows - strong bearish continuation"
                })
        
        # TWEEZER TOP / BOTTOM
        if prev is not None:
            # Tweezer Top: two candles with same high
            if abs(h - prev["High"]) / h < 0.001 and prev["Close"] > prev["Open"] and c < o:
                patterns.append({
                    "name": "TWEEZER_TOP",
                    "signal": "SELL",
                    "strength": 0.65,
                    "description": "Tweezer top - bearish reversal at resistance"
                })
            # Tweezer Bottom: two candles with same low
            elif abs(l - prev["Low"]) / l < 0.001 and prev["Close"] < prev["Open"] and c > o:
                patterns.append({
                    "name": "TWEEZER_BOTTOM",
                    "signal": "BUY",
                    "strength": 0.65,
                    "description": "Tweezer bottom - bullish reversal at support"
                })
    
    # Determine overall signal
    buy_signals = [p for p in patterns if p["signal"] == "BUY"]
    sell_signals = [p for p in patterns if p["signal"] == "SELL"]
    
    if buy_signals:
        overall_signal = "BUY"
        strength = max(p["strength"] for p in buy_signals)
    elif sell_signals:
        overall_signal = "SELL"
        strength = max(p["strength"] for p in sell_signals)
    else:
        overall_signal = "NEUTRAL"
        strength = 0.0
    
    return {
        "patterns": patterns,
        "signal": overall_signal,
        "strength": strength
    }