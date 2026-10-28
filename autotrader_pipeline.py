#!/usr/bin/env python3
"""
trader-gold-btc: autotrader_pipeline.py
Method 1: The Deterministic Hard-Asset Pipeline Engine for Gold (XAU) & Bitcoin (BTC).

Stages:
  1. Structural Location Scan (Golden Pocket 0.618 Fib, 50/200 SMA)
  2. Microstructure Anti-Trap Filter (Bull/Bear Trap Wick Analysis)
  3. Macro & Momentum Context (DXY, 10Y Yield, RSI, Mayer Multiple, Fear & Greed)
  4. Confluence Scoring (10-Point Veto Matrix) & Exact Order Ticket Generator (Entry, Stop, TP)
"""

import warnings
warnings.filterwarnings("ignore")
import os
os.environ["PYTHONWARNINGS"] = "ignore"
import logging
logging.captureWarnings(True)

import argparse
import json
import time
import urllib.request
from datetime import datetime
import numpy as np

try:
    import yfinance as yf
except ImportError:
    print("❌ yfinance required. Run: pip install yfinance")
    exit(1)


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
    sw_range = sw_high - sw_low

    fib_500 = sw_high - 0.500 * sw_range
    fib_618 = sw_high - 0.618 * sw_range
    fib_650 = sw_high - 0.650 * sw_range

    # In Golden Pocket? (within 2% of 0.618-0.650 zone)
    in_golden_pocket = (curr >= fib_650 * 0.985) and (curr <= fib_618 * 1.02)

    # STAGE 2: MICROSTRUCTURE & TRAP FILTER
    last_bar = hist.iloc[-1]
    o, h, l, c = last_bar["Open"], last_bar["High"], last_bar["Low"], last_bar["Close"]
    tot_rng = h - l if (h - l) > 0 else 1
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l

    trap_state = "CLEAN"
    if h >= sw_high * 0.998 and c < sw_high and (upper_wick / tot_rng) >= 0.40:
        trap_state = "BULL_TRAP"
    elif l <= sw_low * 1.002 and c > sw_low and (lower_wick / tot_rng) >= 0.40:
        trap_state = "BEAR_TRAP_SPRING"

    # STAGE 3: MACRO & MOMENTUM
    rsi = compute_rsi(hist["Close"], 14)
    returns = hist["Close"].pct_change().dropna()
    ann_factor = 365 if asset_type == "BTC" else 252
    vol30 = float(returns.tail(30).std() * np.sqrt(ann_factor) * 100)
    mayer = float(curr / ma200) if not np.isnan(ma200) and ma200 > 0 else 1.0

    # STAGE 4: CONFLUENCE SCORING
    score = 0
    factors = []

    if asset_type == "BTC":
        if dxy_chg < 0.2:
            score += 1
            factors.append("Macro: DXY favorable (USD weakness/neutral)")
        if tnx_chg < 1.0:
            score += 1
            factors.append("Macro: 10Y Yields controlled")
        if curr > ma200:
            score += 1
            factors.append(f"Trend: Above 200 SMA (${ma200:,.0f})")
        if 0.85 <= mayer <= 1.50:
            score += 1
            factors.append(f"Valuation: Mayer Multiple healthy ({mayer:.2f})")
        if 40 <= rsi <= 65:
            score += 1
            factors.append(f"Momentum: RSI in healthy expansion zone ({rsi:.1f})")
        if in_golden_pocket:
            score += 1
            factors.append("Level: Resting in Golden Pocket (0.618 Fib)")
        if 25 <= fg_val <= 70:
            score += 1
            factors.append(f"Sentiment: Fear & Greed balanced ({fg_val})")
        if trap_state != "BULL_TRAP":
            score += 1
            factors.append("Microstructure: Zero Bull Trap rejection")
        if curr > ma50:
            score += 1
            factors.append("Momentum: Above 50 SMA")
        if vol30 < 75:
            score += 1
            factors.append(f"Risk: Volatility normalized ({vol30:.1f}%)")

    else:  # GOLD
        if dxy_chg <= 0.05:
            score += 1
            factors.append("Macro: DXY weakness (Gold tailwind)")
        if tnx_chg <= 0.2:
            score += 1
            factors.append("Macro: 10Y Yields easing (Real yield tailwind)")
        if curr > ma200:
            score += 1
            factors.append(f"Trend: Above 200 SMA (${ma200:,.0f})")
        if curr > ma50:
            score += 1
            factors.append("Trend: Above 50 SMA")
        if 40 <= rsi <= 60:
            score += 1
            factors.append(f"Momentum: RSI pullback sweet spot ({rsi:.1f})")
        if in_golden_pocket:
            score += 1
            factors.append("Level: Resting in Golden Pocket (0.618 Fib)")
        if gsr >= 75:
            score += 1
            factors.append(f"Metals Value: GSR elevated ({gsr:.1f}x)")
        if vol30 < 22:
            score += 1
            factors.append(f"Risk: Orderly volatility ({vol30:.1f}%)")
        if trap_state != "BULL_TRAP":
            score += 1
            factors.append("Microstructure: Clean auction; no Bull Trap")
        if (curr - sw_low) / curr <= 0.05:
            score += 1
            factors.append("Structure: Near major swing support floor")

    # Generate Verdict & Order Ticket
    if score >= 9:
        verdict = "A+ SETUP (EXECUTE ORDER)"
        action = "BUY"
    elif score >= 7:
        verdict = "B SETUP (HALF SIZE)"
        action = "BUY_HALF"
    else:
        verdict = "VETOED (WAIT FOR CONFLUENCE)"
        action = "STAND_ASIDE"

    # Calculate exact Order Parameters with tight Golden Pocket Invalidation
    if in_golden_pocket:
        stop_loss = fib_650 * 0.985  # Tucked tightly just beneath the 0.65 Golden Pocket boundary
        tp1 = fib_500 if curr < fib_500 * 0.98 else sw_high * 0.98
        tp2 = sw_high
    else:
        stop_loss = sw_low * 0.985
        tp1 = fib_500
        tp2 = sw_high

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
        "factors": factors,
        "verdict": verdict,
        "action": action,
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
    print("═" * 78)

    # Global Macro Inputs
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

        print(f"\n{icon} {asset_type} ({sym}) ──► Price: ${res['price']:,.2f}")
        print(f"   • Structural Location : {'✅ INSIDE Golden Pocket ($' + f'{res['golden_pocket'][0]:,.0f} - ${res['golden_pocket'][1]:,.0f})' if res['in_golden_pocket'] else 'Outside Golden Pocket'}")
        print(f"   • Microstructure Trap : {res['trap_state']}")
        print(f"   • Trend & Momentum    : 200 SMA: ${res['ma200']:,.0f} | RSI: {res['rsi']:.1f}" + (f" | Mayer: {res['mayer']:.2f}x" if asset_type == 'BTC' else ""))
        print(f"   • Confluence Score    : {res['score']}/10 ──► {status_color} {res['verdict']}")

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
