#!/usr/bin/env python3
"""
trader-key-levels: find_levels.py
Algorithmic key entry level & confluence detector using price action,
Fibonacci retracements, key moving averages, and structural pivots.
"""

import argparse
import sys
import numpy as np

try:
    import yfinance as yf
except ImportError:
    print("Error: yfinance is required. Run: pip install yfinance")
    sys.exit(1)


def compute_levels(ticker_symbol: str, lookback_days: int = 180):
    print(f"\n🔍 Fetching historical data for {ticker_symbol} ({lookback_days} days)...")
    ticker = yf.Ticker(ticker_symbol)
    hist = ticker.history(period=f"{lookback_days}d")

    if hist.empty or len(hist) < 50:
        print(f"❌ Insufficient historical data found for '{ticker_symbol}'.")
        return

    current_price = hist["Close"].iloc[-1]
    high_price = hist["High"].max()
    low_price = hist["Low"].min()

    # Find recent swing high and swing low (last 60 bars)
    recent_window = hist.tail(60)
    swing_high = recent_window["High"].max()
    swing_low = recent_window["Low"].min()
    swing_range = swing_high - swing_low

    # Moving Averages
    ma_20_ema = hist["Close"].ewm(span=20, adjust=False).mean().iloc[-1]
    ma_50_sma = hist["Close"].rolling(window=50).mean().iloc[-1] if len(hist) >= 50 else np.nan
    ma_200_sma = hist["Close"].rolling(window=200).mean().iloc[-1] if len(hist) >= 200 else np.nan

    # Fibonacci Retracements (measured from recent swing low to swing high)
    fibs = {
        "Fib 0.382": swing_high - 0.382 * swing_range,
        "Fib 0.500 (Equilibrium)": swing_high - 0.500 * swing_range,
        "Fib 0.618 (Golden Pocket)": swing_high - 0.618 * swing_range,
        "Fib 0.650 (Golden Pocket)": swing_high - 0.650 * swing_range,
        "Fib 0.786": swing_high - 0.786 * swing_range,
    }

    # Daily Classical Pivot Points (from yesterday)
    yesterday = hist.iloc[-2] if len(hist) >= 2 else hist.iloc[-1]
    pp = (yesterday["High"] + yesterday["Low"] + yesterday["Close"]) / 3
    r1 = 2 * pp - yesterday["Low"]
    s1 = 2 * pp - yesterday["High"]

    raw_levels = [
        ("Swing High (Resistance)", swing_high),
        ("Swing Low (Support)", swing_low),
        ("20 EMA (Momentum)", ma_20_ema),
        ("50 SMA (Trend)", ma_50_sma),
        ("200 SMA (Structural)", ma_200_sma),
        ("Daily Pivot (P)", pp),
        ("Daily R1", r1),
        ("Daily S1", s1),
    ]

    for name, val in fibs.items():
        raw_levels.append((name, val))

    # Filter out NaNs
    valid_levels = [(name, val) for name, val in raw_levels if not np.isnan(val)]
    valid_levels.sort(key=lambda x: x[1], reverse=True)

    # Detect Confluence Clusters (levels within 1.0% of each other)
    clusters = []
    threshold_pct = 0.010  # 1.0%

    for i in range(len(valid_levels)):
        name_i, val_i = valid_levels[i]
        matched = [(name_i, val_i)]
        for j in range(i + 1, len(valid_levels)):
            name_j, val_j = valid_levels[j]
            if abs(val_i - val_j) / val_i <= threshold_pct:
                matched.append((name_j, val_j))
        if len(matched) >= 2:
            avg_price = sum(v for _, v in matched) / len(matched)
            labels = [n for n, _ in matched]
            # Avoid duplicate cluster reporting
            if not any(abs(c["price"] - avg_price) / avg_price < 0.005 for c in clusters):
                clusters.append({"price": avg_price, "factors": labels, "count": len(labels)})

    clusters.sort(key=lambda x: x["count"], reverse=True)

    # Print institutional report
    print(f"""
╔══════════════════════════════════════════════════════════════════╗
║               INSTITUTIONAL KEY LEVELS & CONFLUENCE              ║
╠══════════════════════════════════════════════════════════════════╣
  Ticker:         {ticker_symbol.upper():<10}
  Current Price:  ${current_price:>12,.2f}
  60-Day High:    ${swing_high:>12,.2f}
  60-Day Low:     ${swing_low:>12,.2f}
╠══════════════════════════════════════════════════════════════════╣
  🎯 HIGH-CONFLUENCE ENTRY ZONES (Multiple Factors Overlapping):""")

    if clusters:
        for c in clusters:
            dist_pct = ((c["price"] / current_price) - 1) * 100
            zone_type = "RESISTANCE 🔴" if c["price"] > current_price else "SUPPORT 🟢"
            print(f"""
  ★ Zone: ${c['price']:>10,.2f}  ({dist_pct:>+6.2f}%)  [{zone_type}] - Score: {c['count']} Factors
    Components:
    {chr(10).join('    • ' + f for f in c['factors'])}""")
    else:
        print("  No major cluster overlaps detected within 1.0% threshold.")

    print(f"""
╠══════════════════════════════════════════════════════════════════╣
  📊 ALL INDIVIDUAL STRUCTURAL LEVELS:""")

    for name, val in valid_levels:
        dist = ((val / current_price) - 1) * 100
        tag = "ABOVE (Resistance)" if val > current_price else "BELOW (Support)"
        print(f"  {name:<28} : ${val:>11,.2f}  ({dist:>+6.2f}% | {tag})")

    print("""╚══════════════════════════════════════════════════════════════════╝\n""")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Find Institutional Key Levels & Confluence")
    parser.add_argument("--ticker", default="BTC-USD", help="Ticker symbol (e.g., BTC-USD, AAPL, GC=F)")
    parser.add_argument("--lookback", type=int, default=180, help="Lookback period in days (default: 180)")
    args = parser.parse_args()

    compute_levels(args.ticker, args.lookback)
