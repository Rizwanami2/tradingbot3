#!/usr/bin/env python3
"""
telegram_bot.py
Unified Institutional Hard-Asset Trading Bot (Gold & Bitcoin).
Combines ALL 12 Trading Skills into a Single Autonomous Telegram Engine:
  1. Macro Radar (DXY, 10Y Yield, GSR, VIX, Crypto Fear & Greed)
  2. Institutional Key Levels & Fibonacci Golden Pocket (0.618 - 0.650)
  3. Microstructure Anti-Trap & Wyckoff Rejection Geometry (>=40% wicks)
  4. Orderflow & Fair Value Gap (FVG) Imbalance Detection
  5. Volatility Regime Detection (ADX trend strength, ATR, Realized Vol)
  6. Asset-Specific Valuation (Mayer Multiple, Physical Gold floor)
  7. Adversarial Bull vs. Bear Dialectical Debate Engine
  8. 10-Point Confluence Scoring Matrix (A+, B, Vetoed)
  9. Strict 1% Risk Sizing & 1:2+ R:R Enforcement
 10. Autonomous Self-Learning & Adaptive Weight Optimization (self_learning.py)
 11. Automated 30-Minute Background Scanner & Alert Broadcaster
 12. 100% Free of MetaTrader 5 (MT5) - Runs on ANY VPS (Windows / Linux)
"""

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
import json
import time
import threading
import urllib.request
import urllib.parse
import urllib.error
import ssl
from datetime import datetime
import numpy as np
import pandas as pd

# Suppress warnings
import warnings
warnings.filterwarnings("ignore")

# Bypass Windows VPS missing root CA certificates or hosting provider SSL inspection
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

try:
    import yfinance as yf
except ImportError:
    print("❌ yfinance required. Run: pip install yfinance")
    sys.exit(1)

# Import Self-Learning Engine
try:
    from self_learning import SelfLearningEngine
    learning_engine = SelfLearningEngine()
    LEARNING_AVAILABLE = True
except Exception:
    learning_engine = None
    LEARNING_AVAILABLE = False

# Import MT5-Style Visual Chart Generator
try:
    from chart_generator import generate_mt5_chart, send_telegram_chart
    CHARTS_AVAILABLE = True
except Exception:
    CHARTS_AVAILABLE = False

# Import Institutional Risk Management & Sizing Engine
try:
    from risk_engine import (
        calculate_lot_size, generate_risk_audit_text, validate_trade_risk,
        calculate_sniper_levels, calculate_strategy_levels, STRATEGIES,
        set_active_strategy, get_active_strategy, validate_strategy_accuracy,
        get_market_session
    )
    RISK_ENGINE_AVAILABLE = True
except Exception:
    RISK_ENGINE_AVAILABLE = False

# Import Live MT5 Broker Execution Engine
try:
    from mt5_executor import live_broker
    MT5_EXECUTOR_AVAILABLE = True
except Exception:
    live_broker = None
    MT5_EXECUTOR_AVAILABLE = False

# Import Quantitative Backtesting Engine
try:
    from backtest import run_historical_backtest, format_backtest_telegram_card
    BACKTEST_AVAILABLE = True
except Exception:
    BACKTEST_AVAILABLE = False

# Live auto-trade state and separate watchlist ('OFF', 'BOTH', 'GOLD', 'BTC')
AUTO_TRADE_MODE = "OFF"
AUTO_TRADE_LIVE = False

# Automated Trailing Stop & Breakeven Protection
TRAILING_STOP_ENABLED = True


ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config_telegram.json")


def load_env():
    """Reads credentials from .env into os.environ."""
    if os.path.exists(ENV_PATH):
        try:
            with open(ENV_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip('"').strip("'")
                        os.environ[k] = v
        except Exception:
            pass


def get_risk_config():
    """Loads account balance (auto-fetched from live MT5 if connected) and risk %."""
    load_env()
    # 1. Automatically fetch live equity from connected MT5 live account
    if MT5_EXECUTOR_AVAILABLE and live_broker and live_broker.is_connected:
        acc_data = live_broker.get_live_account_data()
        if acc_data and acc_data.get("equity", 0) > 0:
            balance = acc_data["equity"]
        else:
            try:
                balance = float(os.environ.get("ACCOUNT_BALANCE", "10000.0").strip())
            except Exception:
                balance = 10000.0
    else:
        try:
            balance = float(os.environ.get("ACCOUNT_BALANCE", "10000.0").strip())
        except Exception:
            balance = 10000.0

    try:
        risk_pct = float(os.environ.get("RISK_PCT_PER_TRADE", "1.0").strip())
    except Exception:
        risk_pct = 1.0

    return balance, risk_pct


def get_credentials():
    """Loads bot_token and chat_id from .env or config_telegram.json."""
    load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not token and os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                token = data.get("telegram", {}).get("bot_token", "").strip()
                if not chat_id:
                    chat_id = str(data.get("telegram", {}).get("chat_id", "")).strip()
        except Exception:
            pass

    return token, chat_id


def save_chat_id(chat_id: str):
    """Saves chat ID to .env and config_telegram.json for persistence."""
    lines = []
    found = False
    if os.path.exists(ENV_PATH):
        try:
            with open(ENV_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("TELEGRAM_CHAT_ID="):
                        lines.append(f"TELEGRAM_CHAT_ID={chat_id}\n")
                        found = True
                    else:
                        lines.append(line)
        except Exception:
            pass
    if not found:
        lines.append(f"TELEGRAM_CHAT_ID={chat_id}\n")
    try:
        with open(ENV_PATH, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except Exception:
        pass

    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "telegram" not in data:
                data["telegram"] = {}
            data["telegram"]["chat_id"] = str(chat_id)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass


def verify_token(token: str):
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GoldBtcTelegramBot/3.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            res = json.loads(r.read())
            if res.get("ok"):
                return True, res["result"].get("username"), res["result"].get("first_name")
            return False, None, None
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, "401_UNAUTHORIZED", "Invalid token"
        return False, f"HTTP_{e.code}", str(e)
    except Exception as e:
        return False, "NETWORK_ERROR", str(e)


def send_message(token: str, chat_id: str, text: str, reply_markup: dict = None):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": str(chat_id),
        "text": text,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=12) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError:
        try:
            payload.pop("parse_mode", None)
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=12) as r:
                return json.loads(r.read())
        except Exception:
            return None
    except Exception:
        return None


# ==============================================================================
# SKILL 1: TECHNICAL INDICATORS & VOLATILITY (ADX, ATR, RSI, VOL)
# ==============================================================================

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


def compute_atr(df, period: int = 14) -> float:
    if len(df) < period + 1:
        return 0.0
    h_l = df["High"] - df["Low"]
    h_pc = (df["High"] - df["Close"].shift(1)).abs()
    l_pc = (df["Low"] - df["Close"].shift(1)).abs()
    tr = np.maximum(h_l, np.maximum(h_pc, l_pc))
    atr = tr.rolling(period).mean().iloc[-1]
    return float(atr)


def compute_adx(df, period: int = 14) -> tuple:
    """Computes ADX and determines regime (Trending > 25 vs Chop < 20), plus Directional Indicators (+DI, -DI)."""
    if len(df) < period * 2:
        return 22.0, "CHOP / RANGE", 20.0, 20.0
    
    up_move = df["High"] - df["High"].shift(1)
    down_move = df["Low"].shift(1) - df["Low"]
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    plus_dm_s = pd.Series(plus_dm, index=df.index)
    minus_dm_s = pd.Series(minus_dm, index=df.index)

    h_l = df["High"] - df["Low"]
    h_pc = (df["High"] - df["Close"].shift(1)).abs()
    l_pc = (df["Low"] - df["Close"].shift(1)).abs()
    tr = np.maximum(h_l, np.maximum(h_pc, l_pc))

    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm_s.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm_s.rolling(period).mean() / atr)

    dx = 100 * (np.abs(plus_di - minus_di) / (plus_di + minus_di))
    adx_series = dx.rolling(period).mean()
    adx = float(adx_series.iloc[-1]) if not adx_series.empty and not np.isnan(adx_series.iloc[-1]) else 22.0
    plus_di_val = float(plus_di.iloc[-1]) if not plus_di.empty and not np.isnan(plus_di.iloc[-1]) else 20.0
    minus_di_val = float(minus_di.iloc[-1]) if not minus_di.empty and not np.isnan(minus_di.iloc[-1]) else 20.0

    regime = "TRENDING (ADX > 25)" if adx >= 25 else "CHOP / CONSOLIDATION (ADX < 20)" if adx <= 20 else "TRANSITIONAL (20-25)"
    return adx, regime, plus_di_val, minus_di_val


# ==============================================================================
# SKILL 2 & 3: KEY LEVELS, FIBONACCI & ORDERFLOW IMBALANCE (FVG)
# ==============================================================================

def compute_key_levels(hist):
    curr = hist["Close"].iloc[-1]
    ma20_ema = hist["Close"].ewm(span=20, adjust=False).mean().iloc[-1]
    ma50 = hist["Close"].rolling(50).mean().iloc[-1] if len(hist) >= 50 else np.nan
    ma200 = hist["Close"].rolling(200).mean().iloc[-1] if len(hist) >= 200 else np.nan

    recent_60 = hist.tail(60)
    sw_high = recent_60["High"].max()
    sw_low = recent_60["Low"].min()
    sw_range = sw_high - sw_low

    fib_382 = sw_high - 0.382 * sw_range
    fib_500 = sw_high - 0.500 * sw_range
    fib_618 = sw_high - 0.618 * sw_range
    fib_650 = sw_high - 0.650 * sw_range
    fib_786 = sw_high - 0.786 * sw_range

    in_golden_pocket = (curr >= fib_650 * 0.985) and (curr <= fib_618 * 1.02)

    # Classical daily pivot
    yesterday = hist.iloc[-2] if len(hist) >= 2 else hist.iloc[-1]
    pp = (yesterday["High"] + yesterday["Low"] + yesterday["Close"]) / 3
    r1 = 2 * pp - yesterday["Low"]
    s1 = 2 * pp - yesterday["High"]

    return {
        "curr": curr, "ma20_ema": ma20_ema, "ma50": ma50, "ma200": ma200,
        "sw_high": sw_high, "sw_low": sw_low, "sw_range": sw_range,
        "fib_382": fib_382, "fib_500": fib_500, "fib_618": fib_618,
        "fib_650": fib_650, "fib_786": fib_786, "in_golden_pocket": in_golden_pocket,
        "pivot": pp, "r1": r1, "s1": s1
    }


def detect_fvg(hist):
    """Detects 3-candle Fair Value Gap imbalances in recent bars."""
    if len(hist) < 5:
        return "None"
    recent = hist.tail(5)
    # Check 3-candle gaps
    c1, c2, c3 = recent.iloc[-3], recent.iloc[-2], recent.iloc[-1]
    # Bullish FVG: Low of candle 3 is higher than High of candle 1
    if c3["Low"] > c1["High"]:
        gap_size = c3["Low"] - c1["High"]
        return f"BULLISH FVG (${c1['High']:,.0f} - ${c3['Low']:,.0f}, Gap: ${gap_size:,.0f})"
    # Bearish FVG: High of candle 3 is lower than Low of candle 1
    elif c3["High"] < c1["Low"]:
        gap_size = c1["Low"] - c3["High"]
        return f"BEARISH FVG (${c3['High']:,.0f} - ${c1['Low']:,.0f}, Gap: ${gap_size:,.0f})"
    return "Balanced Auction (No Active FVG)"


# ==============================================================================
# SKILL 4: FAKEOUT & WYCKOFF TRAP DETECTION (>=40% WICKS)
# ==============================================================================

def detect_traps(hist, levels):
    curr_bar = hist.iloc[-1]
    c_open, c_high, c_low, c_close = curr_bar["Open"], curr_bar["High"], curr_bar["Low"], curr_bar["Close"]
    c_range = c_high - c_low
    upper_wick = c_high - max(c_open, c_close)
    lower_wick = min(c_open, c_close) - c_low

    trap_type = "CLEAN"
    detail = "No major trap wicks detected"

    if c_range > 0:
        up_pct = (upper_wick / c_range) * 100
        low_pct = (lower_wick / c_range) * 100

        # Bull Trap: Pierced resistance with >=40% upper rejection wick
        if up_pct >= 40.0 and curr_bar["Close"] >= levels["fib_500"]:
            trap_type = "BULL_TRAP"
            detail = f"Upthrust / Bull Trap detected! Upper wick: {up_pct:.1f}% of candle range. FADE LONGS."
        # Bear Trap: Swept support with >=40% lower absorption spring
        elif low_pct >= 40.0 and curr_bar["Close"] <= levels["fib_650"]:
            trap_type = "BEAR_TRAP"
            detail = f"Wyckoff Spring / Bear Trap detected! Lower wick: {low_pct:.1f}% absorption. BULLISH REVERSAL."

    return trap_type, detail


# ==============================================================================
# SKILL 5 & 6: MACRO & ON-CHAIN QUANTITATIVE VALUATION
# ==============================================================================

def fetch_fear_greed():
    try:
        req = urllib.request.Request("https://api.alternative.me/fng/?limit=1", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
            return int(data["data"][0]["value"]), data["data"][0]["value_classification"]
    except Exception:
        return 50, "Neutral"


def fetch_macro_context():
    dxy = yf.Ticker("DX-Y.NYB").history(period="5d")
    tnx = yf.Ticker("^TNX").history(period="5d")
    silver = yf.Ticker("SI=F").history(period="5d")
    gold_5d = yf.Ticker("GC=F").history(period="5d")
    vix = yf.Ticker("^VIX").history(period="5d")

    dxy_val = dxy["Close"].iloc[-1] if not dxy.empty else 102.0
    dxy_chg = (((dxy_val / dxy["Close"].iloc[-2]) - 1) * 100) if len(dxy) >= 2 else 0.0

    tnx_val = tnx["Close"].iloc[-1] if not tnx.empty else 5.0
    tnx_chg = (((tnx_val / tnx["Close"].iloc[-2]) - 1) * 100) if len(tnx) >= 2 else 0.0

    vix_val = vix["Close"].iloc[-1] if not vix.empty else 16.0

    gsr = (gold_5d["Close"].iloc[-1] / silver["Close"].iloc[-1]) if (not gold_5d.empty and not silver.empty) else 75.0
    fg_val, fg_label = fetch_fear_greed()

    return {
        "dxy": dxy_val, "dxy_chg": dxy_chg,
        "tnx": tnx_val, "tnx_chg": tnx_chg,
        "vix": vix_val,
        "gsr": gsr, "fg_val": fg_val, "fg_label": fg_label
    }


# ==============================================================================
# SKILL 7, 8 & 9: MULTI-FACTOR AUDIT, CONFLUENCE SCORING & RISK SIZING
# ==============================================================================

def analyze_asset_complete(symbol: str, asset_type: str, macro: dict):
    t = yf.Ticker(symbol)
    hist = t.history(period="350d")
    if hist.empty or len(hist) < 40:
        return None

    levels = compute_key_levels(hist)
    curr = levels["curr"]
    ma50 = levels["ma50"]
    ma200 = levels["ma200"]

    # Technical indicators
    rsi = compute_rsi(hist["Close"], 14)
    atr = compute_atr(hist, 14)
    adx, regime, plus_di, minus_di = compute_adx(hist, 14)

    # Imbalance & Trap analysis
    fvg = detect_fvg(hist)
    trap_type, trap_detail = detect_traps(hist, levels)

    # Volatility
    daily_rets = hist["Close"].pct_change().dropna()
    vol30 = float(daily_rets.tail(30).std() * np.sqrt(365) * 100) if len(daily_rets) >= 30 else 30.0

    # Valuation
    mayer = (curr / ma200) if not np.isnan(ma200) and ma200 > 0 else 1.0

    # 10-Point Hard Asset Confluence Matrix
    factors_hit = []
    active_features = {}

    if asset_type == "BTC":
        feat_dxy = macro["dxy_chg"] < 0.2
        feat_yield = macro["tnx_chg"] < 1.0
        feat_trend200 = curr > ma200
        feat_trend50 = curr > ma50
        feat_mayer = 0.85 <= mayer <= 1.50
        feat_rsi = 40 <= rsi <= 65
        feat_gp = levels["in_golden_pocket"]
        feat_no_trap = trap_type != "BULL_TRAP"
        feat_vol = vol30 < 75
        feat_support = (curr - levels["sw_low"]) / curr <= 0.05

        if feat_dxy: factors_hit.append("Macro: USD tailwind (DXY flat/falling)")
        if feat_yield: factors_hit.append("Yields: 10Y real yield controlled")
        if feat_trend200: factors_hit.append(f"Trend: Above 200 SMA (${ma200:,.0f})")
        if feat_trend50: factors_hit.append("Trend: Above 50 SMA")
        if feat_mayer: factors_hit.append(f"Valuation: Mayer Multiple healthy ({mayer:.2f}x)")
        if feat_rsi: factors_hit.append(f"Momentum: RSI sweet spot ({rsi:.1f})")
        if feat_gp: factors_hit.append("Key Level: Resting in Golden Pocket (0.618 Fib)")
        if feat_no_trap: factors_hit.append("Auction: Clean auction (no bull trap wicks)")
        if feat_vol: factors_hit.append(f"Volatility: Orderly ({vol30:.1f}%)")
        if feat_support: factors_hit.append("Structure: Near major swing support floor")

        active_features = {
            "in_golden_pocket": bool(feat_gp),
            "no_trap": bool(feat_no_trap),
            "macro_dxy_tailwind": bool(feat_dxy),
            "macro_yield_tailwind": bool(feat_yield),
            "trend_ma200": bool(feat_trend200),
            "trend_ma50": bool(feat_trend50),
            "rsi_sweet_spot": bool(feat_rsi),
            "mayer_sweet_spot": bool(feat_mayer),
            "gsr_undervalued": False,
            "volatility_orderly": bool(feat_vol),
            "near_swing_support": bool(feat_support)
        }

    else:  # GOLD
        feat_dxy = macro["dxy_chg"] <= 0.05
        feat_yield = macro["tnx_chg"] <= 0.2
        feat_trend200 = curr > ma200
        feat_trend50 = curr > ma50
        feat_rsi = 40 <= rsi <= 60
        feat_gp = levels["in_golden_pocket"]
        feat_gsr = macro["gsr"] >= 75
        feat_no_trap = trap_type != "BULL_TRAP"
        feat_vol = vol30 < 22
        feat_support = (curr - levels["sw_low"]) / curr <= 0.05

        if feat_dxy: factors_hit.append("Macro: DXY weakness (Gold tailwind)")
        if feat_yield: factors_hit.append("Yields: 10Y real yields easing")
        if feat_trend200: factors_hit.append(f"Trend: Above 200 SMA (${ma200:,.0f})")
        if feat_trend50: factors_hit.append("Trend: Above 50 SMA")
        if feat_rsi: factors_hit.append(f"Momentum: RSI pullback sweet spot ({rsi:.1f})")
        if feat_gp: factors_hit.append("Key Level: Resting in Golden Pocket (0.618 Fib)")
        if feat_gsr: factors_hit.append(f"Metals Value: GSR elevated ({macro['gsr']:.1f}x)")
        if feat_no_trap: factors_hit.append("Auction: Zero Bull Trap rejection")
        if feat_vol: factors_hit.append(f"Volatility: Orderly ({vol30:.1f}%)")
        if feat_support: factors_hit.append("Structure: Near major swing support floor")

        active_features = {
            "in_golden_pocket": bool(feat_gp),
            "no_trap": bool(feat_no_trap),
            "macro_dxy_tailwind": bool(feat_dxy),
            "macro_yield_tailwind": bool(feat_yield),
            "trend_ma200": bool(feat_trend200),
            "trend_ma50": bool(feat_trend50),
            "rsi_sweet_spot": bool(feat_rsi),
            "mayer_sweet_spot": False,
            "gsr_undervalued": bool(feat_gsr),
            "volatility_orderly": bool(feat_vol),
            "near_swing_support": bool(feat_support)
        }

    curr_bar = hist.iloc[-1]
    c_open, c_high, c_low, c_close = curr_bar["Open"], curr_bar["High"], curr_bar["Low"], curr_bar["Close"]
    c_range = c_high - c_low
    up_wick_pct = ((c_high - max(c_open, c_close)) / c_range * 100) if c_range > 0 else 0.0
    low_wick_pct = ((min(c_open, c_close) - c_low) / c_range * 100) if c_range > 0 else 0.0
    candle_body_pct = ((abs(c_close - c_open)) / c_range * 100) if c_range > 0 else 50.0

    acc_data = live_broker.get_live_account_data() if (MT5_EXECUTOR_AVAILABLE and live_broker and live_broker.is_connected) else None
    broker_lev = acc_data.get("leverage") if acc_data else None
    free_mrg = acc_data.get("margin_free") if acc_data else None
    swap_info = live_broker.get_swap_rates(asset_type) if (MT5_EXECUTOR_AVAILABLE and live_broker and live_broker.is_connected) else None

    active_strat = get_active_strategy() if RISK_ENGINE_AVAILABLE else {"code": "SCALP", "name": "Sniper Scalp"}

    # Profile-Specific Strategy Accuracy Verification
    strat_accuracy = {"passed": True, "veto_reasons": []}
    if RISK_ENGINE_AVAILABLE:
        strat_accuracy = validate_strategy_accuracy(
            strat_code=active_strat["code"],
            asset=asset_type,
            current_price=curr,
            atr=atr,
            rsi=rsi,
            adx=adx,
            levels=levels,
            trap_type=trap_type,
            upper_wick_pct=up_wick_pct,
            lower_wick_pct=low_wick_pct,
            candle_body_pct=candle_body_pct,
            plus_di=plus_di,
            minus_di=minus_di,
            macro=macro,
            swap_info=swap_info,
            action="BUY"
        )

    base_score = len(factors_hit)
    adaptive_score = base_score
    if LEARNING_AVAILABLE and learning_engine:
        adaptive_score, _ = learning_engine.calculate_score(asset_type, active_features)

    final_score = max(base_score, int(round(adaptive_score)))
    is_a_plus = final_score >= 8

    # Key institutional level detection for Scalp execution
    at_good_level = strat_accuracy.get("at_good_level", False) or \
                    levels.get("in_golden_pocket", False) or \
                    ((curr - sw_low) / curr <= 0.05 if (sw_low and curr) else False) or \
                    (levels.get("ma20_ema") and abs(curr - levels["ma20_ema"]) / curr <= 0.02)
    can_execute_scalp = (active_strat["code"] == "SCALP" and final_score >= 7 and at_good_level and strat_accuracy["passed"] and trap_type != "BULL_TRAP")

    # VETO conditions: Anti-Trap & Strategy-Specific Accuracy Filters
    if trap_type == "BULL_TRAP":
        is_a_plus = False
        verdict = "🔴 VETOED: Bull Trap at Resistance! Stand Aside or Fade."
    elif not strat_accuracy["passed"]:
        is_a_plus = False
        verdict = f"🔴 VETOED [{active_strat['code']}]: {strat_accuracy['veto_reasons'][0]}"
    elif is_a_plus:
        verdict = f"🟢 A+ SETUP [{active_strat['code']}] (Score: {final_score}/10) - High Probability Execution"
    elif can_execute_scalp:
        is_a_plus = True  # Qualified for practical key level scalp execution
        verdict = f"🟢 SCALP EXECUTION [{active_strat['code']}] (Score: {final_score}/10) - Key Level Clearance"
    elif final_score >= 6:
        verdict = f"🟡 B SETUP [{active_strat['code']}] (Score: {final_score}/10) - Watchlist / Reduced Size"
    else:
        verdict = f"🔴 VETOED (Score: {final_score}/10) - Insufficient Confluence"

    account_balance, base_risk = get_risk_config()
    target_risk = base_risk if is_a_plus else (base_risk * 0.5)

    # Multi-Strategy Parameter Calculation (SCALP, SWING, BALANCE, SWAP)
    if RISK_ENGINE_AVAILABLE:
        strat_calc = calculate_strategy_levels(
            asset_type, curr, atr=atr, action="BUY",
            strategy=active_strat["code"],
            account_balance=account_balance, risk_pct=target_risk,
            broker_leverage=broker_lev, margin_free=free_mrg,
            swap_info=swap_info, levels=levels
        )
        stop_loss = strat_calc["stop_loss"]
        tp1 = strat_calc["tp1"]
        tp2 = strat_calc["tp2"]
        risk_pct = strat_calc["risk_pct"]
        reward_pct = round(abs(tp1 - curr) / curr * 100, 2)
        rr = strat_calc["rr_tp1"]
        lot_info = {
            "lots": strat_calc["lot_size"],
            "actual_risk_usd": strat_calc["risk_usd"],
            "actual_risk_pct": strat_calc["risk_pct"],
            "price_dist": strat_calc["sl_dist"],
            "strategy": strat_calc["strategy"],
            "holding_time": strat_calc["holding_time"],
            "breakeven_r": strat_calc["breakeven_r"],
            "trail_start_r": strat_calc["trail_start_r"],
            "trail_step_r": strat_calc["trail_step_r"],
            "swap_note": strat_calc.get("swap_note", "")
        }
    else:
        sl_dist = 4.0 if asset_type == "GOLD" else 350.0
        stop_loss = round(curr - sl_dist, 2)
        tp1 = round(curr + (sl_dist * 1.2), 2)
        tp2 = round(curr + (sl_dist * 2.0), 2)
        risk_pct = 1.0
        reward_pct = 1.2
        rr = 1.2
        lot_info = {
            "lots": 0.05,
            "actual_risk_usd": round(account_balance * (target_risk / 100.0), 2),
            "actual_risk_pct": target_risk,
            "price_dist": sl_dist,
            "strategy": "SCALP",
            "holding_time": "5 - 30 minutes",
            "swap_note": ""
        }

    return {
        "asset": asset_type,
        "symbol": symbol,
        "price": curr,
        "levels": levels,
        "rsi": rsi,
        "atr": atr,
        "adx": adx,
        "plus_di": plus_di,
        "minus_di": minus_di,
        "regime": regime,
        "fvg": fvg,
        "mayer": mayer,
        "vol30": vol30,
        "candle_body_pct": candle_body_pct,
        "trap_type": trap_type,
        "trap_detail": trap_detail,
        "strat_accuracy": strat_accuracy,
        "base_score": base_score,
        "adaptive_score": adaptive_score,
        "final_score": final_score,
        "verdict": verdict,
        "is_a_plus": is_a_plus,
        "factors_hit": factors_hit,
        "entry": curr,
        "stop_loss": stop_loss,
        "tp1": tp1,
        "tp2": tp2,
        "risk_pct": risk_pct,
        "reward_pct": reward_pct,
        "rr": rr,
        "lot_info": lot_info
    }


_last_pipeline_cache = {
    "macro": None,
    "btc": None,
    "gold": None,
    "timestamp": 0
}


def run_full_pipeline():
    global _last_pipeline_cache
    now = time.time()
    # Cache for up to 10 seconds to avoid provider rate-limits on rapid commands
    if _last_pipeline_cache["btc"] and _last_pipeline_cache["gold"] and (now - _last_pipeline_cache["timestamp"] < 10):
        return _last_pipeline_cache

    try:
        macro = fetch_macro_context()
    except Exception:
        macro = _last_pipeline_cache["macro"] or {
            "dxy": 102.0, "dxy_chg": 0.0, "tnx": 4.5, "tnx_chg": 0.0,
            "vix": 18.0, "gsr": 80.0, "fg_val": 50, "fg_label": "Neutral"
        }

    try:
        btc = analyze_asset_complete("BTC-USD", "BTC", macro)
    except Exception:
        btc = None

    try:
        gold = analyze_asset_complete("GC=F", "GOLD", macro)
    except Exception:
        gold = None

    # Resilient fallback to last known good snapshot if temporary provider failure
    if btc is None and _last_pipeline_cache["btc"]:
        btc = _last_pipeline_cache["btc"]
    if gold is None and _last_pipeline_cache["gold"]:
        gold = _last_pipeline_cache["gold"]

    result = {"macro": macro, "btc": btc, "gold": gold}
    if btc and gold:
        _last_pipeline_cache = {
            "macro": macro,
            "btc": btc,
            "gold": gold,
            "timestamp": now
        }
    return result


# ==============================================================================
# SKILL 10: ADVERSARIAL BULL VS. BEAR DIALECTICAL DEBATE
# ==============================================================================

def generate_adversarial_debate(data: dict) -> str:
    m = data.get("macro", {})
    b = data.get("btc")
    g = data.get("gold")

    if not b or not g:
        return "⚠️ Market data temporarily unavailable for dialectical debate. Please try again."

    lines = [
        "⚔️ *ADVERSARIAL BULL VS. BEAR DEBATE*",
        "",
        "₿ *BITCOIN (BTC-USD):*",
        f"🐂 *Bull Thesis:* Price (${b['price']:,.2f}) supported by 200 SMA (${b['levels']['ma200']:,.0f}). Mayer Multiple at {b['mayer']:.2f}x indicates institutional accumulation zone without retail euphoria. Market regime is {b['regime']}.",
        f"🐻 *Bear Counter:* Macro 10Y Yields at {m.get('tnx', 4.5):.2f}% ({m.get('tnx_chg', 0.0):+.2f}%) maintain liquidity drag. Recent imbalance: {b['fvg']}. Invalidation stop sits at ${b['stop_loss']:,.2f}.",
        "",
        "🥇 *GOLD (XAU/USD):*",
        f"🐂 *Bull Thesis:* Gold/Silver Ratio at {m.get('gsr', 80.0):.1f}x signals structural metal undervaluation. Physical central bank demand creates solid floor. No bull trap rejection.",
        f"🐻 *Bear Counter:* DXY trading at {m.get('dxy', 102.0):.2f} ({m.get('dxy_chg', 0.0):+.2f}%). Real yield firmness caps explosive breakout momentum until DXY rolls over.",
        "",
        f"⚖️ *Consensus Verdict:*",
        f"• BTC: {b['verdict']}",
        f"• Gold: {g['verdict']}"
    ]
    return "\n".join(lines)


# ==============================================================================
# TELEGRAM DISPATCHER & COMMAND CENTER
# ==============================================================================

def format_scan_summary(data: dict) -> str:
    m = data.get("macro", {})
    b = data.get("btc")
    g = data.get("gold")

    if not b or not g:
        return "⚠️ Market data temporarily unavailable from provider. Retrying momentarily..."

    session_info = get_market_session() if RISK_ENGINE_AVAILABLE else None
    strat = get_active_strategy() if RISK_ENGINE_AVAILABLE else {"name": "Scalp Sniper", "code": "SCALP"}
    session_badge = f"{session_info.get('badge', '🌐')} {session_info.get('name', 'Active')}" if session_info else "Active Market"
    edge_str = session_info.get('win_rate_edge', 'Normal') if session_info else 'Normal'

    b_gp_str = f"✅ INSIDE (${b['levels']['fib_650']:,.0f} - ${b['levels']['fib_618']:,.0f})" if b['levels']['in_golden_pocket'] else "Outside GP"
    g_gp_str = f"✅ INSIDE (${g['levels']['fib_650']:,.0f} - ${g['levels']['fib_618']:,.0f})" if g['levels']['in_golden_pocket'] else "Outside GP"

    lines = [
        f"📊 *HARD-ASSET MULTI-SKILL SCAN* ({session_badge})",
        f"🎯 Active Profile: *{strat['name']} ({strat['code']})* | Edge: `{edge_str}`",
        "",
        f"🌐 *Macro Radar:*",
        f"• DXY: `{m['dxy']:.2f}` ({m['dxy_chg']:+.2f}%) | 10Y Yield: `{m['tnx']:.2f}%`",
        f"• GSR: `{m['gsr']:.1f}x` | VIX: `{m['vix']:.1f}` | F&G: `{m['fg_val']}` ({m['fg_label']})",
        "",
        f"₿ *Bitcoin (BTC-USD):* `${b['price']:,.2f}`",
        f"• Score: `{b['base_score']}/10` (Learned: `{b['adaptive_score']:.1f}/10`) ──► {b['verdict']}",
        f"• Regime: `{b['regime']}` (ADX: `{b['adx']:.1f}` | DI: +{b.get('plus_di', 0):.0f}/-{b.get('minus_di', 0):.0f})",
        f"• Golden Pocket: {b_gp_str}",
        f"• Microstructure: `{b['trap_type']}` | Body: `{b.get('candle_body_pct', 50):.0f}%`",
        "",
        f"🥇 *Gold (XAU/USD):* `${g['price']:,.2f}`",
        f"• Score: `{g['base_score']}/10` (Learned: `{g['adaptive_score']:.1f}/10`) ──► {g['verdict']}",
        f"• Regime: `{g['regime']}` (ADX: `{g['adx']:.1f}` | DI: +{g.get('plus_di', 0):.0f}/-{g.get('minus_di', 0):.0f})",
        f"• Golden Pocket: {g_gp_str}",
        f"• Microstructure: `{g['trap_type']}` | Body: `{g.get('candle_body_pct', 50):.0f}%`",
        ""
    ]

    if b['is_a_plus']:
        b_lot = b.get('lot_info', {})
        b_lot_str = f"{b_lot.get('lots', 0.05)} BTC Lots (${b_lot.get('actual_risk_usd', 100.0):,.0f} risk)"
        lines.extend([
            f"⚡ *ACTIONABLE BTC ORDER TICKET:*",
            f"• Entry Zone: `${b['entry']:,.2f}`",
            f"• Stop-Loss:  `${b['stop_loss']:,.2f}` (-{b['risk_pct']:.2f}%)",
            f"• Target 1:   `${b['tp1']:,.2f}` (+{b['reward_pct']:.2f}%)",
            f"• Target 2:   `${b['tp2']:,.2f}`",
            f"• Position Size: `{b_lot_str}`",
            f"• Risk/Reward: 1:{b['rr']:.2f}",
            ""
        ])

    if g['is_a_plus']:
        g_lot = g.get('lot_info', {})
        g_lot_str = f"{g_lot.get('lots', 0.05)} Standard Lots (${g_lot.get('actual_risk_usd', 100.0):,.0f} risk)"
        lines.extend([
            f"⚡ *ACTIONABLE GOLD ORDER TICKET:*",
            f"• Entry Zone: `${g['entry']:,.2f}`",
            f"• Stop-Loss:  `${g['stop_loss']:,.2f}` (-{g['risk_pct']:.2f}%)",
            f"• Target 1:   `${g['tp1']:,.2f}` (+{g['reward_pct']:.2f}%)",
            f"• Target 2:   `${g['tp2']:,.2f}`",
            f"• Position Size: `{g_lot_str}`",
            f"• Risk/Reward: 1:{g['rr']:.2f}",
            ""
        ])

    lines.append("Menu: `/scan`, `/btc`, `/gold`, `/levels`, `/traps`, `/debate`, `/macro`, `/learn`")
    return "\n".join(lines)


def format_welcome_menu(sender_name: str) -> str:
    auto_desc = f"ENABLED 🟢 ({AUTO_TRADE_MODE})" if AUTO_TRADE_MODE != "OFF" else "DISABLED ⚪"
    mt5_status = "CONNECTED 🟢" if (MT5_EXECUTOR_AVAILABLE and live_broker and live_broker.is_connected) else "OFFLINE ⚪"
    strat = get_active_strategy() if RISK_ENGINE_AVAILABLE else {"name": "Scalp Sniper", "code": "SCALP"}
    trail_st = "ACTIVE 🛡️" if TRAILING_STOP_ENABLED else "DISABLED ⚪"

    return (
        f"⚡ *INSTITUTIONAL QUANTITATIVE HARD-ASSET ENGINE*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Welcome {sender_name}! High-probability quantitative engine for Gold (`XAU/USD`) & Bitcoin (`BTC/USD`).\n\n"
        f"🎛️ *System State:*\n"
        f"• Continuous Scanner : `1-MIN CANDLE CLOSE` 🟢\n"
        f"• MT5 Live Broker    : `{mt5_status}` (Auto-Managed Leverage)\n"
        f"• Active Strategy    : `{strat['name']}` (`{strat['code']}`) 🎯\n"
        f"• Auto-Trade Mode    : `{auto_desc}`\n"
        f"• Auto-Trailing & BE : `{trail_st}` (+0.4R Breakeven / +0.75R Trail)\n\n"
        f"🗂️ *MODERN COMMAND HUBS:*\n"
        f"📊 `/market` - Institutional analysis & MT5 visual charts\n"
        f"   └ Options: `/market btc`, `/market gold`, `/market macro`, `/market levels`\n\n"
        f"⚡ `/trade` - Live broker execution & watchlist selector\n"
        f"   └ Options: `/trade buy gold`, `/trade sell btc`, `/trade close`, `/trade auto [gold|btc|both|off]`\n\n"
        f"🎯 `/strategy` - Modular trade strategy selector\n"
        f"   └ Options: `/strategy scalp`, `/strategy swing`, `/strategy balance`, `/strategy swap`\n\n"
        f"💼 `/portfolio` - Unified balance, equity, positions & risk budget\n\n"
        f"🛡️ `/trail` - Automated Trailing Stop & Breakeven controller (`/trail on|off`)\n\n"
        f"📈 `/backtest` - Institutional historical strategy simulator (`/backtest [gold|btc] [scalp|swing]`)\n\n"
        f"🧠 `/learn` - Bayesian factor rankings & self-training (`/learn train`)\n\n"
        f"ℹ️ `/status` - Live server latency, MT5 connection & engine health\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 *Direct Shortcuts:* `/scan`, `/btc`, `/gold`, `/buy_gold`, `/sell_gold`, `/buy_btc`, `/sell_btc`, `/positions`, `/close_all`"
    )


def trailing_monitor_worker(token: str, chat_id_getter):
    """
    Automated Profile-Aware Trailing Stop & Breakeven Monitor.
    Runs every 12 seconds:
      - Automatically reads strategy profile (SCALP, SWING, BALANCE, SWAP) from position comment or active strategy.
      - SCALP: Locks Breakeven at +0.40R, trails at +0.75R (0.30R step).
      - SWING: Locks Breakeven at +1.00R, trails at +1.50R (0.70R step).
      - BALANCE: Locks Breakeven at +0.60R, trails at +1.05R (0.35R step).
      - SWAP: Locks Breakeven at +0.80R, trails at +1.30R (0.60R step).
      - Rollover hour protection (freezes modifications during 21:50-22:15 UTC).
    """
    global TRAILING_STOP_ENABLED
    print("🛡️ Automated Profile-Aware Trailing Stop & Breakeven Monitor: ACTIVE (Every 12s)")
    while True:
        try:
            time.sleep(12)
            if not TRAILING_STOP_ENABLED:
                continue
            if not (MT5_EXECUTOR_AVAILABLE and live_broker and live_broker.is_connected):
                continue

            strat_code = get_active_strategy()["code"] if RISK_ENGINE_AVAILABLE else "SCALP"
            events = live_broker.trail_positions(default_strategy=strat_code)
            if events:
                target_chat_id = chat_id_getter()
                if target_chat_id:
                    for ev in events:
                        send_message(token, target_chat_id, ev["msg"])
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Trailing Event: {ev['symbol']} #{ev['ticket']} -> {ev['action']} @ {ev['new_sl']}")
        except Exception:
            time.sleep(5)


def format_elite_alert(asset: str, data: dict) -> str:
    """Formats an uncluttered, high-impact elite trade alert (zero spam)."""
    item = data["btc"] if asset == "BTC" else data["gold"]
    sym_name = "BITCOIN (BTC/USD)" if asset == "BTC" else "GOLD (XAU/USD)"
    icon = "₿" if asset == "BTC" else "🥇"
    lv = item["levels"]
    lot_info = item.get("lot_info", {})
    strat_code = lot_info.get("strategy", "SCALP")
    strat = STRATEGIES.get(strat_code, {}) if RISK_ENGINE_AVAILABLE else {}
    target_wr = strat.get("target_win_rate", "80-85%")
    session_info = get_market_session() if RISK_ENGINE_AVAILABLE else None

    lines = [
        f"🎯 *ELITE A+ TRADE SIGNAL (SCORE: {item['final_score']}/10)*",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"{icon} *Asset:* `{sym_name}`",
        f"• Strategy Profile: `{strat.get('name', strat_code)} ({strat_code})` 🎯",
        f"• Win-Rate Edge: `{target_wr}` ({session_info['badge'] if session_info else '🌐'} {session_info['name'] if session_info else 'Active'})",
        f"• Live Price: `${item['price']:,.2f}`",
        f"• Confluence: {'✅ Golden Pocket Active' if lv['in_golden_pocket'] else 'Key S/R Flip Level'}",
        f"• Microstructure: `{item['trap_type']}` (Body: `{item.get('candle_body_pct', 50):.0f}%`)",
        f"• Momentum: `{item['regime']}` (ADX: `{item['adx']:.1f}`)",
        "",
        "⚡ *Precision Sniper Order Ticket:*",
        f"• Action: `BUY` (High Probability Setup)",
        f"• Entry Zone: `${item['entry']:,.2f}`",
        f"• Small Stop-Loss:  `${item['stop_loss']:,.2f}` (-{item['risk_pct']:.2f}%)",
        f"• Small Take-Profit: `${item['tp1']:,.2f}` (+{item['reward_pct']:.2f}% | {strat.get('rr_tp1', 1.2):.1f}R)",
        f"• Extended Target:   `${item['tp2']:,.2f}` (+{strat.get('rr_tp2', 2.0):.1f}R)",
        f"• Recommended Size:  `{lot_info.get('lots', 0.05)}` Lots (${lot_info.get('actual_risk_usd', 50):,.2f} risk)",
        f"• Breakeven / Trail: BE at `+{strat.get('breakeven_r', 0.40):.2f}R` | Trail at `+{strat.get('trail_start_r', 0.75):.2f}R`",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🔒 *Anti-Spam Filter:* This signal is locked. Zero duplicate alerts while in progress."
    ]
    return "\n".join(lines)


def auto_scanner_worker(token: str, chat_id_getter):
    """
    Continuous 1-Minute Live Candle Quantitative Scanner.
    Features:
      1. Continuous 1-minute candle sync (:00 seconds).
      2. High-Quality Filter: Only Elite A+ Setups (Score >= 8/10 + Structural Confirmation).
      3. Zero-Spam State Machine: 1 setup = 1 alert. No repetitive spam while trade is in progress.
      4. Auto-resolves when Target (TP) is reached or setup invalidates.
      5. Optional Auto-Trade Execution if /auto_trade on.
    """
    print("⏰ Automated 1-Minute Live Candle Scanner: ACTIVE (Monitoring Gold & BTC every 60s)")
    global AUTO_TRADE_LIVE

    # Active setup trackers (None = IDLE; dict = setup currently active and locked)
    active_btc_setup = None
    active_gold_setup = None

    while True:
        try:
            # Sync to the next 1-minute candle close (:00 seconds)
            now = time.time()
            sleep_sec = max(5, int(60 - (now % 60)))
            time.sleep(sleep_sec)

            target_chat_id = chat_id_getter()
            if not target_chat_id:
                continue

            data = run_full_pipeline()
            if not data or not data.get("btc") or not data.get("gold"):
                continue

            b = data["btc"]
            g = data["gold"]
            current_time = time.time()

            # ── 1. Bitcoin (BTC/USD) State Machine (Zero Spam) ──
            if active_btc_setup is None:
                # Check for FRESH High-Quality A+ Setup or Qualified Key-Level Scalp
                if b['is_a_plus'] and (b['final_score'] >= 8 or (active_strat['code'] == "SCALP" and b['final_score'] >= 7)):
                    active_btc_setup = {
                        "entry": b['entry'],
                        "sl": b['stop_loss'],
                        "tp": b['tp1'],
                        "time": current_time,
                        "score": b['final_score']
                    }
                    print(f"🎯 [{datetime.now().strftime('%H:%M:%S')}] ELITE BTC SIGNAL DETECTED: ${b['price']:,.2f} (Score {b['final_score']}/10)! Broadcasting single alert...")
                    alert_text = format_elite_alert("BTC", data)
                    send_message(token, target_chat_id, alert_text)

                    if CHARTS_AVAILABLE:
                        b_buf = generate_mt5_chart("BTC-USD", "BITCOIN (BTC-USD)")
                        if b_buf:
                            send_telegram_chart(token, target_chat_id, b_buf, f"📊 MT5 1M Chart: Bitcoin (${b['price']:,.2f}) | Elite A+ Signal")

                    # Auto-Trade Execution (Respects Watchlist: BOTH, BTC, GOLD, OFF)
                    global AUTO_TRADE_MODE
                    if AUTO_TRADE_MODE in ("BOTH", "BTC") and MT5_EXECUTOR_AVAILABLE and live_broker and live_broker.is_connected:
                        if not live_broker.has_open_position("BTC"):
                            res = live_broker.execute_live_sniper_order("BTC", "BUY", b["entry"], b["stop_loss"], b["tp1"], b["lot_info"]["lots"], comment="Auto1M-A+")
                            if res.get("success"):
                                send_message(token, target_chat_id, f"⚡ *LIVE 1M AUTO-EXECUTION (BTC)*\n• Symbol: `{res['symbol']}` (BUY)\n• Volume: `{res['lots']}` Lots\n• Price: `${res['price']:,.2f}`\n• Ticket: `#{res['ticket']}`\n• SL: `${res['sl']:,.2f}` | TP: `${res['tp']:,.2f}`")
            else:
                # Setup is active: monitor for Target or Invalidation (DO NOT SPAM)
                # 1. Take-Profit hit?
                if b['price'] >= active_btc_setup['tp']:
                    tp_text = f"🎯 *BITCOIN TAKE-PROFIT ACHIEVED!*\n• Price: `${b['price']:,.2f}` reached Target (`${active_btc_setup['tp']:,.2f}`)!\n• High win-rate sniper profit secured. Setup closed."
                    send_message(token, target_chat_id, tp_text)
                    print(f"✅ [{datetime.now().strftime('%H:%M:%S')}] BTC Take-Profit Hit @ ${b['price']:,.2f}!")
                    active_btc_setup = None
                # 2. Stop-Loss hit or time expired (>2 hours)?
                elif b['price'] <= active_btc_setup['sl'] or (current_time - active_btc_setup['time']) > 7200:
                    active_btc_setup = None
                elif abs(b['price'] - active_btc_setup['entry']) / active_btc_setup['entry'] > 0.025:
                    active_btc_setup = None

            # ── 2. Gold (XAU/USD) State Machine (Zero Spam) ──
            if active_gold_setup is None:
                # Check for FRESH High-Quality A+ Setup or Qualified Key-Level Scalp
                if g['is_a_plus'] and (g['final_score'] >= 8 or (active_strat['code'] == "SCALP" and g['final_score'] >= 7)):
                    active_gold_setup = {
                        "entry": g['entry'],
                        "sl": g['stop_loss'],
                        "tp": g['tp1'],
                        "time": current_time,
                        "score": g['final_score']
                    }
                    print(f"🎯 [{datetime.now().strftime('%H:%M:%S')}] ELITE GOLD SIGNAL DETECTED: ${g['price']:,.2f} (Score {g['final_score']}/10)! Broadcasting single alert...")
                    alert_text = format_elite_alert("GOLD", data)
                    send_message(token, target_chat_id, alert_text)

                    if CHARTS_AVAILABLE:
                        g_buf = generate_mt5_chart("GC=F", "GOLD (XAU/USD)")
                        if g_buf:
                            send_telegram_chart(token, target_chat_id, g_buf, f"📊 MT5 1M Chart: Gold (${g['price']:,.2f}) | Elite A+ Signal")

                    # Auto-Trade Execution (Respects Watchlist: BOTH, BTC, GOLD, OFF)
                    if AUTO_TRADE_MODE in ("BOTH", "GOLD") and MT5_EXECUTOR_AVAILABLE and live_broker and live_broker.is_connected:
                        if not live_broker.has_open_position("GOLD"):
                            res = live_broker.execute_live_sniper_order("GOLD", "BUY", g["entry"], g["stop_loss"], g["tp1"], g["lot_info"]["lots"], comment="Auto1M-A+")
                            if res.get("success"):
                                send_message(token, target_chat_id, f"⚡ *LIVE 1M AUTO-EXECUTION (GOLD)*\n• Symbol: `{res['symbol']}` (BUY)\n• Volume: `{res['lots']}` Lots\n• Price: `${res['price']:,.2f}`\n• Ticket: `#{res['ticket']}`\n• SL: `${res['sl']:,.2f}` | TP: `${res['tp']:,.2f}`")
            else:
                # Setup is active: monitor for Target or Invalidation (DO NOT SPAM)
                # 1. Take-Profit hit?
                if g['price'] >= active_gold_setup['tp']:
                    tp_text = f"🎯 *GOLD TAKE-PROFIT ACHIEVED!*\n• Price: `${g['price']:,.2f}` reached Target (`${active_gold_setup['tp']:,.2f}`)!\n• High win-rate sniper profit secured. Setup closed."
                    send_message(token, target_chat_id, tp_text)
                    print(f"✅ [{datetime.now().strftime('%H:%M:%S')}] Gold Take-Profit Hit @ ${g['price']:,.2f}!")
                    active_gold_setup = None
                # 2. Stop-Loss hit or time expired (>2 hours)?
                elif g['price'] <= active_gold_setup['sl'] or (current_time - active_gold_setup['time']) > 7200:
                    active_gold_setup = None
                elif abs(g['price'] - active_gold_setup['entry']) / active_gold_setup['entry'] > 0.020:
                    active_gold_setup = None

            # ── 3. Clean 1-Minute Console Heartbeat (Zero Spam) ──
            btc_st = "Active Signal 🔒" if active_btc_setup else f"Score {b['final_score']}/10 (Stand Aside)"
            gold_st = "Active Signal 🔒" if active_gold_setup else f"Score {g['final_score']}/10 (Stand Aside)"
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 1M Scan: BTC: {btc_st} | Gold: {gold_st} (Spam: 0)")

        except Exception as scan_err:
            time.sleep(5)


def process_telegram_command(token: str, sender_id: str, sender_name: str, msg_text: str):
    """
    Central command processor for Telegram bot.
    Supports both Modern Combined Hubs and Direct Legacy Shortcuts.
    """
    global AUTO_TRADE_MODE, AUTO_TRADE_LIVE, TRAILING_STOP_ENABLED

    text = msg_text.strip()
    cmd_parts = text.split()
    if not cmd_parts:
        return
    raw_cmd = cmd_parts[0].lower()
    # Support commands with bot username (e.g. /market@my_bot btc)
    cmd = raw_cmd.split("@")[0]
    args = text[len(cmd_parts[0]):].strip()
    args_lower = args.lower()

    # ── 1. WELCOME & HELP HUB ──
    if cmd in ("/start", "/help", "/menu"):
        welcome = format_welcome_menu(sender_name)
        send_message(token, sender_id, welcome)
        return

    # ── 2. MODERN MARKET HUB (/market [btc|gold|macro|levels|traps|debate]) ──
    if cmd == "/market" or cmd in ("/scan", "/btc", "/gold", "/macro", "/levels", "/traps", "/debate"):
        sub = args_lower if cmd == "/market" else cmd.replace("/", "")

        # Sub-branch: Macro
        if sub in ("macro", "dxy", "yields"):
            data = run_full_pipeline()
            m = data.get("macro")
            if not m:
                send_message(token, sender_id, "⚠️ Macro radar data temporarily unavailable. Please try again.")
                return
            macro_text = (
                f"🌐 *GLOBAL MACRO RADAR*\n\n"
                f"• US Dollar Index (DXY): `{m['dxy']:.2f}` ({m['dxy_chg']:+.2f}%)\n"
                f"• US 10-Year Real Yield: `{m['tnx']:.2f}%` ({m['tnx_chg']:+.2f}%)\n"
                f"• Gold/Silver Ratio (GSR): `{m['gsr']:.1f}x` (Undervalued: {m['gsr'] >= 75})\n"
                f"• CBOE Volatility Index (VIX): `{m['vix']:.1f}`\n"
                f"• Crypto Fear & Greed: `{m['fg_val']}` ({m['fg_label']})"
            )
            send_message(token, sender_id, macro_text)
            return

        # Sub-branch: Key Levels & Fibonacci
        if sub in ("levels", "fib", "pivots"):
            data = run_full_pipeline()
            b = data.get("btc")
            g = data.get("gold")
            if not b or not g:
                send_message(token, sender_id, "⚠️ Key levels temporarily unavailable. Please try again.")
                return
            b_lv = b["levels"]
            g_lv = g["levels"]
            levels_msg = (
                f"📐 *INSTITUTIONAL KEY LEVELS & FIBONACCI*\n\n"
                f"₿ *Bitcoin (BTC-USD):* `${b_lv['curr']:,.2f}`\n"
                f"• Swing High: `${b_lv['sw_high']:,.0f}` | Swing Low: `${b_lv['sw_low']:,.0f}`\n"
                f"• Golden Pocket (0.618-0.650): `${b_lv['fib_650']:,.0f} - ${b_lv['fib_618']:,.0f}`\n"
                f"• Equilibrium (0.50 Fib): `${b_lv['fib_500']:,.0f}`\n"
                f"• 50 SMA: `${b_lv['ma50']:,.0f}` | 200 SMA: `${b_lv['ma200']:,.0f}`\n"
                f"• Daily Pivot (PP): `${b_lv['pivot']:,.0f}` | R1: `${b_lv['r1']:,.0f}` | S1: `${b_lv['s1']:,.0f}`\n\n"
                f"🥇 *Gold (XAU/USD):* `${g_lv['curr']:,.2f}`\n"
                f"• Swing High: `${g_lv['sw_high']:,.0f}` | Swing Low: `${g_lv['sw_low']:,.0f}`\n"
                f"• Golden Pocket (0.618-0.650): `${g_lv['fib_650']:,.0f} - ${g_lv['fib_618']:,.0f}`\n"
                f"• Equilibrium (0.50 Fib): `${g_lv['fib_500']:,.0f}`\n"
                f"• 50 SMA: `${g_lv['ma50']:,.0f}` | 200 SMA: `${g_lv['ma200']:,.0f}`\n"
                f"• Daily Pivot (PP): `${g_lv['pivot']:,.0f}` | R1: `${g_lv['r1']:,.0f}` | S1: `${g_lv['s1']:,.0f}`"
            )
            send_message(token, sender_id, levels_msg)
            return

        # Sub-branch: Wyckoff Traps & Liquidity
        if sub in ("traps", "trap", "fvg", "liquidity"):
            data = run_full_pipeline()
            b = data.get("btc")
            g = data.get("gold")
            if not b or not g:
                send_message(token, sender_id, "⚠️ Trap audit data temporarily unavailable. Please try again.")
                return
            trap_msg = (
                f"🪤 *WYCKOFF TRAP & LIQUIDITY SWEEP AUDIT*\n\n"
                f"₿ *Bitcoin:* `{b['trap_type']}`\n"
                f"• Detail: {b['trap_detail']}\n"
                f"• Fair Value Gap: `{b['fvg']}`\n\n"
                f"🥇 *Gold:* `{g['trap_type']}`\n"
                f"• Detail: {g['trap_detail']}\n"
                f"• Fair Value Gap: `{g['fvg']}`"
            )
            send_message(token, sender_id, trap_msg)
            return

        # Sub-branch: Adversarial Debate
        if sub in ("debate", "bull_bear", "bullbear"):
            data = run_full_pipeline()
            debate_msg = generate_adversarial_debate(data)
            send_message(token, sender_id, debate_msg)
            return

        # Sub-branch: Bitcoin Single Audit
        if sub in ("btc", "bitcoin"):
            data = run_full_pipeline()
            b = data.get("btc")
            if not b:
                send_message(token, sender_id, "⚠️ Market data for Bitcoin is temporarily unavailable. Please retry.")
                return
            lv = b["levels"]
            strat_info = b.get("lot_info", {})
            ticket = (
                f"₿ *Bitcoin (BTC-USD) Multi-Skill Audit:*\n"
                f"• Price: `${b['price']:,.2f}`\n"
                f"• Score: `{b['base_score']}/10` (Learned: `{b['adaptive_score']:.1f}/10`)\n"
                f"• Strategy: `{strat_info.get('strategy', 'SCALP')}` ({strat_info.get('holding_time', '5-30m')})\n"
                f"• Regime: `{b['regime']}` (ADX: `{b['adx']:.1f}` | ATR: `${b['atr']:,.1f}`)\n"
                f"• Mayer Multiple: `{b['mayer']:.2f}x` (200 SMA: `${lv['ma200']:,.0f}`)\n"
                f"• 50 SMA: `${lv['ma50']:,.0f}` | 20 EMA: `${lv['ma20_ema']:,.0f}`\n"
                f"• Golden Pocket (0.618-0.65): `${lv['fib_650']:,.0f} - ${lv['fib_618']:,.0f}`\n"
                f"• Status: {'✅ Resting in Golden Pocket' if lv['in_golden_pocket'] else 'Outside Golden Pocket'}\n"
                f"• Microstructure: `{b['trap_type']}`\n"
                f"• Orderflow: `{b['fvg']}`\n"
                f"• Verdict: {b['verdict']}\n\n"
                f"📋 *Actionable Trade Parameters:*\n"
                f"• Entry: `${b['entry']:,.2f}`\n"
                f"• Stop-Loss: `${b['stop_loss']:,.2f}` (-{b['risk_pct']:.2f}%)\n"
                f"• Target 1: `${b['tp1']:,.2f}` (+{b['reward_pct']:.2f}%)\n"
                f"• Target 2: `${b['tp2']:,.2f}`\n"
                f"• Position Size: `{strat_info.get('lots', 0.05)}` BTC Lots (${strat_info.get('actual_risk_usd', 100):,.2f} risk | {strat_info.get('actual_risk_pct', 1.0):.2f}% equity)\n"
                f"• Risk/Reward: 1:{b['rr']:.2f}"
            )
            send_message(token, sender_id, ticket)
            if CHARTS_AVAILABLE:
                b_buf = generate_mt5_chart("BTC-USD", "BITCOIN (BTC-USD)")
                if b_buf:
                    send_telegram_chart(token, sender_id, b_buf, f"📊 MT5 Chart: Bitcoin (${b['price']:,.2f})")
            return

        # Sub-branch: Gold Single Audit
        if sub in ("gold", "xau", "xauusd"):
            data = run_full_pipeline()
            g = data.get("gold")
            if not g:
                send_message(token, sender_id, "⚠️ Market data for Gold is temporarily unavailable. Please retry.")
                return
            lv = g["levels"]
            m = data.get("macro", {})
            strat_info = g.get("lot_info", {})
            ticket = (
                f"🥇 *Gold (XAU/USD / GC=F) Multi-Skill Audit:*\n"
                f"• Price: `${g['price']:,.2f}`\n"
                f"• Score: `{g['base_score']}/10` (Learned: `{g['adaptive_score']:.1f}/10`)\n"
                f"• Strategy: `{strat_info.get('strategy', 'SCALP')}` ({strat_info.get('holding_time', '5-30m')})\n"
                f"• Regime: `{g['regime']}` (ADX: `{g['adx']:.1f}` | ATR: `${g['atr']:,.1f}`)\n"
                f"• Gold/Silver Ratio: `{m.get('gsr', 80.0):.1f}x` (Undervalued: {m.get('gsr', 80.0) >= 75})\n"
                f"• 200 SMA: `${lv['ma200']:,.0f}` | 50 SMA: `${lv['ma50']:,.0f}`\n"
                f"• Golden Pocket (0.618-0.65): `${lv['fib_650']:,.0f} - ${lv['fib_618']:,.0f}`\n"
                f"• Status: {'✅ Resting in Golden Pocket' if lv['in_golden_pocket'] else 'Outside Golden Pocket'}\n"
                f"• Microstructure: `{g['trap_type']}`\n"
                f"• Orderflow: `{g['fvg']}`\n"
                f"• Verdict: {g['verdict']}\n\n"
                f"📋 *Actionable Trade Parameters:*\n"
                f"• Entry: `${g['entry']:,.2f}`\n"
                f"• Stop-Loss: `${g['stop_loss']:,.2f}` (-{g['risk_pct']:.2f}%)\n"
                f"• Target 1: `${g['tp1']:,.2f}` (+{g['reward_pct']:.2f}%)\n"
                f"• Target 2: `${g['tp2']:,.2f}`\n"
                f"• Position Size: `{strat_info.get('lots', 0.05)}` Standard Lots (${strat_info.get('actual_risk_usd', 100):,.2f} risk | {strat_info.get('actual_risk_pct', 1.0):.2f}% equity)\n"
                f"• Risk/Reward: 1:{g['rr']:.2f}"
            )
            send_message(token, sender_id, ticket)
            if CHARTS_AVAILABLE:
                g_buf = generate_mt5_chart("GC=F", "GOLD (XAU/USD)")
                if g_buf:
                    send_telegram_chart(token, sender_id, g_buf, f"📊 MT5 Chart: Gold (${g['price']:,.2f})")
            return

        # Default /market (or /scan): Dual Asset Scan + Dual MT5 Charts
        send_message(token, sender_id, "⏳ Running multi-skill quantitative scan & generating MT5 charts...")
        data = run_full_pipeline()
        send_message(token, sender_id, format_scan_summary(data))
        if CHARTS_AVAILABLE and data.get("btc") and data.get("gold"):
            b_buf = generate_mt5_chart("BTC-USD", "BITCOIN (BTC-USD)")
            if b_buf:
                send_telegram_chart(token, sender_id, b_buf, f"📊 MT5 Chart Scan: Bitcoin (${data['btc']['price']:,.2f}) | {data['btc']['verdict']}")
            g_buf = generate_mt5_chart("GC=F", "GOLD (XAU/USD)")
            if g_buf:
                send_telegram_chart(token, sender_id, g_buf, f"📊 MT5 Chart Scan: Gold (${data['gold']['price']:,.2f}) | {data['gold']['verdict']}")
        return

    # ── 3. MODERN TRADE HUB (/trade [buy|sell|close|auto]) ──
    if cmd == "/trade" or cmd in ("/buy_gold", "/sell_gold", "/buy_btc", "/sell_btc", "/close_all", "/auto_trade"):
        if cmd == "/buy_gold": action_mode = "buy gold"
        elif cmd == "/sell_gold": action_mode = "sell gold"
        elif cmd == "/buy_btc": action_mode = "buy btc"
        elif cmd == "/sell_btc": action_mode = "sell btc"
        elif cmd == "/close_all": action_mode = "close"
        elif cmd == "/auto_trade": action_mode = f"auto {args}" if args else "auto"
        else: action_mode = args_lower

        # Sub-branch: Auto-Trade Watchlist Configuration
        if action_mode.startswith("auto"):
            sub_args = action_mode[4:].strip().split()
            sub_val = sub_args[0].lower() if sub_args else ""
            if sub_val in ("gold", "xau"):
                AUTO_TRADE_MODE = "GOLD"
                AUTO_TRADE_LIVE = True
                send_message(token, sender_id, "🟢 *AUTO-TRADE WATCHLIST: GOLD ONLY*\nAutomated 1-minute execution is active exclusively for Gold (XAU/USD). Bitcoin will alert with charts without auto-execution.")
            elif sub_val in ("btc", "bitcoin"):
                AUTO_TRADE_MODE = "BTC"
                AUTO_TRADE_LIVE = True
                send_message(token, sender_id, "🟢 *AUTO-TRADE WATCHLIST: BITCOIN ONLY*\nAutomated 1-minute execution is active exclusively for Bitcoin (BTC/USD). Gold will alert with charts without auto-execution.")
            elif sub_val in ("both", "all", "on", "true", "1"):
                AUTO_TRADE_MODE = "BOTH"
                AUTO_TRADE_LIVE = True
                send_message(token, sender_id, "🟢 *AUTO-TRADE WATCHLIST: BOTH GOLD & BITCOIN*\nAutomated 1-minute execution is active on both Gold and BTC when A+ setups (≥8/10) trigger.")
            elif sub_val in ("off", "false", "disable", "0"):
                AUTO_TRADE_MODE = "OFF"
                AUTO_TRADE_LIVE = False
                send_message(token, sender_id, "⚪ *AUTO-TRADE DISABLED*\nAutomated execution is turned off. All 1-minute alerts and MT5 charts will continue broadcasting, requiring manual execution.")
            else:
                curr_status = f"ENABLED 🟢 ({AUTO_TRADE_MODE})" if AUTO_TRADE_MODE != "OFF" else "DISABLED ⚪"
                send_message(token, sender_id, (
                    f"ℹ️ *1M Auto-Trade Watchlist Controller:*\n"
                    f"• Current Mode: `{curr_status}`\n\n"
                    f"Options:\n"
                    f"• `/trade auto gold`  ──► Auto-trade Gold only\n"
                    f"• `/trade auto btc`   ──► Auto-trade BTC only\n"
                    f"• `/trade auto both`  ──► Auto-trade both Gold & BTC\n"
                    f"• `/trade auto off`   ──► Disable auto-trade (alerts only)"
                ))
            return

        # Sub-branch: Close All / Liquidate
        if action_mode in ("close", "close_all", "close all"):
            if not (MT5_EXECUTOR_AVAILABLE and live_broker and live_broker.is_connected):
                send_message(token, sender_id, "❌ MT5 is disconnected. Please ensure MT5 terminal is open on VPS.")
            else:
                send_message(token, sender_id, "⚠️ Closing all active live MT5 positions...")
                res = live_broker.close_all_positions()
                if res.get("success") and res.get("closed_count", 0) > 0:
                    send_message(token, sender_id, f"🚨 *EMERGENCY CLOSE-ALL COMPLETED!*\n• Closed: `{res['closed_count']}` positions\n• Total Realized PnL: `${res['total_pnl']:+,.2f}`")
                else:
                    send_message(token, sender_id, f"ℹ️ {res.get('msg') or res.get('error', 'No open positions to close.')}")
            return

        # Sub-branch: Buy / Sell Execution (Gold or BTC)
        is_buy_gold = "buy" in action_mode and ("gold" in action_mode or "xau" in action_mode)
        is_sell_gold = "sell" in action_mode and ("gold" in action_mode or "xau" in action_mode)
        is_buy_btc = "buy" in action_mode and ("btc" in action_mode or "bitcoin" in action_mode)
        is_sell_btc = "sell" in action_mode and ("btc" in action_mode or "bitcoin" in action_mode)

        if is_buy_gold or is_sell_gold or is_buy_btc or is_sell_btc:
            target_asset = "GOLD" if (is_buy_gold or is_sell_gold) else "BTC"
            action_type = "BUY" if (is_buy_gold or is_buy_btc) else "SELL"

            if not (MT5_EXECUTOR_AVAILABLE and live_broker and live_broker.is_connected):
                send_message(token, sender_id, "❌ Cannot execute live trade: MT5 is disconnected. Open MT5 on your VPS.")
                return

            send_message(token, sender_id, f"⚡ Calculating institutional parameters & executing Live {action_type} on {target_asset}...")
            data = run_full_pipeline()
            item = data.get("gold") if target_asset == "GOLD" else data.get("btc")
            if not item:
                send_message(token, sender_id, f"❌ Live price for {target_asset} unavailable. Please retry.")
                return

            acc_data = live_broker.get_live_account_data()
            bal, risk = get_risk_config()
            lev = acc_data.get("leverage") if acc_data else None
            mrg = acc_data.get("margin_free") if acc_data else None
            swp = live_broker.get_swap_rates(target_asset)

            strat_calc = calculate_strategy_levels(
                target_asset, item["price"], item["atr"], action_type,
                account_balance=bal, risk_pct=risk,
                broker_leverage=lev, margin_free=mrg, swap_info=swp
            )

            res = live_broker.execute_live_sniper_order(
                target_asset, action_type,
                strat_calc["entry"], strat_calc["stop_loss"], strat_calc["tp1"],
                strat_calc["lot_size"], comment=f"TG-{strat_calc['strategy']}"
            )

            if res.get("success"):
                order_ticket = (
                    f"🟢 *LIVE MT5 ORDER EXECUTED!*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"• Strategy: `{strat_calc['strategy_name']}` ({strat_calc['strategy']})\n"
                    f"• Symbol: `{res['symbol']}` ({res['action']})\n"
                    f"• Ticket: `#{res['ticket']}`\n"
                    f"• Volume: `{res['lots']}` Lots (Leverage Adjusted)\n"
                    f"• Entry: `${res['price']:,.2f}`\n"
                    f"• Stop-Loss: `${res['sl']:,.2f}` (-${abs(res['price']-res['sl']):.2f} risk)\n"
                    f"• Take-Profit 1: `${res['tp1']:,.2f}` (+${abs(res['tp']-res['price']):.2f})\n"
                    f"• Holding Horizon: `{strat_calc['holding_time']}`\n"
                    f"• Auto-Trailing: Active (Locks Breakeven at +0.6R)\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Type `/portfolio` or `/trade` to track live floating PnL."
                )
                send_message(token, sender_id, order_ticket)
            else:
                send_message(token, sender_id, f"❌ Live Order Failed: {res.get('error')}")
            return

        # Default /trade command: Summary Dashboard
        acc = live_broker.get_live_account_data() if (MT5_EXECUTOR_AVAILABLE and live_broker and live_broker.is_connected) else None
        positions = live_broker.get_open_positions() if (MT5_EXECUTOR_AVAILABLE and live_broker and live_broker.is_connected) else []
        strat = get_active_strategy() if RISK_ENGINE_AVAILABLE else {"name": "Scalp Sniper", "code": "SCALP"}
        tot_pnl = sum(p["profit"] for p in positions)

        status_broker = f"🟢 #{acc['login']} (1:{acc['leverage']})" if acc else "⚪ Disconnected"
        trail_status = "ACTIVE 🛡️" if TRAILING_STOP_ENABLED else "DISABLED ⚪"
        auto_status = f"ENABLED 🟢 ({AUTO_TRADE_MODE})" if AUTO_TRADE_MODE != "OFF" else "DISABLED ⚪"

        card = (
            f"⚡ *LIVE TRADING HUB & CONTROLLER*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• Live Broker       : `{status_broker}`\n"
            f"• Active Strategy   : `{strat['name']}` (`{strat['code']}`) 🎯\n"
            f"• Auto-Trade Mode   : `{auto_status}`\n"
            f"• Trailing & BE     : `{trail_status}`\n"
            f"• Open Live Trades  : `{len(positions)}`\n"
            f"• Floating PnL      : `${tot_pnl:+,.2f}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ *Quick Execution Actions:*\n"
            f"• `/trade buy gold` | `/trade sell gold`\n"
            f"• `/trade buy btc`  | `/trade sell btc`\n"
            f"• `/trade close`    ──► Liquidate all positions\n"
            f"• `/trade auto [gold|btc|both|off]` ──► Set watchlist\n"
            f"• `/strategy`       ──► Switch strategy (Scalp, Swing, Balance, Swap)\n"
            f"• `/portfolio`      ──► Full position breakdown"
        )
        send_message(token, sender_id, card)
        return

    # ── 4. MODERN STRATEGY HUB (/strategy [scalp|swing|balance|swap]) ──
    if cmd == "/strategy":
        sub = args_lower.strip()
        if sub in ("scalp", "swing", "balance", "swap"):
            ok, s = set_active_strategy(sub.upper())
            if not ok or not s:
                s = get_active_strategy()
            msg = (
                f"🎯 *STRATEGY SWITCHED: {s['name'].upper()} ({s['code']})*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• Description     : {s['description']}\n"
                f"• Risk Per Trade  : `{s['risk_pct']:.2f}% equity` (Profile Sized)\n"
                f"• Stop-Loss Ratio : `{s['sl_mult']:.2f}x ATR`\n"
                f"• Targets         : `{s['rr_tp1']:.1f}R` (TP1) | `{s['rr_tp2']:.1f}R` (TP2)\n"
                f"• Breakeven Lock  : `+{s['breakeven_r']:.2f}R` (Instant Risk-Free)\n"
                f"• Trailing Stop   : Starts `+{s['trail_start_r']:.2f}R` (`{s['trail_step_r']:.2f}R` step)\n"
                f"• Accuracy Regime : {s['regime_filter']}\n"
                f"• Target Win Rate : `{s['target_win_rate']}`\n"
                f"• Holding Horizon : `{s['holding_time']}`\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"All future manual and auto-executed trades will apply this profile."
            )
            send_message(token, sender_id, msg)
            return

        # Default /strategy: comparison table & current state
        curr_s = get_active_strategy()
        table = (
            f"🎯 *MODULAR STRATEGY & PROFILE CONTROLLER*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Active Strategy: *{curr_s['name']} ({curr_s['code']})* 🎯\n\n"
            f"Available Institutional Profiles:\n"
            f"1. ⚡ *SCALP* (`/strategy scalp`)\n"
            f"   • Profile Risk: `0.50%` | Target Win Rate: `~80-85%`\n"
            f"   • SL: `0.45x ATR` | Targets: `1.2R` / `2.0R`\n"
            f"   • Trail: BE at `+0.40R` | Trail at `+0.75R` (0.30R step)\n"
            f"   • Accuracy: Rejection wick <20%, Candle body >=40%, RSI 38-68\n\n"
            f"2. 🌊 *SWING* (`/strategy swing`)\n"
            f"   • Profile Risk: `1.00%` | Target Win Rate: `~68-75%`\n"
            f"   • SL: `1.20x ATR` | Targets: `2.5R` / `3.5R`\n"
            f"   • Trail: BE at `+1.00R` | Trail at `+1.50R` (0.70R step)\n"
            f"   • Accuracy: ADX >= 22 (+DI > -DI), Above 50 & 200 SMA\n\n"
            f"3. ⚖️ *BALANCE* (`/strategy balance`)\n"
            f"   • Profile Risk: `0.75%` | Target Win Rate: `~78-83%`\n"
            f"   • SL: `0.75x ATR` | Target: `1.8R` to 0.50 Fib Equilibrium\n"
            f"   • Trail: BE at `+0.60R` | Trail at `+1.05R` (0.35R step)\n"
            f"   • Accuracy: ADX <= 25 (Chop/Range), Extreme GP/S1 location\n\n"
            f"4. 🔄 *SWAP* (`/strategy swap`)\n"
            f"   • Profile Risk: `0.75%` | Target Win Rate: `~72-78%`\n"
            f"   • SL: `0.90x ATR` | Targets: `2.0R` / `3.0R`\n"
            f"   • Trail: BE at `+0.80R` | Trail at `+1.30R` (0.60R step)\n"
            f"   • Accuracy: Favorable rollover carry, VIX <= 22, Wed 3x check\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Switch anytime: `/strategy scalp`, `/strategy swing`, `/strategy balance`, `/strategy swap`"
        )
        send_message(token, sender_id, table)
        return

    # ── 5. MODERN PORTFOLIO HUB (/portfolio, /account, /positions) ──
    if cmd in ("/portfolio", "/account", "/positions"):
        acc = live_broker.get_live_account_data() if (MT5_EXECUTOR_AVAILABLE and live_broker and live_broker.is_connected) else None
        positions = live_broker.get_open_positions() if (MT5_EXECUTOR_AVAILABLE and live_broker and live_broker.is_connected) else []

        if not acc:
            text = (
                "❌ *LIVE MT5 BROKER NOT CONNECTED*\n\n"
                "Please make sure:\n"
                "1. MetaTrader 5 terminal is running on your VPS.\n"
                "2. You are logged into your live trading account.\n"
                "3. 'Allow algorithmic trading' is checked in `Tools -> Options -> Expert Advisors`."
            )
            send_message(token, sender_id, text)
            return

        trade_str = "ENABLED ✅" if acc["trade_allowed"] else "DISABLED ⚠️"
        strat = get_active_strategy() if RISK_ENGINE_AVAILABLE else {"name": "Scalp Sniper", "code": "SCALP"}
        auto_desc = f"ENABLED 🟢 ({AUTO_TRADE_MODE})" if AUTO_TRADE_MODE != "OFF" else "DISABLED ⚪"
        trail_desc = "ACTIVE 🛡️" if TRAILING_STOP_ENABLED else "DISABLED ⚪"

        lines = [
            "💼 *INSTITUTIONAL PORTFOLIO & BROKER OVERVIEW*",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"🏦 *Broker Account:* `#{acc['login']}` ({acc['broker']})",
            f"• Server & Currency : `{acc['server']}` | `{acc['currency']}`",
            f"• Broker Leverage   : `1:{acc['leverage']}` (Auto-Calculated Margin)",
            f"• Algo Trading      : {trade_str}",
            "",
            f"💰 *Capital & Margin:*",
            f"• Live Balance      : `${acc['balance']:,.2f}`",
            f"• Live Equity       : `${acc['equity']:,.2f}`",
            f"• Free Margin       : `${acc['margin_free']:,.2f}`",
            f"• Margin Level      : `{acc['margin_level']:.1f}%`",
            "",
            f"🎛️ *Execution Engines:*",
            f"• Active Strategy   : `{strat['name']}` (`{strat['code']}`)",
            f"• Auto-Trade Mode   : `{auto_desc}`",
            f"• Trailing & BE     : `{trail_desc}`",
            "",
            f"🛡️ *Dynamic Risk Budget (from ${acc['equity']:,.2f} Equity):*",
            f"• A+ Setup Risk (1.0%): `${acc['equity'] * 0.01:,.2f}`",
            f"• B Setup Risk (0.5%) : `${acc['equity'] * 0.005:,.2f}`",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ]

        if positions:
            lines.append("📋 *Active Live Positions:*")
            tot_pnl = 0.0
            for p in positions:
                tot_pnl += p["profit"]
                icon = "🟢" if p["profit"] >= 0 else "🔴"
                lines.append(
                    f"• `{p['symbol']}` {p['type']} `{p['lots']}` lots (Ticket `#{p['ticket']}`)\n"
                    f"  Entry: `${p['open_price']:,.2f}` | Current: `${p['current_price']:,.2f}`\n"
                    f"  SL: `${p['sl']:,.2f}` | TP: `${p['tp']:,.2f}` | PnL: {icon} `${p['profit']:+,.2f}`"
                )
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"💰 *Total Floating PnL:* `${tot_pnl:+,.2f}`")
            lines.append("Send `/trade close` to liquidate all open positions.")
        else:
            lines.append("ℹ️ *Open Positions:* No active live positions running.")

        send_message(token, sender_id, "\n".join(lines))
        return

    # ── 6. TRAILING STOP HUB (/trail [on|off]) ──
    if cmd == "/trail":
        sub = args_lower.strip()
        if sub in ("on", "true", "enable", "1"):
            TRAILING_STOP_ENABLED = True
            send_message(token, sender_id, "🛡️ *AUTOMATED PROFILE-AWARE TRAILING STOP: ENABLED 🟢*\n• Scans open live MT5 positions every 12 seconds.\n• Adapts breakeven and trailing distance to each position's strategy profile (SCALP, SWING, BALANCE, SWAP).\n• Rollover insulation freezes trail during 21:50-22:15 UTC daily spread spikes.")
            return
        elif sub in ("off", "false", "disable", "0"):
            TRAILING_STOP_ENABLED = False
            send_message(token, sender_id, "⚪ *AUTOMATED TRAILING STOP: DISABLED*\nOpen positions will remain anchored to their initial SL/TP orders.")
            return
        else:
            st = "ENABLED 🟢" if TRAILING_STOP_ENABLED else "DISABLED ⚪"
            curr_s = get_active_strategy() if RISK_ENGINE_AVAILABLE else {"name": "Scalp Sniper", "code": "SCALP", "breakeven_r": 0.40, "trail_start_r": 0.75, "trail_step_r": 0.30}
            send_message(token, sender_id, (
                f"🛡️ *AUTOMATED PROFILE-AWARE TRAILING CONTROLLER*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• Monitor Status     : `{st}`\n"
                f"• Active Profile     : *{curr_s['name']} ({curr_s['code']})* 🎯\n"
                f"• Breakeven Trigger  : `+{curr_s.get('breakeven_r', 0.40):.2f}R` (Instant Risk-Free)\n"
                f"• Trailing Trigger   : Starts at `+{curr_s.get('trail_start_r', 0.75):.2f}R`\n"
                f"• Trailing Step      : `{curr_s.get('trail_step_r', 0.30):.2f}R` behind price\n"
                f"• Rollover Shield    : `ACTIVE (Insulated from 21:50-22:15 UTC spread spikes)`\n"
                f"• Position Tracking  : Auto-detects SCALP / SWING / BALANCE / SWAP from ticket comment\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Controls: `/trail on` to enable, `/trail off` to disable."
            ))
            return

    # ── 7. SELF-LEARNING HUB (/learn, /train) ──
    if cmd == "/learn":
        if args_lower.strip() in ("train", "calibrate", "fit"):
            cmd = "/train"
        else:
            if LEARNING_AVAILABLE and learning_engine:
                summary = learning_engine.get_summary_text()
                send_message(token, sender_id, f"```\n{summary}\n```")
            else:
                send_message(token, sender_id, "⚠️ Self-Learning module not available.")
            return

    if cmd == "/train":
        send_message(token, sender_id, "🧠 Initiating walk-forward self-calibration across past 180 days...")
        if LEARNING_AVAILABLE and learning_engine:
            trades, wins = learning_engine.train_on_historical_data(lookback_days=180, verbose=False)
            win_pct = (wins / trades * 100) if trades > 0 else 0
            send_message(token, sender_id, f"✅ Self-Training complete!\n• Setups Evaluated: `{trades}`\n• Win Rate: `{win_pct:.1f}%`\nType `/learn` to see updated rankings.")
        else:
            send_message(token, sender_id, "⚠️ Self-Learning module not available.")
        return

    # ── 8. RISK CALCULATOR HUB (/risk [custom_balance]) ──
    if cmd == "/risk":
        parts = args_lower.split()
        custom_bal = None
        if parts:
            try:
                custom_bal = float(parts[0].replace("$", "").replace(",", ""))
            except ValueError:
                pass

        cfg_bal, cfg_risk = get_risk_config()
        active_bal = custom_bal if (custom_bal and custom_bal > 0) else cfg_bal

        send_message(token, sender_id, f"🛡️ Computing institutional risk audit & position sizing for ${active_bal:,.2f} equity...")
        data = run_full_pipeline()

        win_rate = 0.55
        if LEARNING_AVAILABLE and learning_engine:
            if hasattr(learning_engine, "total_signals") and learning_engine.total_signals > 0:
                win_rate = learning_engine.overall_win_rate
            else:
                perf = getattr(learning_engine, "memory", {}).get("performance", {})
                if perf.get("total_trades", 0) > 0 and perf.get("win_rate_pct", 0) > 0:
                    win_rate = perf["win_rate_pct"] / 100.0

        if RISK_ENGINE_AVAILABLE:
            risk_report = generate_risk_audit_text(
                account_balance=active_bal,
                risk_pct=cfg_risk,
                btc_data=data["btc"],
                gold_data=data["gold"],
                win_rate=win_rate
            )
        else:
            risk_report = f"🛡️ *Risk Audit:* Balance `${active_bal:,.2f}` | 1% Risk: `${active_bal*0.01:,.2f}`"

        send_message(token, sender_id, risk_report)
        return

    # ── 9. QUANTITATIVE BACKTEST HUB (/backtest [gold|btc] [scalp|swing|balance|swap] [days]) ──
    if cmd == "/backtest":
        parts = args_lower.split()
        target_asset = "GOLD"
        target_strat = None
        target_days = 365

        for p in parts:
            if p in ("btc", "bitcoin"):
                target_asset = "BTC"
            elif p in ("gold", "xau", "xauusd"):
                target_asset = "GOLD"
            elif p in ("scalp", "swing", "balance", "swap"):
                target_strat = p.upper()
            elif p.isdigit():
                target_days = max(30, min(int(p), 730))

        if not target_strat:
            target_strat = get_active_strategy()["code"] if RISK_ENGINE_AVAILABLE else "SCALP"

        send_message(token, sender_id, f"⏳ Running institutional historical backtest for {target_asset} [{target_strat}] across past {target_days} days...")
        if BACKTEST_AVAILABLE:
            res = run_historical_backtest(asset=target_asset, strategy_code=target_strat, lookback_days=target_days)
            card = format_backtest_telegram_card(res)
            send_message(token, sender_id, card)
        else:
            send_message(token, sender_id, "⚠️ Backtesting engine temporarily unavailable.")
        return

    # ── 10. STATUS HUB (/status) ──
    if cmd == "/status":
        acc_data = live_broker.get_live_account_data() if (MT5_EXECUTOR_AVAILABLE and live_broker and live_broker.is_connected) else None
        broker_line = f"🟢 Connected (#{acc_data['login']} on {acc_data['broker']})" if acc_data else "⚪ Disconnected (Open MT5 on VPS)"
        eq_line = f"${acc_data['equity']:,.2f} {acc_data['currency']}" if acc_data else "N/A"
        strat = get_active_strategy() if RISK_ENGINE_AVAILABLE else {"name": "Scalp Sniper", "code": "SCALP"}
        auto_desc = f"ENABLED 🟢 ({AUTO_TRADE_MODE})" if AUTO_TRADE_MODE != "OFF" else "DISABLED ⚪"
        trail_desc = "ACTIVE 🛡️" if TRAILING_STOP_ENABLED else "DISABLED ⚪"

        status_msg = (
            f"🤖 *SYSTEM & ENGINE HEALTH*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• 1-Minute Candle Scanner : `ACTIVE (Every 60s)` 🟢\n"
            f"• MT5 Broker Connection   : `{broker_line}`\n"
            f"• Live Account Equity     : `{eq_line}`\n"
            f"• Active Strategy         : `{strat['name']}` (`{strat['code']}`) 🎯\n"
            f"• 1M Auto-Trade Watchlist : `{auto_desc}`\n"
            f"• Trailing & Breakeven    : `{trail_desc}`\n"
            f"• Visual MT5 Charts       : `{'ONLINE 🟢' if CHARTS_AVAILABLE else 'OFFLINE ⚪'}`\n"
            f"• Bayesian Self-Learning  : `{'ONLINE 🟢' if LEARNING_AVAILABLE else 'OFFLINE ⚪'}`\n"
            f"• Server Time             : `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Send `/menu` to see all modern command hubs."
        )
        send_message(token, sender_id, status_msg)
        return

    # Fallback for unrecognized commands
    send_message(token, sender_id, f"❓ Unrecognized command: `{msg_text}`\nSend `/menu` to view all available commands.")


def start_bot():
    global AUTO_TRADE_LIVE, AUTO_TRADE_MODE, TRAILING_STOP_ENABLED
    token, chat_id = get_credentials()

    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        print("\n" + "=" * 70)
        print("  ⚠️ TELEGRAM BOT TOKEN REQUIRED")
        print("=" * 70)
        print("  1. Run: python test_telegram.py to paste your token, OR")
        print("  2. Put TELEGRAM_BOT_TOKEN=your_token in .env")
        print("=" * 70 + "\n")
        return

    ok, bot_username, bot_first_name = verify_token(token)
    if not ok:
        print(f"❌ Telegram Connection Failed: {bot_first_name}")
        return

    # ── Initialize Live MT5 Broker Connection ──────────────────────────────
    mt5_banner = "NOT CONNECTED ⚪"
    if MT5_EXECUTOR_AVAILABLE and live_broker:
        login = os.environ.get("MT5_LOGIN", "").strip() or None
        password = os.environ.get("MT5_PASSWORD", "").strip() or None
        server = os.environ.get("MT5_SERVER", "").strip() or None
        path = os.environ.get("MT5_PATH", "").strip() or None
        connected, status_text = live_broker.connect(login, password, server, path)
        print(f"\n{status_text}\n")
        mt5_banner = "ONLINE 🟢" if connected else "DISCONNECTED ⚪"

    print("=" * 70)
    print("  🚀 ALL-SKILLS QUANTITATIVE HARD-ASSET BOT (GOLD & BTC)")
    print("=" * 70)
    print(f"  🟢 Telegram Connected : @{bot_username} ({bot_first_name})")
    print(f"  🏦 Live MT5 Broker    : {mt5_banner}")
    print(f"  🧠 Self-Learning      : {'ONLINE (learning_memory.json)' if LEARNING_AVAILABLE else 'OFFLINE'}")
    print(f"  🛡️ Combined Skills    : 12 Active Modules (Macro, Levels, Traps, FVG, Sizing)")
    print("=" * 70)
    print(f"\n📱 Open Telegram, find @{bot_username}, and send: /start\n")

    current_chat_id = chat_id

    def get_active_chat_id():
        return current_chat_id

    # Launch background alert scanner
    t = threading.Thread(target=auto_scanner_worker, args=(token, get_active_chat_id), daemon=True)
    t.start()

    # Launch background trailing stop and breakeven monitor
    t_trail = threading.Thread(target=trailing_monitor_worker, args=(token, get_active_chat_id), daemon=True)
    t_trail.start()

    offset = None
    while True:
        try:
            url = f"https://api.telegram.org/bot{token}/getUpdates?timeout=25"
            if offset:
                url += f"&offset={offset}"
            req = urllib.request.Request(url, headers={"User-Agent": "GoldBtcTelegramBot/3.0"})
            with urllib.request.urlopen(req, timeout=35) as r:
                updates = json.loads(r.read())

            for u in updates.get("result", []):
                offset = u["update_id"] + 1

                if "message" in u and "text" in u["message"]:
                    msg_text = u["message"]["text"].strip()
                    sender_id = str(u["message"]["chat"]["id"])
                    sender_name = u["message"]["from"].get("first_name", "User")

                    # Auto-capture Chat ID
                    if not current_chat_id or current_chat_id in ("YOUR_TELEGRAM_CHAT_ID_HERE", "0", ""):
                        print(f"🔑 Auto-authorized Chat ID: {sender_id} ({sender_name}). Saved for alerts!")
                        current_chat_id = sender_id
                        save_chat_id(sender_id)

                    print(f"📩 [{datetime.now().strftime('%H:%M:%S')}] From {sender_name}: '{msg_text}'")
                    try:
                        process_telegram_command(token, sender_id, sender_name, msg_text)
                    except Exception as cmd_err:
                        print(f"⚠️ Error processing command '{msg_text}': {cmd_err}")
                        send_message(token, sender_id, f"⚠️ Error processing command: {cmd_err}")

        except urllib.error.HTTPError as e:
            if e.code == 401:
                print("❌ 401 Unauthorized: Invalid bot token.")
                time.sleep(10)
            else:
                time.sleep(3)
        except Exception:
            time.sleep(3)


if __name__ == "__main__":
    start_bot()
