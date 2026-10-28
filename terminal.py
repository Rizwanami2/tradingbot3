#!/usr/bin/env python3
"""
trader-gold-btc: terminal.py (High-Accuracy Quantitative Edition)
The Unified Institutional Intelligence Terminal for Gold (XAU) & Bitcoin (BTC).
Features live multi-factor confluence scoring, Mayer Multiple, Gold/Silver Ratio (GSR),
RSI momentum, Real Yield proxies, and Wyckoff liquidity sweep detection.
"""

import warnings
warnings.filterwarnings("ignore")
import logging
logging.captureWarnings(True)
import os
os.environ["PYTHONWARNINGS"] = "ignore"
import urllib.request
import json
import numpy as np

try:
    import yfinance as yf
except ImportError:
    print("❌ yfinance required. Run: pip install yfinance")
    exit(1)


def compute_rsi(series, period: int = 14) -> float:
    if len(series) < period + 1:
        return float("nan")
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
        return 50, "Neutral (Default)"


def get_asset_stats(ticker_symbol: str, period: str = "350d"):
    t = yf.Ticker(ticker_symbol)
    hist = t.history(period=period)
    if hist.empty or len(hist) < 20:
        return None

    curr = hist["Close"].iloc[-1]
    p_1d = hist["Close"].iloc[-2] if len(hist) >= 2 else curr
    p_7d = hist["Close"].iloc[-6] if len(hist) >= 6 else curr
    p_30d = hist["Close"].iloc[-22] if len(hist) >= 22 else curr

    chg_1d = ((curr / p_1d) - 1) * 100
    chg_7d = ((curr / p_7d) - 1) * 100
    chg_30d = ((curr / p_30d) - 1) * 100

    ma50 = hist["Close"].rolling(50).mean().iloc[-1] if len(hist) >= 50 else np.nan
    ma200 = hist["Close"].rolling(200).mean().iloc[-1] if len(hist) >= 200 else np.nan

    # Mayer Multiple (Price / 200 SMA)
    mayer_multiple = (curr / ma200) if not np.isnan(ma200) and ma200 > 0 else np.nan

    # RSI
    rsi14 = compute_rsi(hist["Close"], 14)

    # 30-day Annualized Realized Volatility
    returns = hist["Close"].pct_change().dropna()
    realized_vol = (returns.tail(30).std() * np.sqrt(365 if "BTC" in ticker_symbol else 252)) * 100

    # 60-day swing & Fibs
    recent = hist.tail(60)
    sw_high = recent["High"].max()
    sw_low = recent["Low"].min()
    rng = sw_high - sw_low

    fib_618 = sw_high - 0.618 * rng
    fib_650 = sw_high - 0.650 * rng
    fib_500 = sw_high - 0.500 * rng

    # Liquidity Sweep / Trap check (Last bar)
    last_bar = hist.iloc[-1]
    o, h, l, c = last_bar["Open"], last_bar["High"], last_bar["Low"], last_bar["Close"]
    tot_rng = h - l if (h - l) > 0 else 1
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l

    trap_status = "Clean (No Active Trap)"
    if h >= sw_high * 0.998 and c < sw_high and (upper_wick / tot_rng) >= 0.40:
        trap_status = "⚠️ BULL TRAP / UPTHRUST (Wick Rejection)"
    elif l <= sw_low * 1.002 and c > sw_low and (lower_wick / tot_rng) >= 0.40:
        trap_status = "🟢 BEAR TRAP / SPRING (Support Absorption)"

    return {
        "current": curr,
        "chg_1d": chg_1d,
        "chg_7d": chg_7d,
        "chg_30d": chg_30d,
        "ma50": ma50,
        "ma200": ma200,
        "mayer": mayer_multiple,
        "rsi": rsi14,
        "vol": realized_vol,
        "sw_high": sw_high,
        "sw_low": sw_low,
        "fib_618": fib_618,
        "fib_650": fib_650,
        "fib_500": fib_500,
        "trap_status": trap_status
    }


def calculate_btc_confluence(btc, dxy_chg, tnx_chg, fg_val):
    score = 0
    factors = []

    # 1. Macro: DXY not surging
    if dxy_chg < 0.2:
        score += 1
        factors.append("Macro: DXY stable/falling (Tailwind)")
    # 2. Macro: Yields not surging
    if tnx_chg < 1.0:
        score += 1
        factors.append("Macro: 10Y yields not spiking")
    # 3. 200 SMA Bullish trend
    if btc["current"] > btc["ma200"]:
        score += 1
        factors.append("Trend: Above 200-day SMA ($" + f"{btc['ma200']:,.0f})")
    # 4. Mayer Multiple healthy
    if 0.85 <= btc["mayer"] <= 1.50:
        score += 1
        factors.append(f"Valuation: Mayer Multiple healthy ({btc['mayer']:.2f})")
    # 5. RSI not overbought
    if 40 <= btc["rsi"] <= 65:
        score += 1
        factors.append(f"Momentum: RSI reset & healthy ({btc['rsi']:.1f})")
    # 6. Golden Pocket Proximity (within 2% of 0.618 Fib)
    if abs(btc["current"] - btc["fib_618"]) / btc["current"] <= 0.025:
        score += 1
        factors.append("Level: Sits in Golden Pocket (0.618)")
    # 7. Sentiment not extreme greed
    if 25 <= fg_val <= 70:
        score += 1
        factors.append(f"Sentiment: Fear & Greed optimal ({fg_val})")
    # 8. No Bull Trap
    if "BULL TRAP" not in btc["trap_status"]:
        score += 1
        factors.append("Microstructure: No active Bull Trap / Fakeout")
    # 9. Above 50 SMA
    if btc["current"] > btc["ma50"]:
        score += 1
        factors.append("Momentum: Price above 50-day SMA")
    # 10. Realized Volatility manageable (< 75%)
    if btc["vol"] < 75:
        score += 1
        factors.append(f"Risk: Volatility normalized ({btc['vol']:.1f}%)")

    return score, factors


def calculate_gold_confluence(gold, dxy_chg, tnx_chg, gsr):
    score = 0
    factors = []

    # 1. Macro: DXY weakness
    if dxy_chg <= 0.0:
        score += 1
        factors.append("Macro: US Dollar weakening (Direct Gold tailwind)")
    # 2. Macro: 10Y Yield easing
    if tnx_chg <= 0.0:
        score += 1
        factors.append("Macro: 10Y Yield easing (Real yield tailwind)")
    # 3. Trend: Above 200 SMA
    if gold["current"] > gold["ma200"]:
        score += 1
        factors.append("Trend: Above 200-day SMA ($" + f"{gold['ma200']:,.0f})")
    # 4. Momentum: Above 50 SMA
    if gold["current"] > gold["ma50"]:
        score += 1
        factors.append("Trend: Above 50-day SMA")
    # 5. RSI healthy
    if 40 <= gold["rsi"] <= 60:
        score += 1
        factors.append(f"Momentum: RSI in pullback sweet spot ({gold['rsi']:.1f})")
    # 6. Golden Pocket Proximity (within 2% of 0.618 Fib)
    if abs(gold["current"] - gold["fib_618"]) / gold["current"] <= 0.025:
        score += 1
        factors.append("Level: Sits in Golden Pocket (0.618 Fib)")
    # 7. Gold/Silver Ratio historically elevated (> 80)
    if gsr >= 80:
        score += 1
        factors.append(f"Metals Value: GSR high ({gsr:.1f}x) indicating sound money bid")
    # 8. Volatility calm (< 22%)
    if gold["vol"] < 22:
        score += 1
        factors.append(f"Risk: Gold volatility orderly ({gold['vol']:.1f}%)")
    # 9. No Bull Trap
    if "BULL TRAP" not in gold["trap_status"]:
        score += 1
        factors.append("Microstructure: Clean auction; no Bull Trap")
    # 10. Near Swing Support (within 3% of 60D Low)
    if abs(gold["current"] - gold["sw_low"]) / gold["current"] <= 0.04:
        score += 1
        factors.append("Asymmetry: Near 60D structural support floor")

    return score, factors


def main():
    print("\n⏳ Running Institutional Hard-Asset Audit (Gold, BTC, Macro)...")

    btc = get_asset_stats("BTC-USD")
    gold = get_asset_stats("GC=F")
    silver = get_asset_stats("SI=F")

    # Macro Feeds
    dxy = yf.Ticker("DX-Y.NYB").history(period="5d")
    tnx = yf.Ticker("^TNX").history(period="5d")
    vix = yf.Ticker("^VIX").history(period="5d")

    dxy_val = dxy["Close"].iloc[-1] if not dxy.empty else 0.0
    dxy_chg = (((dxy_val / dxy["Close"].iloc[-2]) - 1) * 100) if len(dxy) >= 2 else 0.0

    tnx_val = tnx["Close"].iloc[-1] if not tnx.empty else 0.0
    tnx_chg = (((tnx_val / tnx["Close"].iloc[-2]) - 1) * 100) if len(tnx) >= 2 else 0.0

    vix_val = vix["Close"].iloc[-1] if not vix.empty else 0.0

    fg_val, fg_label = fetch_fear_greed()

    # Ratios
    ratio_btc_gold = (btc["current"] / gold["current"]) if (btc and gold) else 0.0
    gsr = (gold["current"] / silver["current"]) if (gold and silver) else 0.0

    # Confluence Scores
    btc_score, btc_factors = calculate_btc_confluence(btc, dxy_chg, tnx_chg, fg_val)
    gold_score, gold_factors = calculate_gold_confluence(gold, dxy_chg, tnx_chg, gsr)

    print(f"""
╔══════════════════════════════════════════════════════════════════════════════════╗
║             INSTITUTIONAL HARD ASSETS AUDIT (GOLD & BITCOIN ENGINE)              ║
╠══════════════════════════════════════════════════════════════════════════════════╣
  🌐 MACROECONOMIC DRIVERS:
  • US Dollar (DXY)         : {dxy_val:>7.2f}  ({dxy_chg:>+5.2f}% 1D)  [{'USD Headwind ❌' if dxy_chg > 0.2 else 'USD Tailwind ✅' if dxy_chg < -0.2 else 'Neutral'}]
  • 10-Yr Benchmark (^TNX)  : {tnx_val:>7.2f}% ({tnx_chg:>+5.2f}% 1D)  [{'Real Yield Spiking ⚠️' if tnx_chg > 1.0 else 'Real Yield Controlled ✅'}]
  • Volatility Index (VIX)  : {vix_val:>7.2f}   [{'High Chop / Risk-Off' if vix_val > 25 else 'Orderly Market'}]
  • Inter-Market Ratios     : BTC/Gold = {ratio_btc_gold:>5.2f} oz/BTC  |  Gold/Silver (GSR) = {gsr:>5.2f}x
╠══════════════════════════════════════════════════════════════════════════════════╣
  🥇 GOLD (COMEX: GC=F)
  • Spot Reference:   ${gold['current']:>10,.2f} / oz  (1D: {gold['chg_1d']:>+5.2f}% | 7D: {gold['chg_7d']:>+5.2f}% | 30D: {gold['chg_30d']:>+5.2f}%)
  • Trend Metrics:    200 SMA: ${gold['ma200']:>9,.0f} | 50 SMA: ${gold['ma50']:>9,.0f} | RSI(14): {gold['rsi']:>5.1f}
  • Realized Vol (30D): {gold['vol']:>5.1f}% annualized
  • Structural Levels:
      - 60D Swing High: ${gold['sw_high']:>10,.2f}
      - Golden Pocket : ${gold['fib_650']:>10,.2f} to ${gold['fib_618']:>10,.2f} (0.618 - 0.65 Fib)
      - 60D Swing Low : ${gold['sw_low']:>10,.2f}
  • Liquidity Status: {gold['trap_status']}
  ────────────────────────────────────────────────────────────────────────────────
  🎯 GOLD CONFLUENCE SCORE: {gold_score:>2}/10  [{'A+ SETUP (EXECUTE)' if gold_score >= 9 else 'B SETUP (HALF-SIZE)' if gold_score >= 7 else 'VETOED (WAIT FOR CONFLUENCE)'}]
  Confluence Components:
  {chr(10).join('  • ' + f for f in gold_factors) if gold_factors else '  • No major confluence factors active.'}
╠══════════════════════════════════════════════════════════════════════════════════╣
  ₿ BITCOIN (BTC-USD)
  • Price:            ${btc['current']:>10,.2f}  (1D: {btc['chg_1d']:>+5.2f}% | 7D: {btc['chg_7d']:>+5.2f}% | 30D: {btc['chg_30d']:>+5.2f}%)
  • Trend Metrics:    200 SMA: ${btc['ma200']:>9,.0f} | 50 SMA: ${btc['ma50']:>9,.0f} | RSI(14): {btc['rsi']:>5.1f}
  • Valuation Ratio:  Mayer Multiple = {btc['mayer']:>5.2f}x  [{'Undervalued (<0.85)' if btc['mayer'] < 0.85 else 'Overheated (>2.4)' if btc['mayer'] > 2.4 else 'Sustainable Expansion (0.85-1.5)'}]
  • Realized Vol (30D): {btc['vol']:>5.1f}% annualized  |  Fear & Greed: {fg_val} ({fg_label})
  • Structural Levels:
      - 60D Swing High: ${btc['sw_high']:>10,.2f}
      - Golden Pocket : ${btc['fib_650']:>10,.2f} to ${btc['fib_618']:>10,.2f} (0.618 - 0.65 Fib)
      - 60D Swing Low : ${btc['sw_low']:>10,.2f}
  • Liquidity Status: {btc['trap_status']}
  ────────────────────────────────────────────────────────────────────────────────
  🎯 BTC CONFLUENCE SCORE: {btc_score:>2}/10  [{'A+ SETUP (EXECUTE)' if btc_score >= 9 else 'B SETUP (HALF-SIZE)' if btc_score >= 7 else 'VETOED (WAIT FOR CONFLUENCE)'}]
  Confluence Components:
  {chr(10).join('  • ' + f for f in btc_factors) if btc_factors else '  • No major confluence factors active.'}
╚══════════════════════════════════════════════════════════════════════════════════╝
""")


if __name__ == "__main__":
    main()
