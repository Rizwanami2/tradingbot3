#!/usr/bin/env python3
"""
trader-gold-btc: autotrader_pipeline.py
Method 1: The Deterministic Hard-Asset Pipeline Engine for Gold (XAU) & Bitcoin (BTC).
Now integrated with the SelfLearningEngine for adaptive weight optimization.

Stages:
  1. Structural Location Scan (Golden Pocket 0.618 Fib, 50/200 SMA)
  2. Microstructure Anti-Trap Filter (Bull/Bear Trap Wick Analysis)
  3. Macro & Momentum Context (DXY, 10Y Yield, RSI, Mayer Multiple, Fear & Greed)
  4. Dual Confluence Scoring:
     - 10-Point Deterministic Baseline Veto Matrix
     - Adaptive Learned Confluence Score (via self_learning.py)
"""

import warnings
warnings.filterwarnings("ignore")
import os
os.environ["PYTHONWARNINGS"] = "ignore"
import logging
logging.captureWarnings(True)

try:
    from utils.logger import get_logger
    logger = get_logger("autotrader_pipeline")
except Exception:
    logger = logging.getLogger("autotrader_pipeline")

try:
    from config_validator import validate_config
except Exception:
    def validate_config(*args, **kwargs):
        return True, []

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import argparse
import json
import time
import urllib.request
import ssl
from typing import Dict, Tuple, Any

# Fix for Windows VPS missing root CA certificates or hosting provider SSL inspection
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context
from datetime import datetime
import numpy as np

try:
    import yfinance as yf
except ImportError:
    print("❌ yfinance required. Run: py -3.11 -m pip install yfinance")
    sys.exit(1)

# Import MT5 for live broker data (recommended for live trading)
try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

# Import Self-Learning Engine
try:
    from self_learning import SelfLearningEngine
    LEARNING_AVAILABLE = True
    learning_engine = SelfLearningEngine()
except Exception:
    LEARNING_AVAILABLE = False

# Import Multi-Source Market Data Engine
try:
    from market_data import market_data_feed
    MARKET_DATA_AVAILABLE = True
except Exception:
    market_data_feed = None
    MARKET_DATA_AVAILABLE = False

# Import Institutional & Smart Money Engine (HTF Bias)
try:
    from institutional_engine import institutional_engine
    INSTITUTIONAL_AVAILABLE = True
except Exception:
    institutional_engine = None
    INSTITUTIONAL_AVAILABLE = False
# Import Multi-Strategy Risk Engine for Practical TP/SL
try:
    import risk_engine
    RISK_ENGINE_AVAILABLE = True
except Exception:
    RISK_ENGINE_AVAILABLE = False

# Import MT5 Live Broker for direct broker data (eliminates data/execution mismatch)
try:
    from mt5_executor import MT5LiveBroker, live_broker
    MT5_BROKER_AVAILABLE = True
except Exception:
    MT5LiveBroker = None
    live_broker = None
    MT5_BROKER_AVAILABLE = False

# Env flag: prefer MT5 live data over yfinance (recommended for live trading)
USE_MT5_LIVE_DATA = os.environ.get("USE_MT5_LIVE_DATA", "true").lower() in ("true", "1", "yes")


def send_pipeline_crash_alert(exc: Exception, context: str = "Autotrader Pipeline"):
    try:
        import traceback
        tb = traceback.format_exc()
        tb_lines = tb.strip().split("\n")
        short_tb = "\n".join(tb_lines[-4:]) if len(tb_lines) >= 4 else tb
        import telegram_bot
        tok, cid = telegram_bot.get_credentials()
        if tok and cid:
            msg = (
                f"🚨 *PIPELINE CRASH ALERT*\n"
                f"• Context: `{context}`\n"
                f"• Error: `{type(exc).__name__}: {exc}`\n"
                f"• Traceback:\n```\n{short_tb}\n```"
            )
            telegram_bot.send_message(tok, cid, msg)
    except Exception:
        pass


def compute_rsi(series, period: int = 14) -> float:
    if len(series) < period + 1:
        return 50.0
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])


def fetch_fear_greed():
    try:
        req = urllib.request.Request("https://api.alternative.me/fng/?limit=1", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
            return int(data["data"][0]["value"]), data["data"][0]["value_classification"]
    except Exception:
        return 50, "Neutral"


# ── Indicator Cache (TTL) to avoid redundant data fetches ──
_indicator_cache: Dict[str, Tuple[float, Any]] = {}
_CACHE_TTL_SECONDS = int(os.environ.get("INDICATOR_CACHE_TTL_SECONDS", "30"))

# MT5 symbol mapping (yfinance -> MT5)
_MT5_SYMBOL_MAP = {
    "GC=F": "XAUUSD",
    "XAUUSD": "XAUUSD",
    "GOLD": "XAUUSD",
    "BTC-USD": "BTCUSD",
    "BTCUSD": "BTCUSD",
    "BTC": "BTCUSD",
}

_MT5_TIMEFRAME_MAP = {
    "1d": mt5.TIMEFRAME_D1 if (MT5_BROKER_AVAILABLE and mt5) else None,
    "1h": mt5.TIMEFRAME_H1 if (MT5_BROKER_AVAILABLE and mt5) else None,
    "15m": mt5.TIMEFRAME_M15 if (MT5_BROKER_AVAILABLE and mt5) else None,
    "5m": mt5.TIMEFRAME_M5 if (MT5_BROKER_AVAILABLE and mt5) else None,
    "1m": mt5.TIMEFRAME_M1 if (MT5_BROKER_AVAILABLE and mt5) else None,
}


def _mt5_rates_to_dataframe(rates, symbol: str):
    """Convert MT5 copy_rates_from_pos result to yfinance-compatible DataFrame."""
    import pandas as pd
    if rates is None or len(rates) == 0:
        return pd.DataFrame()
    df = pd.DataFrame(rates)
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.set_index("time", inplace=True)
    # Rename MT5 columns to yfinance-compatible names
    col_map = {
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "tick_volume": "Volume",
        "real_volume": "Volume",
    }
    for src, dst in col_map.items():
        if src in df.columns and dst not in df.columns:
            df[dst] = df[src]
    # Ensure required columns exist
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col not in df.columns:
            df[col] = 0.0
    df = df[["Open", "High", "Low", "Close", "Volume"]]
    return df


def _get_mt5_hist(symbol: str, count: int = 400, timeframe=None) -> Any:
    """Fetch historical bars directly from live MT5 broker."""
    if not MT5_BROKER_AVAILABLE or live_broker is None:
        return None
    try:
        if not live_broker.ensure_connected():
            return None
        mt5_symbol = _MT5_SYMBOL_MAP.get(symbol, symbol)
        tf = timeframe or mt5.TIMEFRAME_H1
        rates = mt5.copy_rates_from_pos(mt5_symbol, tf, 0, count)
        if rates is None or len(rates) == 0:
            return None
        return _mt5_rates_to_dataframe(rates, symbol)
    except Exception as e:
        logger.debug(f"MT5 data fetch failed for {symbol}: {e}")
        return None


def _get_cached_hist(symbol: str, period: str = "350d"):
    """Fetch historical bars with TTL caching. Prefers MT5 live broker data
    (eliminates data/execution mismatch), falls back to yfinance."""
    now = time.time()
    cache_key = f"{symbol}:{period}"
    if cache_key in _indicator_cache:
        cached_time, cached_hist = _indicator_cache[cache_key]
        if now - cached_time < _CACHE_TTL_SECONDS:
            return cached_hist

    hist = None

    # Priority 1: MT5 live broker (real broker data, matches execution prices)
    if USE_MT5_LIVE_DATA and MT5_BROKER_AVAILABLE and mt5:
        # Determine count based on period string
        if period.endswith("d"):
            days = int(period[:-1]) if period[:-1].isdigit() else 350
            count = min(days * 24, 400)  # H1 bars, max 400
            tf = mt5.TIMEFRAME_H1
        elif period.endswith("h"):
            hours = int(period[:-1]) if period[:-1].isdigit() else 168
            count = min(hours, 400)
            tf = mt5.TIMEFRAME_H1
        else:
            count = 400
            tf = mt5.TIMEFRAME_H1

        hist = _get_mt5_hist(symbol, count=count, timeframe=tf)

    # Priority 2: market_data_feed (yfinance with sanitization)
    if (hist is None or hist.empty or len(hist) < 30) and MARKET_DATA_AVAILABLE and market_data_feed:
        try:
            hist = market_data_feed.get_historical_bars(
                "GOLD" if "XAU" in symbol.upper() or "GOLD" in symbol.upper() else "BTC",
                period=period,
                min_bars=30,
            )
        except Exception as e:
            logger.debug(f"market_data_feed failed for {symbol}: {e}")

    # Priority 3: Direct yfinance (last resort, for backtesting/research)
    if (hist is None or hist.empty or len(hist) < 30):
        try:
            t = yf.Ticker(symbol)
            hist = t.history(period=period)
        except Exception as e:
            logger.debug(f"yfinance direct failed for {symbol}: {e}")
            hist = None

    if hist is not None and not hist.empty:
        _indicator_cache[cache_key] = (now, hist)
    return hist


def analyze_asset_pipeline(symbol: str, asset_type: str, dxy_chg: float, tnx_chg: float, gsr: float, fg_val: int):
    # Priority: MT5 live broker first (matches execution prices), then yfinance
    hist = _get_cached_hist(symbol, period="350d")
    if hist.empty or len(hist) < 30:
        return None

    htf_bias = institutional_engine.compute_htf_bias(hist, asset_type) if (INSTITUTIONAL_AVAILABLE and institutional_engine) else {
        "bias": "NEUTRAL", "summary": "⚪ Neutral"
    }

    # STAGE 1: LOCATION & STRUCTURE
    curr = hist["Close"].iloc[-1]
    ma50 = hist["Close"].rolling(50).mean().iloc[-1] if len(hist) >= 50 else np.nan
    ma200 = hist["Close"].rolling(200).mean().iloc[-1] if len(hist) >= 200 else np.nan

    recent_60 = hist.tail(60)
    sw_high = recent_60["High"].max()
    sw_low = recent_60["Low"].min()
    fib_500 = sw_high - 0.500 * (sw_high - sw_low)
    fib_618 = sw_high - 0.618 * (sw_high - sw_low)
    fib_650 = sw_high - 0.650 * (sw_high - sw_low)

    in_golden_pocket = (curr >= fib_650 * 0.985) and (curr <= fib_618 * 1.02)

    # STAGE 2: ANTI-TRAP VERIFICATION
    curr_bar = hist.iloc[-1]
    c_open, c_high, c_low, c_close = curr_bar["Open"], curr_bar["High"], curr_bar["Low"], curr_bar["Close"]
    c_range = c_high - c_low
    upper_wick = c_high - max(c_open, c_close)
    lower_wick = min(c_open, c_close) - c_low

    trap_state = "CLEAN"
    if c_range > 0:
        if (upper_wick / c_range >= 0.40) and (curr >= fib_500):
            trap_state = "BULL_TRAP"
        elif (lower_wick / c_range >= 0.40) and (curr <= fib_650):
            trap_state = "BEAR_TRAP"

    # STAGE 3: ASSET SPECIFIC METRICS
    rsi = compute_rsi(hist["Close"], 14)
    mayer = (curr / ma200) if not np.isnan(ma200) and ma200 > 0 else 1.0
    daily_rets = hist["Close"].pct_change().dropna()
    vol30 = float(daily_rets.tail(30).std() * np.sqrt(365) * 100) if len(daily_rets) >= 30 else 30.0

    # STAGE 4: DUAL-SIDED CONFLUENCE SCORING & ACTIVE FEATURES (BUY & SELL)
    score_buy = 0
    factors_buy = []
    score_sell = 0
    factors_sell = []

    if asset_type == "BTC":
        # Buy Factors
        feat_dxy = dxy_chg < 0.2
        feat_yield = tnx_chg < 1.0
        feat_ma200 = curr > ma200
        feat_mayer = 0.85 <= mayer <= 1.50
        feat_rsi = 40 <= rsi <= 65
        feat_fg = 25 <= fg_val <= 70
        feat_no_trap = trap_state != "BULL_TRAP"
        feat_ma50 = curr > ma50
        feat_vol = vol30 < 75
        feat_near_support = (curr - sw_low) / curr <= 0.05

        if feat_dxy: score_buy += 1; factors_buy.append("Macro: DXY favorable (USD weakness/neutral)")
        if feat_yield: score_buy += 1; factors_buy.append("Macro: 10Y Yields controlled")
        if feat_ma200: score_buy += 1; factors_buy.append(f"Trend: Above 200 SMA (${ma200:,.0f})")
        if feat_mayer: score_buy += 1; factors_buy.append(f"Valuation: Mayer Multiple healthy ({mayer:.2f})")
        if feat_rsi: score_buy += 1; factors_buy.append(f"Momentum: RSI in healthy expansion zone ({rsi:.1f})")
        if in_golden_pocket: score_buy += 1; factors_buy.append("Level: Resting in Golden Pocket (0.618 Fib)")
        if feat_fg: score_buy += 1; factors_buy.append(f"Sentiment: Fear & Greed balanced ({fg_val})")
        if feat_no_trap: score_buy += 1; factors_buy.append("Microstructure: Zero Bull Trap rejection")
        if feat_ma50: score_buy += 1; factors_buy.append("Momentum: Above 50 SMA")
        if feat_vol: score_buy += 1; factors_buy.append(f"Risk: Volatility normalized ({vol30:.1f}%)")

        # Symmetrical Sell Factors
        sell_dxy = dxy_chg > -0.2
        sell_yield = tnx_chg > -1.0
        sell_ma200 = curr < ma200
        sell_mayer = (mayer > 1.80 or mayer < 0.85)
        sell_rsi = (rsi <= 48 or rsi >= 70)
        sell_fg = (fg_val >= 75 or fg_val <= 20)
        sell_no_trap = trap_state != "BEAR_TRAP"
        sell_ma50 = curr < ma50
        sell_vol = vol30 < 75
        sell_near_res = (sw_high - curr) / curr <= 0.05

        if sell_dxy: score_sell += 1; factors_sell.append("Macro: USD resilient (Headwind for BTC)")
        if sell_yield: score_sell += 1; factors_sell.append("Macro: Yields firm")
        if sell_ma200: score_sell += 1; factors_sell.append(f"Trend: Below 200 SMA (${ma200:,.0f})")
        if sell_mayer: score_sell += 1; factors_sell.append(f"Valuation: Mayer Multiple stretched/weak ({mayer:.2f})")
        if sell_rsi: score_sell += 1; factors_sell.append(f"Momentum: RSI bearish or overbought ({rsi:.1f})")
        if sell_near_res: score_sell += 1; factors_sell.append("Level: Testing swing resistance ceiling")
        if sell_fg: score_sell += 1; factors_sell.append(f"Sentiment: Extreme sentiment exhaustion ({fg_val})")
        if sell_no_trap: score_sell += 1; factors_sell.append("Microstructure: Clean bear auction; zero Bear Trap")
        if sell_ma50: score_sell += 1; factors_sell.append("Momentum: Below 50 SMA")
        if sell_vol: score_sell += 1; factors_sell.append(f"Risk: Volatility tradeable ({vol30:.1f}%)")

    else:  # GOLD
        # Buy Factors
        feat_dxy = dxy_chg <= 0.05
        feat_yield = tnx_chg <= 0.2
        feat_ma200 = curr > ma200
        feat_ma50 = curr > ma50
        feat_rsi = 40 <= rsi <= 60
        feat_gsr = gsr >= 75
        feat_vol = vol30 < 22
        feat_no_trap = trap_state != "BULL_TRAP"
        feat_near_support = (curr - sw_low) / curr <= 0.05

        if feat_dxy: score_buy += 1; factors_buy.append("Macro: DXY weakness (Gold tailwind)")
        if feat_yield: score_buy += 1; factors_buy.append("Macro: 10Y Yields easing (Real yield tailwind)")
        if feat_ma200: score_buy += 1; factors_buy.append(f"Trend: Above 200 SMA (${ma200:,.0f})")
        if feat_ma50: score_buy += 1; factors_buy.append("Trend: Above 50 SMA")
        if feat_rsi: score_buy += 1; factors_buy.append(f"Momentum: RSI pullback sweet spot ({rsi:.1f})")
        if in_golden_pocket: score_buy += 1; factors_buy.append("Level: Resting in Golden Pocket (0.618 Fib)")
        if feat_gsr: score_buy += 1; factors_buy.append(f"Metals Value: GSR elevated ({gsr:.1f}x)")
        if feat_vol: score_buy += 1; factors_buy.append(f"Risk: Orderly volatility ({vol30:.1f}%)")
        if feat_no_trap: score_buy += 1; factors_buy.append("Microstructure: Clean auction; no Bull Trap")
        if feat_near_support: score_buy += 1; factors_buy.append("Structure: Near major swing support floor")

        # Symmetrical Sell Factors
        sell_dxy = dxy_chg >= -0.05
        sell_yield = tnx_chg >= -0.2
        sell_ma200 = curr < ma200
        sell_ma50 = curr < ma50
        sell_rsi = (25.0 <= rsi <= 48.0) or (rsi >= 65.0)  # bearish momentum breakdown or overbought rejection (avoids <25 oversold trap)
        sell_gsr = gsr < 75
        sell_vol = vol30 < 25
        sell_no_trap = trap_state != "BEAR_TRAP"
        sell_near_res = (sw_high - curr) / curr <= 0.05

        if sell_dxy: score_sell += 1; factors_sell.append("Macro: DXY firm (Gold headwind)")
        if sell_yield: score_sell += 1; factors_sell.append("Macro: 10Y Yields firming")
        if sell_ma200: score_sell += 1; factors_sell.append(f"Trend: Below 200 SMA (${ma200:,.0f})")
        if sell_ma50: score_sell += 1; factors_sell.append("Trend: Below 50 SMA")
        if sell_rsi: score_sell += 1; factors_sell.append(f"Momentum: RSI bearish or overbought ({rsi:.1f})")
        if sell_near_res: score_sell += 1; factors_sell.append("Level: Near major swing resistance ceiling")
        if sell_gsr: score_sell += 1; factors_sell.append(f"Metals Value: GSR compressed ({gsr:.1f}x)")
        if sell_vol: score_sell += 1; factors_sell.append(f"Risk: Volatility tradeable ({vol30:.1f}%)")
        if sell_no_trap: score_sell += 1; factors_sell.append("Microstructure: Clean auction; no Bear Trap")
        if (sw_high - curr) / curr <= 0.08: score_sell += 1; factors_sell.append("Structure: Distribution near resistance")

    # Select Dominant Direction
    is_short = score_sell > score_buy
    score = score_sell if is_short else score_buy
    factors = factors_sell if is_short else factors_buy
    side_action = "SELL" if is_short else "BUY"

    # Setup Score Breakdown per confluence factor
    score_breakdown = [
        {"factor": "Macro: USD Trend (DXY)", "status": "PASS" if (sell_dxy if is_short else feat_dxy) else "FAIL", "weight": 1.0, "earned": 1.0 if (sell_dxy if is_short else feat_dxy) else 0.0},
        {"factor": "Macro: Real Yields (^TNX)", "status": "PASS" if (sell_yield if is_short else feat_yield) else "FAIL", "weight": 1.0, "earned": 1.0 if (sell_yield if is_short else feat_yield) else 0.0},
        {"factor": "Trend: 200 SMA Structure", "status": "PASS" if (sell_ma200 if is_short else feat_ma200) else "FAIL", "weight": 1.0, "earned": 1.0 if (sell_ma200 if is_short else feat_ma200) else 0.0},
        {"factor": "Trend: 50 SMA Stack", "status": "PASS" if (sell_ma50 if is_short else feat_ma50) else "FAIL", "weight": 1.0, "earned": 1.0 if (sell_ma50 if is_short else feat_ma50) else 0.0},
        {"factor": f"Momentum: RSI ({rsi:.1f})", "status": "PASS" if (sell_rsi if is_short else feat_rsi) else "FAIL", "weight": 1.0, "earned": 1.0 if (sell_rsi if is_short else feat_rsi) else 0.0},
        {"factor": "Structure: Golden Pocket (0.618 Fib)", "status": "PASS" if (sell_near_res if is_short else in_golden_pocket) else "FAIL", "weight": 1.0, "earned": 1.0 if (sell_near_res if is_short else in_golden_pocket) else 0.0},
        {"factor": "Microstructure: Anti-Trap", "status": "PASS" if (sell_no_trap if is_short else feat_no_trap) else "FAIL", "weight": 1.0, "earned": 1.0 if (sell_no_trap if is_short else feat_no_trap) else 0.0},
        {"factor": f"Valuation: {'Mayer Multiple' if asset_type == 'BTC' else 'Gold/Silver Ratio'}", "status": "PASS" if ((sell_mayer if is_short else feat_mayer) if asset_type == 'BTC' else (sell_gsr if is_short else feat_gsr)) else "FAIL", "weight": 1.0, "earned": 1.0 if ((sell_mayer if is_short else feat_mayer) if asset_type == 'BTC' else (sell_gsr if is_short else feat_gsr)) else 0.0},
        {"factor": f"Risk: Volatility ({vol30:.1f}%)", "status": "PASS" if (sell_vol if is_short else feat_vol) else "FAIL", "weight": 1.0, "earned": 1.0 if (sell_vol if is_short else feat_vol) else 0.0},
        {"factor": "Structure: Key S/R Location", "status": "PASS" if (sell_near_res if is_short else feat_near_support) else "FAIL", "weight": 1.0, "earned": 1.0 if (sell_near_res if is_short else feat_near_support) else 0.0}
    ]

    active_features = {
        "in_golden_pocket": bool(in_golden_pocket),
        "no_trap": bool(sell_no_trap if is_short else feat_no_trap),
        "macro_dxy_tailwind": bool(sell_dxy if is_short else feat_dxy),
        "macro_yield_tailwind": bool(sell_yield if is_short else feat_yield),
        "trend_ma200": bool(sell_ma200 if is_short else feat_ma200),
        "trend_ma50": bool(sell_ma50 if is_short else feat_ma50),
        "rsi_sweet_spot": bool(sell_rsi if is_short else feat_rsi),
        "mayer_sweet_spot": bool(mayer >= 0.85 and mayer <= 1.50) if asset_type == "BTC" else False,
        "gsr_undervalued": bool(gsr >= 75) if asset_type == "GOLD" else False,
        "volatility_orderly": bool(vol30 < 22 if asset_type == "GOLD" else vol30 < 75),
        "near_swing_support": bool(sell_near_res if is_short else feat_near_support)
    }

    # Adaptive Self-Learned Confluence Score
    if LEARNING_AVAILABLE and learning_engine:
        adaptive_score, breakdown = learning_engine.calculate_score(asset_type, active_features, action=side_action)
    else:
        adaptive_score = float(score)
        breakdown = []

    final_score = max(score, int(round(adaptive_score)))
    if final_score >= 9:
        verdict = f"🟢 A+ {side_action} SETUP (EXECUTE ORDER)"
        action = side_action
    elif final_score >= 8:
        verdict = f"🟢 A {side_action} SETUP (EXECUTE ORDER)"
        action = side_action
    elif final_score >= 7:
        verdict = f"🟢 SCALP {side_action} @ KEY LEVEL (EXECUTE ORDER)"
        action = side_action
    else:
        verdict = "🔴 VETOED (WAIT FOR CONFLUENCE)"
        action = "STAND_ASIDE"

    # News Avoidance Gate: Block new entries around high-impact events
    if action != "STAND_ASIDE" and MARKET_DATA_AVAILABLE and market_data_feed:
        is_news_blk, news_msg, news_ev = market_data_feed.is_news_blocked(asset_type)
        if is_news_blk:
            logger.info(f"News Avoidance Gate triggered for {asset_type}: {news_msg}")
            verdict = f"🔴 VETOED (HIGH-IMPACT NEWS WINDOW: {news_msg})"
            action = "STAND_ASIDE"
            factors.append(f"News Block: {news_msg}")

    # Market Regime Detection & Regime-Based Risk Sizing
    # Use actual VIX and ADX from market data (not hardcoded)
    vix_val = 18.0  # neutral fallback
    adx_val = 25.0  # neutral fallback
    if MARKET_DATA_AVAILABLE and market_data_feed:
        vix_val = market_data_feed.get_live_vix() if hasattr(market_data_feed, 'get_live_vix') else 18.0
    else:
        # Fetch VIX for regime detection when not using market data feed
        try:
            vix = yf.Ticker("^VIX").history(period="5d")
            if not vix.empty:
                vix_val = float(vix["Close"].iloc[-1])
        except Exception:
            vix_val = 18.0
    market_regime = "TREND_EXPANSION"
    if LEARNING_AVAILABLE and learning_engine:
        market_regime = learning_engine.detect_market_regime(adx=adx_val, vix=vix_val)
    regime_risk_pct = risk_engine.get_regime_risk_pct(market_regime) if RISK_ENGINE_AVAILABLE else 0.80
    logger.info(f"Market Regime [{market_regime}] for {asset_type} -> Applied Dynamic Risk: {regime_risk_pct:.2f}%")

    # Limit Order in Zone Parameters
    limit_orders_enabled = os.environ.get("LIMIT_ORDERS_ENABLED", "true").lower() in ("true", "1", "yes")
    offset_pips = float(os.environ.get("LIMIT_ORDER_OFFSET_PIPS", "2"))
    pip_val = (0.10 if asset_type == "GOLD" else 10.0)
    offset_amt = offset_pips * pip_val

    if side_action == "BUY":
        zone_bounds = (fib_650, fib_618)
        limit_entry_price = round(fib_618 - offset_amt, 2)
        price_away_from_zone = curr > (fib_618 * 1.002)
    else:
        res_low = sw_high - 0.382 * (sw_high - sw_low)
        zone_bounds = (res_low, sw_high)
        limit_entry_price = round(sw_high - offset_amt, 2)
        price_away_from_zone = curr < (res_low * 0.998)

    use_limit_order = limit_orders_enabled and price_away_from_zone and action != "STAND_ASIDE"
    execution_entry = limit_entry_price if use_limit_order else curr

    # Symmetrical TP & SL Calculation for Profile Execution
    sl_dist = 3.80 if asset_type == "GOLD" else 350.0
    if RISK_ENGINE_AVAILABLE:
        active_strat_code = risk_engine.get_active_strategy()["code"] if hasattr(risk_engine, "get_active_strategy") else "SCALP"
        strat_calc = risk_engine.calculate_strategy_levels(
            asset_type, curr, atr=vol30, action=action if action != "STAND_ASIDE" else side_action,
            strategy=active_strat_code,
            levels={"in_golden_pocket": in_golden_pocket, "sw_low": sw_low, "sw_high": sw_high}
        )
        stop_loss = strat_calc["stop_loss"]
        tp1 = strat_calc["tp1"]
        tp2 = strat_calc["tp2"]
    else:
        if side_action == "SELL":
            stop_loss = round(curr + sl_dist, 2)
            tp1 = round(curr - (sl_dist * 1.25), 2)
            tp2 = round(curr - (sl_dist * 1.85), 2)
        else:
            stop_loss = round(curr - sl_dist, 2)
            tp1 = round(curr + (sl_dist * 1.25), 2)
            tp2 = round(curr + (sl_dist * 1.85), 2)

    # SL/TP Side Validation Gate: Enforce BUY -> SL < entry < TP and SELL -> TP < entry < SL
    if side_action == "SELL":
        if not (tp1 < curr < stop_loss):
            logger.warning(f"Inverted SL/TP detected for SELL on {asset_type} (TP={tp1}, Entry={curr}, SL={stop_loss}). Auto-correcting.")
            stop_loss = round(curr + sl_dist, 2)
            tp1 = round(curr - (sl_dist * 1.25), 2)
            tp2 = round(curr - (sl_dist * 1.85), 2)
    else:
        if not (stop_loss < curr < tp1):
            logger.warning(f"Inverted SL/TP detected for BUY on {asset_type} (SL={stop_loss}, Entry={curr}, TP={tp1}). Auto-correcting.")
            stop_loss = round(curr - sl_dist, 2)
            tp1 = round(curr + (sl_dist * 1.25), 2)
            tp2 = round(curr + (sl_dist * 1.85), 2)

    # Log signal to self-learning journal if actionable
    trade_id = None
    if action in ("BUY", "SELL", "BUY_HALF", "SELL_HALF") and LEARNING_AVAILABLE and learning_engine:
        trade_id = learning_engine.log_signal(
            asset=asset_type,
            symbol=symbol,
            entry=execution_entry,
            sl=stop_loss,
            tp1=tp1,
            tp2=tp2,
            score=adaptive_score,
            active_features=active_features
        )

    is_sell_action = side_action == "SELL"
    if is_sell_action:
        risk_pct_calc = abs((curr - stop_loss) / curr) * 100 if curr != 0 else 0.0
        reward_pct_calc = abs((tp1 - curr) / curr) * 100 if curr != 0 else 0.0
    else:
        risk_pct_calc = ((curr - stop_loss) / curr) * 100 if curr != 0 else 0.0
        reward_pct_calc = ((tp1 - curr) / curr) * 100 if curr != 0 else 0.0

    return {
        "asset": asset_type,
        "symbol": symbol,
        "htf_bias": htf_bias,
        "price": curr,
        "ma200": ma200,
        "ma50": ma50,
        "rsi": rsi,
        "mayer": mayer,
        "vol30": vol30,
        "golden_pocket": (fib_650, fib_618),
        "in_golden_pocket": in_golden_pocket,
        "trap_state": trap_state,
        "score": score,
        "adaptive_score": adaptive_score,
        "active_features": active_features,
        "breakdown": breakdown,
        "factors": factors,
        "verdict": verdict,
        "action": action,
        "trade_id": trade_id,
        "score_breakdown": score_breakdown,
        "regime": market_regime,
        "regime_risk_pct": regime_risk_pct,
        "order_ticket": {
            "entry": execution_entry,
            "market_price": curr,
            "order_type": "LIMIT" if use_limit_order else "MARKET",
            "limit_price": limit_entry_price,
            "zone": zone_bounds,
            "expiry_minutes": int(os.environ.get("LIMIT_ORDER_EXPIRY_MIN", "35")),
            "stop_loss": stop_loss,
            "tp1": tp1,
            "tp2": tp2,
            "risk_pct": risk_pct_calc,
            "reward_pct": reward_pct_calc,
            "side": side_action,
            "regime": market_regime,
            "applied_risk_pct": regime_risk_pct
        }
    }


def run_pipeline(*args, **kwargs):
    try:
        validate_config(fail_fast=False)
    except Exception as e:
        logger.warning(f"Startup config check: {e}")

    try:
        _execute_pipeline(*args, **kwargs)
    except Exception as exc:
        logger.critical(f"Unhandled exception in autotrader pipeline: {exc}", exc_info=True)
        send_pipeline_crash_alert(exc, context="run_pipeline")
        raise exc


def _execute_pipeline(*args, **kwargs):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n" + "═" * 78)
    print(f"  ⚡ HARD-ASSET AUTOTRADER PIPELINE (METHOD 1) | {timestamp}")
    if LEARNING_AVAILABLE:
        print(f"  🧠 Self-Learning Adaptive Engine: ACTIVE (Memory: learning_memory.json)")
    print("═" * 78)

    # Global Macro Inputs (Multi-Source Resilient Feed)
    if MARKET_DATA_AVAILABLE and market_data_feed:
        macro = market_data_feed.get_macro_snapshot()
        dxy_val = macro["dxy"]
        dxy_chg = macro["dxy_chg"]
        tnx_val = macro["tnx"]
        tnx_chg = macro["tnx_chg"]
        gsr = macro["gsr"]
        fg_val = macro["fg_val"]
        fg_label = macro["fg_label"]
    else:
        dxy = yf.Ticker("DX-Y.NYB").history(period="5d")
        tnx = yf.Ticker("^TNX").history(period="5d")
        silver = yf.Ticker("SI=F").history(period="5d")
        gold_5d = yf.Ticker("GC=F").history(period="5d")

        dxy_val = dxy["Close"].iloc[-1] if not dxy.empty else 100.0
        prev_dxy_close = dxy["Close"].iloc[-2] if len(dxy) >= 2 else 0.0
        dxy_chg = (((dxy_val / prev_dxy_close) - 1) * 100) if (len(dxy) >= 2 and prev_dxy_close != 0) else 0.0

        tnx_val = tnx["Close"].iloc[-1] if not tnx.empty else 4.0
        prev_tnx_close = tnx["Close"].iloc[-2] if len(tnx) >= 2 else 0.0
        tnx_chg = (((tnx_val / prev_tnx_close) - 1) * 100) if (len(tnx) >= 2 and prev_tnx_close != 0) else 0.0

        gsr = (gold_5d["Close"].iloc[-1] / silver["Close"].iloc[-1]) if (not gold_5d.empty and not silver.empty and float(silver["Close"].iloc[-1]) != 0) else 80.0
        fg_val, fg_label = fetch_fear_greed()

    print(f"  MACRO RADAR: DXY: {dxy_val:.2f} ({dxy_chg:+.2f}%) | 10Y Yield: {tnx_val:.2f}% ({tnx_chg:+.2f}%) | GSR: {gsr:.1f}x | F&G: {fg_val} ({fg_label})")
    print("─" * 78)

    assets = [("BTC-USD", "BTC"), ("GC=F", "GOLD")]

    for sym, asset_type in assets:
        res = analyze_asset_pipeline(sym, asset_type, dxy_chg, tnx_chg, gsr, fg_val)
        if not res:
            continue

        icon = "₿" if asset_type == "BTC" else "🥇"
        status_color = "🟢" if "EXECUTE" in res['verdict'] else "🟡" if "HALF" in res['verdict'] else "🔴"

        gp_low, gp_high = res['golden_pocket']
        loc_str = f"✅ INSIDE Golden Pocket (${gp_low:,.0f} - ${gp_high:,.0f})" if res['in_golden_pocket'] else "Outside Golden Pocket"
        htf_str = res.get('htf_bias', {}).get('summary', 'Neutral')
        print(f"\n{icon} {asset_type} ({sym}) ──► Price: ${res['price']:,.2f}")
        print(f"   • Higher TF Bias      : {htf_str}")
        print(f"   • Structural Location : {loc_str}")
        print(f"   • Microstructure Trap : {res['trap_state']}")
        print(f"   • Trend & Momentum    : 200 SMA: ${res['ma200']:,.0f} | RSI: {res['rsi']:.1f}" + (f" | Mayer: {res['mayer']:.2f}x" if asset_type == 'BTC' else ""))
        print(f"   • Confluence Score    : {res['score']}/10 (Base) | {res['adaptive_score']:.1f}/10 (Learned) ──► {status_color} {res['verdict']}")

        if res['action'] in ("BUY", "BUY_HALF", "SELL", "SELL_HALF"):
            ot = res['order_ticket']
            rr = (ot['reward_pct'] / ot['risk_pct']) if ot['risk_pct'] > 0 else 1.0
            side_label = ot.get('side', res['action'])
            otype = ot.get('order_type', 'MARKET')
            reg_name = ot.get('regime', 'TREND_EXPANSION')
            reg_risk = ot.get('applied_risk_pct', 0.8)

            # Display Setup Score Breakdown Box
            print("   ┌──────────────────────────────────────────────────────────────┐")
            print(f"   │  📊 CONFLUENCE FACTOR BREAKDOWN ({side_label})               │")
            for item in res.get('score_breakdown', []):
                icon_pass = "✅" if item['status'] == "PASS" else "❌"
                f_name = item['factor'][:32]
                print(f"   │  {icon_pass} {f_name:<32} : {item['status']:<4} (+{item['earned']:.1f}) │")
            print(f"   │  • Base: {res['score']}/10  |  Adaptive: {res['adaptive_score']:.1f}/10  |  Regime: {reg_name} │")
            print("   └──────────────────────────────────────────────────────────────┘")

            print(f"""   ┌──────────────────────────────────────────────────────────────┐
   │  📋 ACTIONABLE ORDER TICKET ({otype} {side_label})                │
   │  • Entry Zone : ${ot['entry']:>10,.2f}  ({otype})                       │
   │  • Stop-Loss  : ${ot['stop_loss']:>10,.2f}  (Risk: -{ot['risk_pct']:.2f}%)               │
   │  • Target 1   : ${ot['tp1']:>10,.2f}  (Reward: +{ot['reward_pct']:.2f}%)            │
   │  • Target 2   : ${ot['tp2']:>10,.2f}                                │
   │  • Risk/Reward: 1:{rr:.2f}  |  Dynamic Sizing: {reg_risk:.2f}%              │
   └──────────────────────────────────────────────────────────────┘""")
        else:
            print("   ⛔ ACTION: Stand aside. Confluence does not meet institutional execution threshold.")

    print("\n" + "═" * 78 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deterministic Hard-Asset Pipeline Engine")
    parser.add_argument("--loop", action="store_true", help="Run continuously on an automated loop")
    parser.add_argument("--interval", type=int, default=3600, help="Loop interval in seconds (default: 3600 / 1hr)")
    args = parser.parse_args()

    if args.loop:
        print(f"🚀 Starting Autotrader Pipeline Loop (Interval: {args.interval}s)... Press Ctrl+C to stop.")
        try:
            while True:
                run_pipeline()
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n🛑 Pipeline monitor stopped.")
    else:
        run_pipeline()
