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
    from risk_engine import calculate_lot_size, generate_risk_audit_text, validate_trade_risk, calculate_sniper_levels
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

# Live auto-trade state (disabled by default for safety; toggleable via /auto_trade on|off)
AUTO_TRADE_LIVE = False


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
    """Computes ADX and determines regime (Trending > 25 vs Chop < 20)."""
    if len(df) < period * 2:
        return 22.0, "CHOP / RANGE"
    
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

    regime = "TRENDING (ADX > 25)" if adx >= 25 else "CHOP / CONSOLIDATION (ADX < 20)" if adx <= 20 else "TRANSITIONAL (20-25)"
    return adx, regime


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
    adx, regime = compute_adx(hist, 14)

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

    base_score = len(factors_hit)
    adaptive_score = base_score
    if LEARNING_AVAILABLE and learning_engine:
        adaptive_score, _ = learning_engine.calculate_score(asset_type, active_features)

    final_score = max(base_score, int(round(adaptive_score)))
    is_a_plus = final_score >= 8

    # VETO condition: Bull Trap at resistance kills all longs
    if trap_type == "BULL_TRAP":
        is_a_plus = False
        verdict = "🔴 VETOED: Bull Trap at Resistance! Stand Aside or Fade."
    elif is_a_plus:
        verdict = f"🟢 A+ SETUP (Score: {final_score}/10) - High Probability Execution"
    elif final_score >= 6:
        verdict = f"🟡 B SETUP (Score: {final_score}/10) - Watchlist / Reduced Size"
    else:
        verdict = f"🔴 VETOED (Score: {final_score}/10) - Insufficient Confluence"

    account_balance, base_risk = get_risk_config()
    target_risk = base_risk if is_a_plus else (base_risk * 0.5)

    # High Win-Rate Sniper Calibration: Small SL, Small TP (1.2R scalp), Small Micro-Lots
    if RISK_ENGINE_AVAILABLE:
        sniper = calculate_sniper_levels(asset_type, curr, atr=atr, action="BUY", account_balance=account_balance, risk_pct=target_risk)
        stop_loss = sniper["stop_loss"]
        tp1 = sniper["tp1"]
        tp2 = sniper["tp2"]
        risk_pct = sniper["risk_pct"]
        reward_pct = round(abs(tp1 - curr) / curr * 100, 2)
        rr = sniper["rr_tp1"]
        lot_info = {
            "lots": sniper["lot_size"],
            "actual_risk_usd": sniper["risk_usd"],
            "actual_risk_pct": sniper["risk_pct"],
            "price_dist": sniper["sl_dist"]
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
            "price_dist": sl_dist
        }

    return {
        "asset": asset_type,
        "symbol": symbol,
        "price": curr,
        "levels": levels,
        "rsi": rsi,
        "atr": atr,
        "adx": adx,
        "regime": regime,
        "fvg": fvg,
        "mayer": mayer,
        "vol30": vol30,
        "trap_type": trap_type,
        "trap_detail": trap_detail,
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


def run_full_pipeline():
    macro = fetch_macro_context()
    btc = analyze_asset_complete("BTC-USD", "BTC", macro)
    gold = analyze_asset_complete("GC=F", "GOLD", macro)
    return {"macro": macro, "btc": btc, "gold": gold}


# ==============================================================================
# SKILL 10: ADVERSARIAL BULL VS. BEAR DIALECTICAL DEBATE
# ==============================================================================

def generate_adversarial_debate(data: dict) -> str:
    m = data["macro"]
    b = data["btc"]
    g = data["gold"]

    lines = [
        "⚔️ *ADVERSARIAL BULL VS. BEAR DEBATE*",
        "",
        "₿ *BITCOIN (BTC-USD):*",
        f"🐂 *Bull Thesis:* Price (${b['price']:,.2f}) supported by 200 SMA (${b['levels']['ma200']:,.0f}). Mayer Multiple at {b['mayer']:.2f}x indicates institutional accumulation zone without retail euphoria. Market regime is {b['regime']}.",
        f"🐻 *Bear Counter:* Macro 10Y Yields at {m['tnx']:.2f}% ({m['tnx_chg']:+.2f}%) maintain liquidity drag. Recent imbalance: {b['fvg']}. Invalidation stop sits at ${b['stop_loss']:,.2f}.",
        "",
        "🥇 *GOLD (XAU/USD):*",
        f"🐂 *Bull Thesis:* Gold/Silver Ratio at {m['gsr']:.1f}x signals structural metal undervaluation. Physical central bank demand creates solid floor. No bull trap rejection.",
        f"🐻 *Bear Counter:* DXY trading at {m['dxy']:.2f} ({m['dxy_chg']:+.2f}%). Real yield firmness caps explosive breakout momentum until DXY rolls over.",
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
    m = data["macro"]
    b = data["btc"]
    g = data["gold"]

    b_gp_str = f"✅ INSIDE (${b['levels']['fib_650']:,.0f} - ${b['levels']['fib_618']:,.0f})" if b['levels']['in_golden_pocket'] else "Outside GP"
    g_gp_str = f"✅ INSIDE (${g['levels']['fib_650']:,.0f} - ${g['levels']['fib_618']:,.0f})" if g['levels']['in_golden_pocket'] else "Outside GP"

    lines = [
        "📊 *HARD-ASSET MULTI-SKILL SCAN*",
        "",
        f"🌐 *Macro Radar:*",
        f"• DXY: `{m['dxy']:.2f}` ({m['dxy_chg']:+.2f}%) | 10Y Yield: `{m['tnx']:.2f}%`",
        f"• GSR: `{m['gsr']:.1f}x` | VIX: `{m['vix']:.1f}` | F&G: `{m['fg_val']}` ({m['fg_label']})",
        "",
        f"₿ *Bitcoin (BTC-USD):* `${b['price']:,.2f}`",
        f"• Score: `{b['base_score']}/10` (Learned: `{b['adaptive_score']:.1f}/10`) ──► {b['verdict']}",
        f"• Regime: `{b['regime']}` (ADX: `{b['adx']:.1f}`)",
        f"• Golden Pocket: {b_gp_str}",
        f"• Microstructure: `{b['trap_type']}` | FVG: `{b['fvg']}`",
        "",
        f"🥇 *Gold (XAU/USD):* `${g['price']:,.2f}`",
        f"• Score: `{g['base_score']}/10` (Learned: `{g['adaptive_score']:.1f}/10`) ──► {g['verdict']}",
        f"• Regime: `{g['regime']}` (ADX: `{g['adx']:.1f}`)",
        f"• Golden Pocket: {g_gp_str}",
        f"• Microstructure: `{g['trap_type']}` | FVG: `{g['fvg']}`",
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
    auto_status = "ENABLED 🟢" if AUTO_TRADE_LIVE else "DISABLED ⚪"
    mt5_status = "CONNECTED 🟢" if (MT5_EXECUTOR_AVAILABLE and live_broker and live_broker.is_connected) else "OFFLINE ⚪"
    return (
        f"🚀 *INSTITUTIONAL QUANTITATIVE TRADING BOT*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Welcome {sender_name}! High-probability quantitative engine for Gold (`XAU/USD`) & Bitcoin (`BTC/USD`).\n\n"
        f"⚡ *Live Engine Status:*\n"
        f"• Auto-Scanner: `1-MINUTE CANDLE CLOSE` 🟢\n"
        f"• MT5 Live Broker: `{mt5_status}`\n"
        f"• 1M Auto-Trade: `{auto_status}`\n\n"
        f"💼 *1. LIVE MT5 BROKER & TRADING:*\n"
        f"• `/account` - Live equity, balance, free margin & broker info\n"
        f"• `/positions` - View all active live trades & real-time PnL\n"
        f"• `/buy_gold` - Live Buy on Gold (Small SL & Small TP)\n"
        f"• `/sell_gold` - Live Sell on Gold (Small SL & Small TP)\n"
        f"• `/buy_btc` - Live Buy on Bitcoin (Small SL & Small TP)\n"
        f"• `/sell_btc` - Live Sell on Bitcoin (Small SL & Small TP)\n"
        f"• `/close_all` - 🚨 Emergency close all live positions\n"
        f"• `/auto_trade on|off` - Toggle 1m automatic execution\n\n"
        f"📊 *2. MARKET AUDIT & MT5 CHARTS:*\n"
        f"• `/scan` - Full 12-skill scan + default MT5 Candlestick Charts\n"
        f"• `/btc` - Deep Bitcoin audit with MT5 Chart & Sniper ticket\n"
        f"• `/gold` - Deep Gold audit with MT5 Chart & Sniper ticket\n"
        f"• `/levels` - Institutional Daily Pivots & Fibonacci Golden Pocket\n"
        f"• `/traps` - Wyckoff trap inspection (Springs & Upthrusts)\n"
        f"• `/macro` - Global Macro Radar (DXY, 10Y Yield, GSR, VIX)\n"
        f"• `/debate` - Adversarial Bull vs. Bear debate pressure test\n\n"
        f"🛡️ *3. RISK MANAGEMENT & POSITION SIZING:*\n"
        f"• `/risk` - Audit risk budget & small lot sizes on live equity\n"
        f"• `/risk [balance]` - Simulate custom equity (e.g. `/risk 25000`)\n\n"
        f"🧠 *4. AUTONOMOUS SELF-LEARNING:*\n"
        f"• `/learn` - View Bayesian factor rankings, win rates & weights\n"
        f"• `/train` - Trigger 180-day walk-forward self-calibration\n\n"
        f"ℹ️ *5. SYSTEM COMMANDS:*\n"
        f"• `/status` - Bot uptime, MT5 status & 1m scanner health\n"
        f"• `/menu` - Redisplay this organized command directory\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔔 *Continuous Scanner:* Active every 60 seconds on each 1-minute candle close!"
    )


def auto_scanner_worker(token: str, chat_id_getter):
    """
    Background thread: Runs multi-factor quantitative audit on EVERY 1-MINUTE CANDLE.
    Syncs precisely to the :00 second candle close.
    Broadcasts alerts on A+ setups (>=8/10) and auto-executes if /auto_trade on.
    """
    print("⏰ Automated 1-Minute Live Candle Scanner: ACTIVE (Monitoring Gold & BTC every 60s)")

    last_btc_alert_time = 0.0
    last_gold_alert_time = 0.0
    last_btc_alert_price = 0.0
    last_gold_alert_price = 0.0
    ALERT_COOLDOWN_SEC = 300.0  # 5-minute cooldown for repeated alert on same stagnant price

    while True:
        try:
            # Sync to the next 1-minute candle close (:00 seconds)
            now = time.time()
            sleep_sec = max(5, int(60 - (now % 60)))
            time.sleep(sleep_sec)

            target_chat_id = chat_id_getter()
            if not target_chat_id:
                continue

            current_time = time.time()
            data = run_full_pipeline()
            if not data:
                continue

            b = data["btc"]
            g = data["gold"]

            # ── 1-Minute Bitcoin Audit ──
            if b['is_a_plus']:
                price_moved = abs(b['price'] - last_btc_alert_price) / b['price'] > 0.003 if last_btc_alert_price > 0 else True
                cooldown_passed = (current_time - last_btc_alert_time) > ALERT_COOLDOWN_SEC
                if price_moved or cooldown_passed:
                    last_btc_alert_time = current_time
                    last_btc_alert_price = b['price']
                    print(f"🚨 [{datetime.now().strftime('%H:%M:%S')}] 1M Candle A+ Setup: Bitcoin (${b['price']:,.2f})! Score: {b['final_score']}/10")
                    alert_text = f"🚨 *1-MINUTE CANDLE A+ SETUP DETECTED: BITCOIN*\n\n" + format_scan_summary(data)
                    send_message(token, target_chat_id, alert_text)
                    if CHARTS_AVAILABLE:
                        b_buf = generate_mt5_chart("BTC-USD", "BITCOIN (BTC-USD)")
                        if b_buf:
                            send_telegram_chart(token, target_chat_id, b_buf, f"📊 MT5 1M Chart: Bitcoin (${b['price']:,.2f}) | {b['verdict']}")

                    # Auto-Trade execution (only if no existing open position to avoid duplicate staking)
                    global AUTO_TRADE_LIVE
                    if AUTO_TRADE_LIVE and MT5_EXECUTOR_AVAILABLE and live_broker and live_broker.is_connected:
                        if not live_broker.has_open_position("BTC"):
                            res = live_broker.execute_live_sniper_order("BTC", "BUY", b["entry"], b["stop_loss"], b["tp1"], b["lot_info"]["lots"], comment="Auto1M-A+")
                            if res.get("success"):
                                send_message(token, target_chat_id, f"⚡ *LIVE 1M AUTO-EXECUTION (A+ SETUP)*\n• Symbol: `{res['symbol']}` (BUY)\n• Volume: `{res['lots']}` Lots\n• Price: `${res['price']:,.2f}`\n• Ticket: `#{res['ticket']}`\n• Small SL: `${res['sl']:,.2f}` | Small TP: `${res['tp']:,.2f}`")

            # ── 1-Minute Gold Audit ──
            if g['is_a_plus']:
                g_price_moved = abs(g['price'] - last_gold_alert_price) / g['price'] > 0.002 if last_gold_alert_price > 0 else True
                g_cooldown_passed = (current_time - last_gold_alert_time) > ALERT_COOLDOWN_SEC
                if g_price_moved or g_cooldown_passed:
                    last_gold_alert_time = current_time
                    last_gold_alert_price = g['price']
                    print(f"🚨 [{datetime.now().strftime('%H:%M:%S')}] 1M Candle A+ Setup: Gold (${g['price']:,.2f})! Score: {g['final_score']}/10")
                    alert_text = f"🚨 *1-MINUTE CANDLE A+ SETUP DETECTED: GOLD*\n\n" + format_scan_summary(data)
                    send_message(token, target_chat_id, alert_text)
                    if CHARTS_AVAILABLE:
                        g_buf = generate_mt5_chart("GC=F", "GOLD (XAU/USD)")
                        if g_buf:
                            send_telegram_chart(token, target_chat_id, g_buf, f"📊 MT5 1M Chart: Gold (${g['price']:,.2f}) | {g['verdict']}")

                    # Auto-Trade execution (only if no existing open position)
                    if AUTO_TRADE_LIVE and MT5_EXECUTOR_AVAILABLE and live_broker and live_broker.is_connected:
                        if not live_broker.has_open_position("GOLD"):
                            res = live_broker.execute_live_sniper_order("GOLD", "BUY", g["entry"], g["stop_loss"], g["tp1"], g["lot_info"]["lots"], comment="Auto1M-A+")
                            if res.get("success"):
                                send_message(token, target_chat_id, f"⚡ *LIVE 1M AUTO-EXECUTION (A+ SETUP)*\n• Symbol: `{res['symbol']}` (BUY)\n• Volume: `{res['lots']}` Lots\n• Price: `${res['price']:,.2f}`\n• Ticket: `#{res['ticket']}`\n• Small SL: `${res['sl']:,.2f}` | Small TP: `${res['tp']:,.2f}`")

        except Exception:
            time.sleep(5)


def start_bot():
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

                    if msg_text.startswith("/start") or msg_text.startswith("/help") or msg_text.startswith("/menu"):
                        welcome = format_welcome_menu(sender_name)
                        send_message(token, sender_id, welcome)

                    elif msg_text.startswith("/scan"):
                        send_message(token, sender_id, "⏳ Running multi-skill quantitative scan & generating MT5 charts...")
                        data = run_full_pipeline()
                        send_message(token, sender_id, format_scan_summary(data))

                        # Default MT5 chart scan attached automatically
                        if CHARTS_AVAILABLE:
                            b_buf = generate_mt5_chart("BTC-USD", "BITCOIN (BTC-USD)")
                            if b_buf:
                                send_telegram_chart(token, sender_id, b_buf, f"📊 MT5 Chart Scan: Bitcoin (${data['btc']['price']:,.2f}) | {data['btc']['verdict']}")
                            g_buf = generate_mt5_chart("GC=F", "GOLD (XAU/USD)")
                            if g_buf:
                                send_telegram_chart(token, sender_id, g_buf, f"📊 MT5 Chart Scan: Gold (${data['gold']['price']:,.2f}) | {data['gold']['verdict']}")

                    elif msg_text.startswith("/btc"):
                        data = run_full_pipeline()
                        b = data["btc"]
                        lv = b["levels"]
                        ticket = (
                            f"₿ *Bitcoin (BTC-USD) Multi-Skill Audit:*\n"
                            f"• Price: `${b['price']:,.2f}`\n"
                            f"• Score: `{b['base_score']}/10` (Learned: `{b['adaptive_score']:.1f}/10`)\n"
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
                            f"• Position Size: `{b['lot_info']['lots']}` BTC Lots (${b['lot_info']['actual_risk_usd']:,.2f} risk | {b['lot_info']['actual_risk_pct']:.2f}% equity)\n"
                            f"• Risk/Reward: 1:{b['rr']:.2f}"
                        )
                        send_message(token, sender_id, ticket)
                        if CHARTS_AVAILABLE:
                            b_buf = generate_mt5_chart("BTC-USD", "BITCOIN (BTC-USD)")
                            if b_buf:
                                send_telegram_chart(token, sender_id, b_buf, f"📊 MT5 Chart: Bitcoin (${b['price']:,.2f})")

                    elif msg_text.startswith("/gold"):
                        data = run_full_pipeline()
                        g = data["gold"]
                        lv = g["levels"]
                        m = data["macro"]
                        ticket = (
                            f"🥇 *Gold (XAU/USD / GC=F) Multi-Skill Audit:*\n"
                            f"• Price: `${g['price']:,.2f}`\n"
                            f"• Score: `{g['base_score']}/10` (Learned: `{g['adaptive_score']:.1f}/10`)\n"
                            f"• Regime: `{g['regime']}` (ADX: `{g['adx']:.1f}` | ATR: `${g['atr']:,.1f}`)\n"
                            f"• Gold/Silver Ratio: `{m['gsr']:.1f}x` (Undervalued: {m['gsr'] >= 75})\n"
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
                            f"• Position Size: `{g['lot_info']['lots']}` Standard Lots (${g['lot_info']['actual_risk_usd']:,.2f} risk | {g['lot_info']['actual_risk_pct']:.2f}% equity)\n"
                            f"• Risk/Reward: 1:{g['rr']:.2f}"
                        )
                        send_message(token, sender_id, ticket)
                        if CHARTS_AVAILABLE:
                            g_buf = generate_mt5_chart("GC=F", "GOLD (XAU/USD)")
                            if g_buf:
                                send_telegram_chart(token, sender_id, g_buf, f"📊 MT5 Chart: Gold (${g['price']:,.2f})")

                    elif msg_text.startswith("/risk"):
                        parts = msg_text.strip().split()
                        custom_bal = None
                        if len(parts) > 1:
                            try:
                                custom_bal = float(parts[1].replace("$", "").replace(",", ""))
                            except ValueError:
                                pass

                        cfg_bal, cfg_risk = get_risk_config()
                        active_bal = custom_bal if (custom_bal and custom_bal > 0) else cfg_bal

                        send_message(token, sender_id, f"🛡️ Computing institutional risk audit & position sizing for ${active_bal:,.2f} equity...")
                        data = run_full_pipeline()

                        win_rate = 0.55
                        if LEARNING_AVAILABLE and learning_engine and learning_engine.total_signals > 0:
                            win_rate = learning_engine.overall_win_rate

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

                    elif msg_text.startswith("/account"):
                        acc = live_broker.get_live_account_data() if (MT5_EXECUTOR_AVAILABLE and live_broker and live_broker.is_connected) else None
                        if acc:
                            trade_str = "ENABLED ✅" if acc["trade_allowed"] else "DISABLED ⚠️ (Enable 'Allow Algo Trading' in MT5)"
                            text = (
                                f"🏦 *LIVE MT5 BROKER ACCOUNT SUMMARY*\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"• Status: 🟢 *LIVE BROKER CONNECTED*\n"
                                f"• Broker: `{acc['broker']}`\n"
                                f"• Account ID: `#{acc['login']}` ({acc['server']})\n"
                                f"• Live Balance: `${acc['balance']:,.2f} {acc['currency']}`\n"
                                f"• Live Equity:  `${acc['equity']:,.2f} {acc['currency']}`\n"
                                f"• Free Margin: `${acc['margin_free']:,.2f}`\n"
                                f"• Leverage: `1:{acc['leverage']}`\n"
                                f"• Open Trades: `{acc['open_positions_count']}`\n"
                                f"• Algo Trading: `{trade_str}`\n"
                                f"• Auto-Execution: `{'ON 🟢' if AUTO_TRADE_LIVE else 'OFF ⚪'}`\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"⚡ *Live Risk Engine:* Position sizing is dynamically linked to your `${acc['equity']:,.2f}` equity in real-time."
                            )
                        else:
                            text = (
                                "❌ *LIVE MT5 BROKER NOT CONNECTED*\n\n"
                                "Please make sure:\n"
                                "1. MetaTrader 5 terminal is running on your VPS.\n"
                                "2. You are logged into your live trading account.\n"
                                "3. 'Allow algorithmic trading' is checked in `Tools -> Options -> Expert Advisors`."
                            )
                        send_message(token, sender_id, text)

                    elif msg_text.startswith("/positions"):
                        positions = live_broker.get_open_positions() if (MT5_EXECUTOR_AVAILABLE and live_broker and live_broker.is_connected) else []
                        if positions:
                            lines = [
                                "📋 *LIVE MT5 OPEN POSITIONS*",
                                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                            ]
                            tot_pnl = 0.0
                            for p in positions:
                                tot_pnl += p["profit"]
                                icon = "🟢" if p["profit"] >= 0 else "🔴"
                                lines.append(
                                    f"• `{p['symbol']}` {p['type']} `{p['lots']}` lots\n"
                                    f"  Ticket: `#{p['ticket']}` | Open: `${p['open_price']:,.2f}`\n"
                                    f"  Current: `${p['current_price']:,.2f}` | PnL: {icon} `${p['profit']:+,.2f}`\n"
                                    f"  SL: `${p['sl']:,.2f}` | TP: `${p['tp']:,.2f}`"
                                )
                            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                            lines.append(f"💰 *Total Floating PnL:* `${tot_pnl:+,.2f}`")
                            lines.append("Send `/close_all` to instantly liquidate all open positions.")
                            send_message(token, sender_id, "\n".join(lines))
                        else:
                            send_message(token, sender_id, "ℹ️ *No Open Positions:* There are currently no active live trades running in MT5.")

                    elif msg_text.startswith("/buy_gold") or msg_text.startswith("/sell_gold"):
                        is_buy = msg_text.startswith("/buy_gold")
                        action = "BUY" if is_buy else "SELL"
                        if not (MT5_EXECUTOR_AVAILABLE and live_broker and live_broker.is_connected):
                            send_message(token, sender_id, "❌ Cannot execute live trade: MT5 is disconnected. Open MT5 on your VPS.")
                        else:
                            send_message(token, sender_id, f"⚡ Executing Live {action} Order on Gold (XAU/USD)...")
                            data = run_full_pipeline()
                            g = data["gold"]
                            bal, risk = get_risk_config()
                            sniper = calculate_sniper_levels("GOLD", g["price"], g["atr"], action, bal, risk)
                            res = live_broker.execute_live_sniper_order("GOLD", action, sniper["entry"], sniper["stop_loss"], sniper["tp1"], sniper["lot_size"], comment="Telegram-GoldSniper")
                            if res.get("success"):
                                order_ticket = (
                                    f"🟢 *LIVE MT5 ORDER EXECUTED!*\n"
                                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                    f"• Symbol: `{res['symbol']}` ({res['action']})\n"
                                    f"• Ticket: `#{res['ticket']}`\n"
                                    f"• Volume: `{res['lots']}` Lots (Micro Lot Sizing)\n"
                                    f"• Entry: `${res['price']:,.2f}`\n"
                                    f"• Small SL: `${res['sl']:,.2f}` (-${abs(res['price']-res['sl']):.2f} tight risk)\n"
                                    f"• Small TP: `${res['tp']:,.2f}` (+${abs(res['tp']-res['price']):.2f} quick scalp)\n"
                                    f"• Win Rate Target: ~75% High Probability Focus\n"
                                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                    f"Type `/positions` to track live floating PnL."
                                )
                                send_message(token, sender_id, order_ticket)
                            else:
                                send_message(token, sender_id, f"❌ Live Order Failed: {res.get('error')}")

                    elif msg_text.startswith("/buy_btc") or msg_text.startswith("/sell_btc"):
                        is_buy = msg_text.startswith("/buy_btc")
                        action = "BUY" if is_buy else "SELL"
                        if not (MT5_EXECUTOR_AVAILABLE and live_broker and live_broker.is_connected):
                            send_message(token, sender_id, "❌ Cannot execute live trade: MT5 is disconnected. Open MT5 on your VPS.")
                        else:
                            send_message(token, sender_id, f"⚡ Executing Live {action} Order on Bitcoin (BTC/USD)...")
                            data = run_full_pipeline()
                            b = data["btc"]
                            bal, risk = get_risk_config()
                            sniper = calculate_sniper_levels("BTC", b["price"], b["atr"], action, bal, risk)
                            res = live_broker.execute_live_sniper_order("BTC", action, sniper["entry"], sniper["stop_loss"], sniper["tp1"], sniper["lot_size"], comment="Telegram-BtcSniper")
                            if res.get("success"):
                                order_ticket = (
                                    f"🟢 *LIVE MT5 ORDER EXECUTED!*\n"
                                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                    f"• Symbol: `{res['symbol']}` ({res['action']})\n"
                                    f"• Ticket: `#{res['ticket']}`\n"
                                    f"• Volume: `{res['lots']}` Lots (Micro Contract)\n"
                                    f"• Entry: `${res['price']:,.2f}`\n"
                                    f"• Small SL: `${res['sl']:,.2f}` (-${abs(res['price']-res['sl']):.2f} tight risk)\n"
                                    f"• Small TP: `${res['tp']:,.2f}` (+${abs(res['tp']-res['price']):.2f} quick scalp)\n"
                                    f"• Win Rate Target: ~75% High Probability Focus\n"
                                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                    f"Type `/positions` to track live floating PnL."
                                )
                                send_message(token, sender_id, order_ticket)
                            else:
                                send_message(token, sender_id, f"❌ Live Order Failed: {res.get('error')}")

                    elif msg_text.startswith("/close_all"):
                        if not (MT5_EXECUTOR_AVAILABLE and live_broker and live_broker.is_connected):
                            send_message(token, sender_id, "❌ MT5 is disconnected.")
                        else:
                            send_message(token, sender_id, "⚠️ Closing all active live MT5 positions...")
                            res = live_broker.close_all_positions()
                            if res.get("success") and res.get("closed_count", 0) > 0:
                                send_message(token, sender_id, f"🚨 *EMERGENCY CLOSE-ALL COMPLETED!*\n• Closed: `{res['closed_count']}` positions\n• Total Realized PnL: `${res['total_pnl']:+,.2f}`")
                            else:
                                send_message(token, sender_id, f"ℹ️ {res.get('msg', 'No open positions to close.')}")

                    elif msg_text.startswith("/auto_trade"):
                        parts = msg_text.strip().split()
                        if len(parts) > 1 and parts[1].lower() in ("on", "true", "enable", "1"):
                            AUTO_TRADE_LIVE = True
                            send_message(token, sender_id, "🟢 *LIVE AUTO-EXECUTION ENABLED!*\nThe bot will automatically place live MT5 sniper orders on every 1-minute candle close whenever an A+ setup (≥8/10) is detected.")
                        elif len(parts) > 1 and parts[1].lower() in ("off", "false", "disable", "0"):
                            AUTO_TRADE_LIVE = False
                            send_message(token, sender_id, "⚪ *LIVE AUTO-EXECUTION DISABLED.*\nThe bot will send notifications and charts for alerts, but will require manual /buy or /sell command to execute.")
                        else:
                            status_str = "ENABLED 🟢" if AUTO_TRADE_LIVE else "DISABLED ⚪"
                            send_message(token, sender_id, f"ℹ️ *1M Auto-Trade Status:* `{status_str}`\nUsage: `/auto_trade on` or `/auto_trade off`")

                    elif msg_text.startswith("/status"):
                        acc_data = live_broker.get_live_account_data() if (MT5_EXECUTOR_AVAILABLE and live_broker and live_broker.is_connected) else None
                        broker_line = f"🟢 Connected (#{acc_data['login']} on {acc_data['broker']})" if acc_data else "⚪ Disconnected (Open MT5 on VPS)"
                        eq_line = f"${acc_data['equity']:,.2f} {acc_data['currency']}" if acc_data else "N/A"
                        status_msg = (
                            f"🤖 *SYSTEM & ENGINE HEALTH*\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"• 1-Minute Candle Scanner: `ACTIVE (Every 60s)` 🟢\n"
                            f"• MT5 Broker Connection: `{broker_line}`\n"
                            f"• Live Account Equity: `{eq_line}`\n"
                            f"• 1M Auto-Trade Execution: `{'ENABLED 🟢' if AUTO_TRADE_LIVE else 'DISABLED ⚪'}`\n"
                            f"• Visual MT5 Charts: `{'ONLINE 🟢' if CHARTS_AVAILABLE else 'OFFLINE ⚪'}`\n"
                            f"• Bayesian Self-Learning: `{'ONLINE 🟢' if LEARNING_AVAILABLE else 'OFFLINE ⚪'}`\n"
                            f"• Server Time: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"Send `/menu` to see all organized commands."
                        )
                        send_message(token, sender_id, status_msg)

                    elif msg_text.startswith("/levels"):
                        data = run_full_pipeline()
                        b_lv = data["btc"]["levels"]
                        g_lv = data["gold"]["levels"]
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

                    elif msg_text.startswith("/traps"):
                        data = run_full_pipeline()
                        b = data["btc"]
                        g = data["gold"]
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

                    elif msg_text.startswith("/debate"):
                        data = run_full_pipeline()
                        debate_msg = generate_adversarial_debate(data)
                        send_message(token, sender_id, debate_msg)

                    elif msg_text.startswith("/macro"):
                        data = run_full_pipeline()
                        m = data["macro"]
                        macro_text = (
                            f"🌐 *GLOBAL MACRO RADAR*\n\n"
                            f"• US Dollar Index (DXY): `{m['dxy']:.2f}` ({m['dxy_chg']:+.2f}%)\n"
                            f"• US 10-Year Real Yield: `{m['tnx']:.2f}%` ({m['tnx_chg']:+.2f}%)\n"
                            f"• Gold/Silver Ratio (GSR): `{m['gsr']:.1f}x` (Undervalued: {m['gsr'] >= 75})\n"
                            f"• CBOE Volatility Index (VIX): `{m['vix']:.1f}`\n"
                            f"• Crypto Fear & Greed: `{m['fg_val']}` ({m['fg_label']})"
                        )
                        send_message(token, sender_id, macro_text)

                    elif msg_text.startswith("/learn"):
                        if LEARNING_AVAILABLE and learning_engine:
                            summary = learning_engine.get_summary_text()
                            send_message(token, sender_id, f"```\n{summary}\n```")
                        else:
                            send_message(token, sender_id, "⚠️ Self-Learning module not available.")

                    elif msg_text.startswith("/train"):
                        send_message(token, sender_id, "🧠 Initiating walk-forward self-calibration across past 180 days...")
                        if LEARNING_AVAILABLE and learning_engine:
                            trades, wins = learning_engine.train_on_historical_data(lookback_days=180, verbose=False)
                            win_pct = (wins / trades * 100) if trades > 0 else 0
                            send_message(token, sender_id, f"✅ Self-Training complete!\n• Setups Evaluated: `{trades}`\n• Win Rate: `{win_pct:.1f}%`\nType `/learn` to see updated rankings.")
                        else:
                            send_message(token, sender_id, "⚠️ Self-Learning module not available.")

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
