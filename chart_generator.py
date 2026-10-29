#!/usr/bin/env python3
"""
chart_generator.py
Generates MT5-Style Candlestick Charts with Key Levels, Fibonacci Golden Pocket,
and Moving Averages, and sends them directly to Telegram.
"""

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import io
import os
import urllib.request
import ssl
from datetime import datetime
import numpy as np

# Fix for Windows VPS missing root CA certificates or hosting provider SSL inspection
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

import matplotlib
matplotlib.use("Agg")  # Non-interactive headless backend for VPS
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

try:
    import yfinance as yf
except ImportError:
    print("❌ yfinance required")
    sys.exit(1)


def generate_mt5_chart(symbol: str, asset_name: str, lookback_bars: int = 45, df_input=None) -> io.BytesIO:
    """
    Renders an MT5-style institutional dark candlestick chart with:
      - 50 SMA & 200 SMA
      - Fibonacci Golden Pocket (0.618 - 0.650) Shaded Band
      - Swing High / Low (S/R)
      - Order Entry, Stop-Loss, and Take-Profit Lines
    Returns in-memory BytesIO buffer containing PNG bytes.
    """
    hist = None
    if df_input is not None and hasattr(df_input, "empty") and not df_input.empty and len(df_input) >= 30:
        hist = df_input.copy()
    else:
        try:
            from market_data import market_data_feed
            asset_norm = "GOLD" if any(x in symbol.upper() for x in ("GC", "GOLD", "XAU")) else "BTC"
            hist = market_data_feed.get_historical_bars(asset_norm, period="350d", min_bars=30)
        except Exception:
            pass

        if hist is None or hist.empty or len(hist) < 30:
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period="180d")
            except Exception:
                pass

    if hist is None or hist.empty or len(hist) < 30:
        return None

    # Slice recent bars for high-clarity viewing
    df = hist.tail(lookback_bars).copy()
    
    # Calculate indicators on full history then slice
    hist["SMA50"] = hist["Close"].rolling(50).mean()
    hist["SMA200"] = hist["Close"].rolling(200).mean()
    df["SMA50"] = hist["SMA50"].tail(lookback_bars)
    df["SMA200"] = hist["SMA200"].tail(lookback_bars)

    # 60-day swing levels
    recent_60 = hist.tail(60)
    sw_h = recent_60["High"].max()
    sw_l = recent_60["Low"].min()
    fib_500 = sw_h - 0.500 * (sw_h - sw_l)
    fib_618 = sw_h - 0.618 * (sw_h - sw_l)
    fib_650 = sw_h - 0.650 * (sw_h - sw_l)
    curr_price = df["Close"].iloc[-1]

    # Setup dark theme figure
    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(12, 6.5), dpi=150)
    fig.patch.set_facecolor("#131722")
    ax.set_facecolor("#131722")

    # Plot Candlesticks
    indices = np.arange(len(df))
    width = 0.6
    width2 = 0.1

    up = df[df["Close"] >= df["Open"]]
    down = df[df["Close"] < df["Open"]]

    # Up candles (Green #089981)
    up_idx = np.where(df["Close"] >= df["Open"])[0]
    ax.bar(up_idx, up["Close"] - up["Open"], width, bottom=up["Open"], color="#089981", edgecolor="#089981", zorder=3)
    ax.bar(up_idx, up["High"] - up["Close"], width2, bottom=up["Close"], color="#089981", zorder=3)
    ax.bar(up_idx, up["Low"] - up["Open"], width2, bottom=up["Open"], color="#089981", zorder=3)

    # Down candles (Red #f23645)
    down_idx = np.where(df["Close"] < df["Open"])[0]
    ax.bar(down_idx, down["Close"] - down["Open"], width, bottom=down["Open"], color="#f23645", edgecolor="#f23645", zorder=3)
    ax.bar(down_idx, down["High"] - down["Open"], width2, bottom=down["Open"], color="#f23645", zorder=3)
    ax.bar(down_idx, down["Low"] - down["Close"], width2, bottom=down["Close"], color="#f23645", zorder=3)

    # Moving Averages
    if not df["SMA50"].isna().all():
        ax.plot(indices, df["SMA50"], color="#ff9800", linewidth=1.5, label="50 SMA", zorder=4)
    if not df["SMA200"].isna().all():
        ax.plot(indices, df["SMA200"], color="#2196f3", linewidth=1.8, label="200 SMA", zorder=4)

    # Fibonacci Golden Pocket Highlight (0.618 - 0.650)
    ax.axhspan(fib_650, fib_618, color="#ffd700", alpha=0.22, label=f"Golden Pocket (${fib_650:,.0f} - ${fib_618:,.0f})", zorder=2)
    ax.axhline(fib_618, color="#ffd700", linestyle="--", alpha=0.6, linewidth=1.0)
    ax.axhline(fib_650, color="#ffd700", linestyle="--", alpha=0.6, linewidth=1.0)

    # Key S/R levels
    ax.axhline(sw_h, color="#e91e63", linestyle=":", linewidth=1.2, label=f"Resistance (${sw_h:,.0f})", zorder=2)
    ax.axhline(sw_l, color="#4caf50", linestyle=":", linewidth=1.2, label=f"Support (${sw_l:,.0f})", zorder=2)

    # Current Price tag line
    ax.axhline(curr_price, color="#ffffff", linestyle="-", linewidth=0.8, alpha=0.8)

    # X-Axis date labels
    step = max(1, len(df) // 8)
    ticks = indices[::step]
    labels = [df.index[i].strftime("%b %d") for i in ticks]
    ax.set_xticks(ticks)
    ax.set_xticklabels(labels, rotation=0, fontsize=9, color="#9aa0a6")

    # Grid & Spines
    ax.grid(True, linestyle="--", alpha=0.15, color="#ffffff")
    for spine in ax.spines.values():
        spine.set_color("#2a2e39")

    # Title & Legend
    time_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    ax.set_title(f"MT5 CHART SCAN: {asset_name} ({symbol}) | Price: ${curr_price:,.2f} | {time_str}",
                 fontsize=12, fontweight="bold", color="#ffffff", pad=12)
    ax.legend(loc="upper left", facecolor="#181a20", edgecolor="#2a2e39", fontsize=8)

    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", facecolor=fig.get_facecolor(), dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf


def send_telegram_chart(token: str, chat_id: str, photo_buf: io.BytesIO, caption: str = ""):
    """Sends chart PNG to Telegram using multipart/form-data upload."""
    boundary = "----WebKitFormBoundary" + str(int(datetime.now().timestamp()))
    lines = []
    
    # chat_id field
    lines.append(f"--{boundary}".encode())
    lines.append(b'Content-Disposition: form-data; name="chat_id"')
    lines.append(b"")
    lines.append(str(chat_id).encode())

    # caption field
    if caption:
        lines.append(f"--{boundary}".encode())
        lines.append(b'Content-Disposition: form-data; name="caption"')
        lines.append(b"")
        lines.append(caption.encode())

    # photo file field
    lines.append(f"--{boundary}".encode())
    lines.append(b'Content-Disposition: form-data; name="photo"; filename="mt5_chart.png"')
    lines.append(b"Content-Type: image/png")
    lines.append(b"")
    
    body = b"\r\n".join(lines) + b"\r\n" + photo_buf.getvalue() + b"\r\n" + f"--{boundary}--\r\n".encode()

    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    req = urllib.request.Request(url, data=body)
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("User-Agent", "TelegramChartBot/1.0")

    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return True, r.read().decode()
    except Exception as e:
        return False, str(e)


if __name__ == "__main__":
    print("Testing MT5 Chart Generation...")
    buf = generate_mt5_chart("BTC-USD", "BITCOIN")
    if buf:
        with open("test_chart_btc.png", "wb") as f:
            f.write(buf.getvalue())
        print(f"✅ Generated test_chart_btc.png ({len(buf.getvalue())} bytes)")
    buf_gold = generate_mt5_chart("GC=F", "GOLD")
    if buf_gold:
        with open("test_chart_gold.png", "wb") as f:
            f.write(buf_gold.getvalue())
        print(f"✅ Generated test_chart_gold.png ({len(buf_gold.getvalue())} bytes)")
