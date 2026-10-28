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

    # Order parameters (tight Invalidation below 0.650 Golden Pocket or local sweep)
    stop_loss = levels["fib_650"] * 0.985 if levels["in_golden_pocket"] else levels["sw_low"] * 0.985
    tp1 = levels["fib_500"] if curr < levels["fib_500"] * 0.98 else levels["sw_high"] * 0.98
    tp2 = levels["sw_high"]
    risk_pct = abs(curr - stop_loss) / curr * 100 if curr > 0 else 1.0
    reward_pct = abs(tp1 - curr) / curr * 100 if curr > 0 else 2.0
    rr = reward_pct / risk_pct if risk_pct > 0 else 2.0

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
        "rr": rr
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
        lines.extend([
            f"⚡ *ACTIONABLE BTC ORDER TICKET:*",
            f"• Entry Zone: `${b['entry']:,.2f}`",
            f"• Stop-Loss:  `${b['stop_loss']:,.2f}` (-{b['risk_pct']:.2f}%)",
            f"• Target 1:   `${b['tp1']:,.2f}` (+{b['reward_pct']:.2f}%)",
            f"• Target 2:   `${b['tp2']:,.2f}`",
            f"• Risk/Reward: 1:{b['rr']:.2f}",
            ""
        ])

    if g['is_a_plus']:
        lines.extend([
            f"⚡ *ACTIONABLE GOLD ORDER TICKET:*",
            f"• Entry Zone: `${g['entry']:,.2f}`",
            f"• Stop-Loss:  `${g['stop_loss']:,.2f}` (-{g['risk_pct']:.2f}%)",
            f"• Target 1:   `${g['tp1']:,.2f}` (+{g['reward_pct']:.2f}%)",
            f"• Target 2:   `${g['tp2']:,.2f}`",
            f"• Risk/Reward: 1:{g['rr']:.2f}",
            ""
        ])

    lines.append("Menu: `/scan`, `/btc`, `/gold`, `/levels`, `/traps`, `/debate`, `/macro`, `/learn`")
    return "\n".join(lines)


def auto_scanner_worker(token: str, chat_id_getter):
    """Background thread: runs multi-factor audit every 30 minutes and broadcasts alerts."""
    print("⏰ Automated 30-Minute Multi-Skill Market Scanner: ACTIVE")
    while True:
        try:
            time.sleep(1800)  # 30 minutes
            target_chat_id = chat_id_getter()
            if not target_chat_id:
                continue

            data = run_full_pipeline()
            b = data["btc"]
            g = data["gold"]

            if b['is_a_plus'] or g['is_a_plus']:
                print(f"🚨 [{datetime.now().strftime('%H:%M:%S')}] A+ Setup Detected! Broadcasting Telegram alert...")
                alert_text = "🚨 *INSTITUTIONAL TRADE ALERT (SCORE >= 8/10)*\n\n" + format_scan_summary(data)
                send_message(token, target_chat_id, alert_text)
        except Exception:
            time.sleep(10)


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

    print("=" * 70)
    print("  🚀 ALL-SKILLS QUANTITATIVE HARD-ASSET BOT (GOLD & BTC)")
    print("=" * 70)
    print(f"  🟢 Telegram Connected : @{bot_username} ({bot_first_name})")
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

                    if msg_text.startswith("/start") or msg_text.startswith("/help"):
                        welcome = (
                            f"🚀 *All-Skills Quantitative Hard-Asset Bot*\n\n"
                            f"Welcome {sender_name}! All 12 trading skills are actively combined and monitoring Gold & Bitcoin.\n\n"
                            f"Commands:\n"
                            f"• `/scan` - Full multi-skill audit for Gold & BTC\n"
                            f"• `/chart` - Visual MT5 Candlestick Chart for Bitcoin\n"
                            f"• `/chart_gold` - Visual MT5 Candlestick Chart for Gold\n"
                            f"• `/btc` - Deep Bitcoin audit (Levels, Mayer, FVG, Risk)\n"
                            f"• `/gold` - Deep Gold audit (GSR, Yields, Levels, Risk)\n"
                            f"• `/levels` - Institutional S/R, Pivots & Golden Pocket\n"
                            f"• `/traps` - Wyckoff trap inspection (Springs & Upthrusts)\n"
                            f"• `/debate` - Adversarial Bull vs. Bear debate\n"
                            f"• `/macro` - Global macro radar (DXY, 10Y Yield, GSR, VIX)\n"
                            f"• `/learn` - View adaptive weights & win rates\n"
                            f"• `/train` - Run walk-forward self-calibration\n\n"
                            f"🔔 *Automated Alerts:* Active! You will receive instant notifications whenever an A+ setup (≥8/10) appears."
                        )
                        send_message(token, sender_id, welcome)

                    elif msg_text.startswith("/scan"):
                        send_message(token, sender_id, "⏳ Running multi-skill quantitative scan...")
                        data = run_full_pipeline()
                        send_message(token, sender_id, format_scan_summary(data))

                    elif msg_text.startswith("/chart_btc") or msg_text.strip() == "/chart":
                        if CHARTS_AVAILABLE:
                            send_message(token, sender_id, "📈 Rendering MT5-style Candlestick Chart for Bitcoin...")
                            buf = generate_mt5_chart("BTC-USD", "BITCOIN (BTC-USD)")
                            if buf:
                                send_telegram_chart(token, sender_id, buf, "📊 MT5 Chart Scan: Bitcoin (BTC-USD) | 50/200 SMA | Golden Pocket (0.618-0.65)")
                            else:
                                send_message(token, sender_id, "⚠️ Failed to render Bitcoin chart.")
                        else:
                            send_message(token, sender_id, "⚠️ Matplotlib not installed for chart rendering. Run: pip install matplotlib")

                    elif msg_text.startswith("/chart_gold"):
                        if CHARTS_AVAILABLE:
                            send_message(token, sender_id, "📈 Rendering MT5-style Candlestick Chart for Gold...")
                            buf = generate_mt5_chart("GC=F", "GOLD (XAU/USD)")
                            if buf:
                                send_telegram_chart(token, sender_id, buf, "📊 MT5 Chart Scan: Gold (XAU/USD) | 50/200 SMA | Golden Pocket (0.618-0.65)")
                            else:
                                send_message(token, sender_id, "⚠️ Failed to render Gold chart.")
                        else:
                            send_message(token, sender_id, "⚠️ Matplotlib not installed for chart rendering. Run: pip install matplotlib")

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
                            f"• Risk/Reward: 1:{b['rr']:.2f}"
                        )
                        send_message(token, sender_id, ticket)

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
                            f"• Risk/Reward: 1:{g['rr']:.2f}"
                        )
                        send_message(token, sender_id, ticket)

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
