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

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import argparse
import json
import time
import urllib.request
import ssl

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
    learning_engine = None

# Import Multi-Strategy Risk Engine for Practical TP/SL
try:
    import risk_engine
    RISK_ENGINE_AVAILABLE = True
except Exception:
    RISK_ENGINE_AVAILABLE = False


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


def analyze_asset_pipeline(symbol: str, asset_type: str, dxy_chg: float, tnx_chg: float, gsr: float, fg_val: int):
    if MARKET_DATA_AVAILABLE and market_data_feed:
        hist = market_data_feed.get_historical_bars(asset_type, period="350d", min_bars=30)
    else:
        t = yf.Ticker(symbol)
        hist = t.history(period="350d")
    if hist.empty or len(hist) < 30:
        return None

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

    # STAGE 4: CONFLUENCE SCORING & ACTIVE FEATURES
    score = 0
    factors = []

    if asset_type == "BTC":
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

        if feat_dxy: score += 1; factors.append("Macro: DXY favorable (USD weakness/neutral)")
        if feat_yield: score += 1; factors.append("Macro: 10Y Yields controlled")
        if feat_ma200: score += 1; factors.append(f"Trend: Above 200 SMA (${ma200:,.0f})")
        if feat_mayer: score += 1; factors.append(f"Valuation: Mayer Multiple healthy ({mayer:.2f})")
        if feat_rsi: score += 1; factors.append(f"Momentum: RSI in healthy expansion zone ({rsi:.1f})")
        if in_golden_pocket: score += 1; factors.append("Level: Resting in Golden Pocket (0.618 Fib)")
        if feat_fg: score += 1; factors.append(f"Sentiment: Fear & Greed balanced ({fg_val})")
        if feat_no_trap: score += 1; factors.append("Microstructure: Zero Bull Trap rejection")
        if feat_ma50: score += 1; factors.append("Momentum: Above 50 SMA")
        if feat_vol: score += 1; factors.append(f"Risk: Volatility normalized ({vol30:.1f}%)")

        active_features = {
            "in_golden_pocket": bool(in_golden_pocket),
            "no_trap": bool(feat_no_trap),
            "macro_dxy_tailwind": bool(feat_dxy),
            "macro_yield_tailwind": bool(feat_yield),
            "trend_ma200": bool(feat_ma200),
            "trend_ma50": bool(feat_ma50),
            "rsi_sweet_spot": bool(feat_rsi),
            "mayer_sweet_spot": bool(feat_mayer),
            "gsr_undervalued": False,
            "volatility_orderly": bool(feat_vol),
            "near_swing_support": bool(feat_near_support)
        }

    else:  # GOLD
        feat_dxy = dxy_chg <= 0.05
        feat_yield = tnx_chg <= 0.2
        feat_ma200 = curr > ma200
        feat_ma50 = curr > ma50
        feat_rsi = 40 <= rsi <= 60
        feat_gsr = gsr >= 75
        feat_vol = vol30 < 22
        feat_no_trap = trap_state != "BULL_TRAP"
        feat_near_support = (curr - sw_low) / curr <= 0.05

        if feat_dxy: score += 1; factors.append("Macro: DXY weakness (Gold tailwind)")
        if feat_yield: score += 1; factors.append("Macro: 10Y Yields easing (Real yield tailwind)")
        if feat_ma200: score += 1; factors.append(f"Trend: Above 200 SMA (${ma200:,.0f})")
        if feat_ma50: score += 1; factors.append("Trend: Above 50 SMA")
        if feat_rsi: score += 1; factors.append(f"Momentum: RSI pullback sweet spot ({rsi:.1f})")
        if in_golden_pocket: score += 1; factors.append("Level: Resting in Golden Pocket (0.618 Fib)")
        if feat_gsr: score += 1; factors.append(f"Metals Value: GSR elevated ({gsr:.1f}x)")
        if feat_vol: score += 1; factors.append(f"Risk: Orderly volatility ({vol30:.1f}%)")
        if feat_no_trap: score += 1; factors.append("Microstructure: Clean auction; no Bull Trap")
        if feat_near_support: score += 1; factors.append("Structure: Near major swing support floor")

        active_features = {
            "in_golden_pocket": bool(in_golden_pocket),
            "no_trap": bool(feat_no_trap),
            "macro_dxy_tailwind": bool(feat_dxy),
            "macro_yield_tailwind": bool(feat_yield),
            "trend_ma200": bool(feat_ma200),
            "trend_ma50": bool(feat_ma50),
            "rsi_sweet_spot": bool(feat_rsi),
            "mayer_sweet_spot": False,
            "gsr_undervalued": bool(feat_gsr),
            "volatility_orderly": bool(feat_vol),
            "near_swing_support": bool(feat_near_support)
        }

    # Adaptive Self-Learned Confluence Score
    if LEARNING_AVAILABLE and learning_engine:
        adaptive_score, breakdown = learning_engine.calculate_score(asset_type, active_features)
    else:
        adaptive_score = float(score)
        breakdown = []

    # Final Execution Verdict (Considers both base score & learned adaptive weights)
    final_score = max(score, int(round(adaptive_score)))
    at_good_level = in_golden_pocket or feat_near_support
    if final_score >= 9:
        verdict = "🟢 A+ SETUP (EXECUTE ORDER)"
        action = "BUY"
    elif final_score >= 8:
        verdict = "🟢 A SETUP (EXECUTE ORDER)"
        action = "BUY"
    elif final_score >= 7:
        if at_good_level:
            verdict = "🟢 SCALP SETUP @ KEY LEVEL (EXECUTE ORDER)"
            action = "BUY"
        else:
            verdict = "🟡 B SETUP (HALF SIZE)"
            action = "BUY_HALF"
    else:
        verdict = "🔴 VETOED (WAIT FOR CONFLUENCE)"
        action = "STAND_ASIDE"

    # Small Practical TP & SL Calculation for Scalp Execution
    if RISK_ENGINE_AVAILABLE:
        strat_calc = risk_engine.calculate_strategy_levels(
            asset_type, curr, atr=vol30, action="BUY", strategy="SCALP",
            levels={"in_golden_pocket": in_golden_pocket, "sw_low": sw_low}
        )
        stop_loss = strat_calc["stop_loss"]
        tp1 = strat_calc["tp1"]
        tp2 = strat_calc["tp2"]
    else:
        sl_dist = 3.80 if asset_type == "GOLD" else 350.0
        stop_loss = round(curr - sl_dist, 2)
        tp1 = round(curr + (sl_dist * 1.25), 2)
        tp2 = round(curr + (sl_dist * 1.85), 2)

    # Log signal to self-learning journal if actionable
    trade_id = None
    if action in ("BUY", "BUY_HALF") and LEARNING_AVAILABLE and learning_engine:
        trade_id = learning_engine.log_signal(
            asset=asset_type,
            symbol=symbol,
            entry=curr,
            sl=stop_loss,
            tp1=tp1,
            tp2=tp2,
            score=adaptive_score,
            active_features=active_features
        )

    return {
        "asset": asset_type,
        "symbol": symbol,
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
        "order_ticket": {
            "entry": curr,
            "stop_loss": stop_loss,
            "tp1": tp1,
            "tp2": tp2,
            "risk_pct": ((curr - stop_loss) / curr) * 100,
            "reward_pct": ((tp1 - curr) / curr) * 100
        }
    }


def run_pipeline():
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
        dxy_chg = (((dxy_val / dxy["Close"].iloc[-2]) - 1) * 100) if len(dxy) >= 2 else 0.0

        tnx_val = tnx["Close"].iloc[-1] if not tnx.empty else 4.0
        tnx_chg = (((tnx_val / tnx["Close"].iloc[-2]) - 1) * 100) if len(tnx) >= 2 else 0.0

        gsr = (gold_5d["Close"].iloc[-1] / silver["Close"].iloc[-1]) if (not gold_5d.empty and not silver.empty) else 80.0
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
        print(f"\n{icon} {asset_type} ({sym}) ──► Price: ${res['price']:,.2f}")
        print(f"   • Structural Location : {loc_str}")
        print(f"   • Microstructure Trap : {res['trap_state']}")
        print(f"   • Trend & Momentum    : 200 SMA: ${res['ma200']:,.0f} | RSI: {res['rsi']:.1f}" + (f" | Mayer: {res['mayer']:.2f}x" if asset_type == 'BTC' else ""))
        print(f"   • Confluence Score    : {res['score']}/10 (Base) | {res['adaptive_score']:.1f}/10 (Learned) ──► {status_color} {res['verdict']}")

        if res['action'] in ("BUY", "BUY_HALF"):
            ot = res['order_ticket']
            rr = (ot['reward_pct'] / ot['risk_pct']) if ot['risk_pct'] > 0 else 1.0
            print(f"""   ┌──────────────────────────────────────────────────────────────┐
   │  📋 ACTIONABLE ORDER TICKET ({res['action']})                       │
   │  • Entry Zone : ${ot['entry']:>10,.2f}                                │
   │  • Stop-Loss  : ${ot['stop_loss']:>10,.2f}  (Risk: -{ot['risk_pct']:.2f}%)               │
   │  • Target 1   : ${ot['tp1']:>10,.2f}  (Reward: +{ot['reward_pct']:.2f}%)            │
   │  • Target 2   : ${ot['tp2']:>10,.2f}                                │
   │  • Risk/Reward: 1:{rr:.2f}                                          │
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
