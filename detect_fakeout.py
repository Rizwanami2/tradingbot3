#!/usr/bin/env python3
"""
trader-fake-breakouts: detect_fakeout.py
Algorithmic scanner for detecting Bull Traps (Upthrusts) and Bear Traps (Springs)
using price action, wick rejection geometry, and volume anomaly analysis.
"""

import argparse
import sys
import numpy as np

try:
    import yfinance as yf
except ImportError:
    print("Error: yfinance is required. Run: pip install yfinance")
    sys.exit(1)


def analyze_fakeouts(ticker_symbol: str, lookback_days: int = 90):
    print(f"\n🔍 Scanning {ticker_symbol} for Breakouts and Liquidity Sweeps...")
    ticker = yf.Ticker(ticker_symbol)
    hist = ticker.history(period=f"{lookback_days}d")

    if hist.empty or len(hist) < 30:
        print(f"❌ Insufficient historical data for '{ticker_symbol}'.")
        return

    # Calculate 20-day rolling high/low (shifted by 1 to exclude current bar)
    hist["20_High"] = hist["High"].shift(1).rolling(window=20).max()
    hist["20_Low"] = hist["Low"].shift(1).rolling(window=20).min()
    hist["Vol_MA20"] = hist["Volume"].rolling(window=20).mean()

    # Identify traps across the last 15 trading days
    recent = hist.tail(15).copy()
    traps_found = []

    for idx, row in recent.iterrows():
        date_str = idx.strftime("%Y-%m-%d")
        o, h, l, c, v = row["Open"], row["High"], row["Low"], row["Close"], row["Volume"]
        prior_high = row["20_High"]
        prior_low = row["20_Low"]
        vol_avg = row["Vol_MA20"]

        total_range = h - l
        if total_range <= 0:
            continue

        body = abs(c - o)
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l

        vol_ratio = (v / vol_avg) if vol_avg > 0 else 1.0

        # Bull Trap / Upthrust criteria:
        # 1. High pierced the 20-day resistance
        # 2. Close settled back BELOW the 20-day resistance
        # 3. Upper wick represents >= 40% of the candle's total range
        if h > prior_high and c < prior_high and (upper_wick / total_range) >= 0.40:
            traps_found.append({
                "date": date_str,
                "type": "BULL TRAP 🔴 (Liquidity Sweep / Upthrust)",
                "price_pierced": h,
                "closed_at": c,
                "level": prior_high,
                "wick_pct": (upper_wick / total_range) * 100,
                "vol_ratio": vol_ratio,
                "action": "FADE: Look for Short entry targeting range equilibrium. Stop above sweep high."
            })

        # Bear Trap / Spring criteria:
        # 1. Low pierced below the 20-day support
        # 2. Close settled back ABOVE the 20-day support
        # 3. Lower wick represents >= 40% of the candle's total range
        elif l < prior_low and c > prior_low and (lower_wick / total_range) >= 0.40:
            traps_found.append({
                "date": date_str,
                "type": "BEAR TRAP 🟢 (Liquidity Sweep / Spring)",
                "price_pierced": l,
                "closed_at": c,
                "level": prior_low,
                "wick_pct": (lower_wick / total_range) * 100,
                "vol_ratio": vol_ratio,
                "action": "FADE: Look for Long entry targeting range equilibrium. Stop below sweep low."
            })

        # Real Breakout Check
        elif c > prior_high and (body / total_range) >= 0.55 and vol_ratio >= 1.2:
            traps_found.append({
                "date": date_str,
                "type": "CLEAN BREAKOUT 🚀 (Bullish Acceptance)",
                "price_pierced": h,
                "closed_at": c,
                "level": prior_high,
                "wick_pct": (upper_wick / total_range) * 100,
                "vol_ratio": vol_ratio,
                "action": "CONTINUATION: Wait for clean retest of broken level on declining volume."
            })

    current_price = hist["Close"].iloc[-1]
    res_20 = hist["20_High"].iloc[-1]
    sup_20 = hist["20_Low"].iloc[-1]

    print(f"""
╔══════════════════════════════════════════════════════════════════╗
║               BREAKOUT & LIQUIDITY TRAP AUDIT REPORT             ║
╠══════════════════════════════════════════════════════════════════╣
  Ticker:          {ticker_symbol.upper():<10}
  Current Price:   ${current_price:>12,.2f}
  20-Day Range:    ${sup_20:>12,.2f}  to  ${res_20:>12,.2f}
╠══════════════════════════════════════════════════════════════════╣
  ⚡ RECENT BREAKOUT & SWEEP EVENTS (Last 15 Sessions):""")

    if traps_found:
        for t in traps_found:
            print(f"""
  ★ Date: {t['date']}  |  {t['type']}
    • Level Tested:       ${t['level']:,.2f}
    • Extreme Wick Price: ${t['price_pierced']:,.2f}
    • Bar Close Price:    ${t['closed_at']:,.2f}
    • Rejection Wick:     {t['wick_pct']:.1f}% of total bar
    • Volume vs 20D Avg:  {t['vol_ratio']:.2f}x
    • Tactical Play:      {t['action']}""")
    else:
        print("  ✅ No trap or breakout events detected in the last 15 sessions.")
        print(f"     Price is consolidating cleanly between ${sup_20:,.2f} and ${res_20:,.2f}.")

    print("\n╚══════════════════════════════════════════════════════════════════╝\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Detect Fake Breakouts and Liquidity Sweeps")
    parser.add_argument("--ticker", default="TSLA", help="Ticker symbol to scan (default: TSLA)")
    parser.add_argument("--lookback", type=int, default=90, help="Lookback period in days (default: 90)")
    args = parser.parse_args()

    analyze_fakeouts(args.ticker, args.lookback)
