#!/usr/bin/env python3
"""
trader-gold-btc: analyst.py
Fetches price, technicals, and macro data for Gold and BTC.
No paid API keys required for basic use.
"""

import argparse
import json
import urllib.request
import urllib.parse
from datetime import datetime, timedelta

# ── Helpers ────────────────────────────────────────────────────────────────────

def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "trader-gold-btc/1.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def fetch_coingecko_btc(days: int = 90) -> dict:
    url = (
        "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
        f"?vs_currency=usd&days={days}&interval=daily"
    )
    return fetch_json(url)

def fetch_fear_greed() -> dict:
    return fetch_json("https://api.alternative.me/fng/?limit=1")

def compute_rsi(prices: list, period: int = 14) -> float:
    if len(prices) < period + 1:
        return float("nan")
    gains, losses = [], []
    for i in range(1, len(prices)):
        d = prices[i] - prices[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)

def compute_ma(prices: list, period: int) -> float:
    if len(prices) < period:
        return float("nan")
    return round(sum(prices[-period:]) / period, 2)

# ── Main Analysis ──────────────────────────────────────────────────────────────

def analyze_btc():
    print("Fetching BTC data from CoinGecko...")
    data = fetch_coingecko_btc(days=200)
    prices = [p[1] for p in data["prices"]]

    current = prices[-1]
    prev_1d = prices[-2] if len(prices) > 1 else current
    prev_7d  = prices[-8] if len(prices) > 7 else current
    prev_30d = prices[-31] if len(prices) > 30 else current

    rsi     = compute_rsi(prices)
    ma_50   = compute_ma(prices, 50)
    ma_200  = compute_ma(prices, 200)
    trend   = "Uptrend" if current > ma_200 else "Downtrend"

    fg_data  = fetch_fear_greed()
    fg_value = int(fg_data["data"][0]["value"])
    fg_label = fg_data["data"][0]["value_classification"]

    print(f"""
╔══════════════════════════════════════════════════════╗
║          BTC ANALYST REPORT — {datetime.today().strftime('%Y-%m-%d')}           ║
╠══════════════════════════════════════════════════════╣
  Price:    ${current:>12,.2f}
  1D Chg:   {((current/prev_1d)-1)*100:>+7.2f}%
  7D Chg:   {((current/prev_7d)-1)*100:>+7.2f}%
  30D Chg:  {((current/prev_30d)-1)*100:>+7.2f}%

  TECHNICAL
  Trend:    {trend} (vs 200D MA ${ma_200:,.0f})
  50D MA:   ${ma_50:>12,.0f}
  RSI(14):  {rsi:>6.1f}  {"⚠ Overbought" if rsi > 70 else "⚠ Oversold" if rsi < 30 else "✅ Neutral"}

  SENTIMENT
  Fear & Greed: {fg_value} — {fg_label}

╚══════════════════════════════════════════════════════╝
""")

def analyze_gold():
    # Gold via Yahoo Finance yfinance (if available) or fallback message
    try:
        import yfinance as yf
        gc = yf.Ticker("GC=F")
        hist = gc.history(period="200d")
        prices = hist["Close"].tolist()
        current = prices[-1]
        prev_1d  = prices[-2]
        prev_7d  = prices[-8] if len(prices) > 7 else current
        prev_30d = prices[-31] if len(prices) > 30 else current

        rsi    = compute_rsi(prices)
        ma_50  = compute_ma(prices, 50)
        ma_200 = compute_ma(prices, 200)
        trend  = "Uptrend" if current > ma_200 else "Downtrend"

        print(f"""
╔══════════════════════════════════════════════════════╗
║         GOLD ANALYST REPORT — {datetime.today().strftime('%Y-%m-%d')}           ║
╠══════════════════════════════════════════════════════╣
  Price:    ${current:>10,.2f} / oz (COMEX)
  1D Chg:   {((current/prev_1d)-1)*100:>+7.2f}%
  7D Chg:   {((current/prev_7d)-1)*100:>+7.2f}%
  30D Chg:  {((current/prev_30d)-1)*100:>+7.2f}%

  TECHNICAL
  Trend:    {trend} (vs 200D MA ${ma_200:,.0f})
  50D MA:   ${ma_50:>10,.0f}
  RSI(14):  {rsi:>6.1f}  {"⚠ Overbought" if rsi > 70 else "⚠ Oversold" if rsi < 30 else "✅ Neutral"}

  NOTE: Fetch real yield & DXY with: python3 analyst.py --macro
╚══════════════════════════════════════════════════════╝
""")
    except ImportError:
        print("ℹ yfinance not installed. Run: pip install yfinance")
        print("  Then re-run: python3 scripts/analyst.py --asset GOLD")

# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Gold & BTC Analyst")
    p.add_argument("--asset", choices=["BTC", "GOLD", "ALL"], default="ALL")
    args = p.parse_args()

    if args.asset in ("BTC", "ALL"):
        analyze_btc()
    if args.asset in ("GOLD", "ALL"):
        analyze_gold()
