#!/usr/bin/env python3
"""
telegram_bot.py
Standalone Institutional Hard-Asset Trading Bot for Telegram (Gold & Bitcoin).
100% Free of MetaTrader 5 (MT5) - Runs on ANY VPS (Windows, Linux, Ubuntu, macOS).

Features:
  - Macro Radar: Real-time DXY, US 10Y Yields, GSR, and Crypto Fear & Greed.
  - 4-Stage Confluence Pipeline: Golden Pocket (0.618-0.650 Fib), 50/200 SMA, Wyckoff Trap Filter.
  - Autonomous Self-Learning Engine: Dynamic factor weighting tuned to real win-rates.
  - Automated 30-Minute Market Scanner: Broadcasts alerts directly to your phone.
  - Zero MT5 / Broker Dependency: Works immediately with free public financial feeds.
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

# Fix for Windows VPS missing root CA certificates or hosting provider SSL inspection
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context
from datetime import datetime
import numpy as np

# Suppress warnings
import warnings
warnings.filterwarnings("ignore")

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
    # Update .env
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

    # Update config_telegram.json if exists
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
    """Verifies token against Telegram getMe API."""
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GoldBtcTelegramBot/2.0"})
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
    """Sends a Telegram message with fallback to plain text if Markdown fails."""
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
        # Fallback to plain text if Markdown parsing fails
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


def analyze_asset(symbol: str, asset_type: str, dxy_chg: float, tnx_chg: float, gsr: float, fg_val: int):
    t = yf.Ticker(symbol)
    hist = t.history(period="350d")
    if hist.empty or len(hist) < 30:
        return None

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

    # Trap analysis
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

    rsi = compute_rsi(hist["Close"], 14)
    mayer = (curr / ma200) if not np.isnan(ma200) and ma200 > 0 else 1.0
    daily_rets = hist["Close"].pct_change().dropna()
    vol30 = float(daily_rets.tail(30).std() * np.sqrt(365) * 100) if len(daily_rets) >= 30 else 30.0

    # Feature vector
    if asset_type == "BTC":
        active_features = {
            "in_golden_pocket": bool(in_golden_pocket),
            "no_trap": bool(trap_state != "BULL_TRAP"),
            "macro_dxy_tailwind": bool(dxy_chg < 0.2),
            "macro_yield_tailwind": bool(tnx_chg < 1.0),
            "trend_ma200": bool(curr > ma200),
            "trend_ma50": bool(curr > ma50),
            "rsi_sweet_spot": bool(40 <= rsi <= 65),
            "mayer_sweet_spot": bool(0.85 <= mayer <= 1.50),
            "gsr_undervalued": False,
            "volatility_orderly": bool(vol30 < 75),
            "near_swing_support": bool((curr - sw_low) / curr <= 0.05)
        }
    else:  # GOLD
        active_features = {
            "in_golden_pocket": bool(in_golden_pocket),
            "no_trap": bool(trap_state != "BULL_TRAP"),
            "macro_dxy_tailwind": bool(dxy_chg <= 0.05),
            "macro_yield_tailwind": bool(tnx_chg <= 0.2),
            "trend_ma200": bool(curr > ma200),
            "trend_ma50": bool(curr > ma50),
            "rsi_sweet_spot": bool(40 <= rsi <= 60),
            "mayer_sweet_spot": False,
            "gsr_undervalued": bool(gsr >= 75),
            "volatility_orderly": bool(vol30 < 22),
            "near_swing_support": bool((curr - sw_low) / curr <= 0.05)
        }

    base_score = sum(1 for v in active_features.values() if v)
    adaptive_score = base_score
    if LEARNING_AVAILABLE and learning_engine:
        adaptive_score, _ = learning_engine.calculate_score(asset_type, active_features)

    final_score = max(base_score, int(round(adaptive_score)))
    is_ready = final_score >= 8

    # Order parameters
    stop_loss = fib_650 * 0.985 if in_golden_pocket else sw_low * 0.985
    tp1 = fib_500 if curr < fib_500 * 0.98 else sw_high * 0.98
    tp2 = sw_high
    risk_pct = abs(curr - stop_loss) / curr * 100 if curr > 0 else 1.0
    reward_pct = abs(tp1 - curr) / curr * 100 if curr > 0 else 2.0
    rr = reward_pct / risk_pct if risk_pct > 0 else 2.0

    return {
        "asset": asset_type,
        "symbol": symbol,
        "price": curr,
        "ma200": ma200,
        "ma50": ma50,
        "rsi": rsi,
        "mayer": mayer,
        "vol30": vol30,
        "in_golden_pocket": in_golden_pocket,
        "golden_pocket": (fib_650, fib_618),
        "trap_state": trap_state,
        "base_score": base_score,
        "adaptive_score": adaptive_score,
        "is_ready": is_ready,
        "entry": curr,
        "stop_loss": stop_loss,
        "tp1": tp1,
        "tp2": tp2,
        "risk_pct": risk_pct,
        "reward_pct": reward_pct,
        "rr": rr
    }


def run_full_market_scan():
    """Fetches macro context and analyzes BTC & Gold."""
    dxy = yf.Ticker("DX-Y.NYB").history(period="5d")
    tnx = yf.Ticker("^TNX").history(period="5d")
    silver = yf.Ticker("SI=F").history(period="5d")
    gold_5d = yf.Ticker("GC=F").history(period="5d")

    dxy_val = dxy["Close"].iloc[-1] if not dxy.empty else 102.0
    dxy_chg = (((dxy_val / dxy["Close"].iloc[-2]) - 1) * 100) if len(dxy) >= 2 else 0.0
    tnx_val = tnx["Close"].iloc[-1] if not tnx.empty else 5.0
    tnx_chg = (((tnx_val / tnx["Close"].iloc[-2]) - 1) * 100) if len(tnx) >= 2 else 0.0
    gsr = (gold_5d["Close"].iloc[-1] / silver["Close"].iloc[-1]) if (not gold_5d.empty and not silver.empty) else 75.0
    fg_val, fg_label = fetch_fear_greed()

    btc_res = analyze_asset("BTC-USD", "BTC", dxy_chg, tnx_chg, gsr, fg_val)
    gold_res = analyze_asset("GC=F", "GOLD", dxy_chg, tnx_chg, gsr, fg_val)

    return {
        "macro": {
            "dxy": dxy_val, "dxy_chg": dxy_chg, "tnx": tnx_val, "tnx_chg": tnx_chg,
            "gsr": gsr, "fg_val": fg_val, "fg_label": fg_label
        },
        "btc": btc_res,
        "gold": gold_res
    }


def format_scan_report(data):
    m = data["macro"]
    b = data["btc"]
    g = data["gold"]

    btc_status = "🟢 *A+ SETUP (READY)*" if b['is_ready'] else "🔴 *WAIT / VETOED*"
    gold_status = "🟢 *A+ SETUP (READY)*" if g['is_ready'] else "🔴 *WAIT / VETOED*"

    lines = [
        "📊 *HARD-ASSET CONFLUENCE SCAN*",
        "",
        f"🌐 *Macro Radar:*",
        f"• DXY: `{m['dxy']:.2f}` ({m['dxy_chg']:+.2f}%) | 10Y: `{m['tnx']:.2f}%`",
        f"• GSR: `{m['gsr']:.1f}x` | Crypto F&G: `{m['fg_val']}` ({m['fg_label']})",
        "",
        f"₿ *Bitcoin (BTC-USD):* `${b['price']:,.2f}`",
        f"• Confluence: `{b['base_score']}/10` (Learned: `{b['adaptive_score']:.1f}/10`)",
        f"• Location: {'✅ Golden Pocket' if b['in_golden_pocket'] else 'Outside GP'} | Trap: `{b['trap_state']}`",
        f"• RSI: `{b['rsi']:.1f}` | Mayer: `{b['mayer']:.2f}x`",
        f"• Verdict: {btc_status}",
        "",
        f"🥇 *Gold (XAU/USD):* `${g['price']:,.2f}`",
        f"• Confluence: `{g['base_score']}/10` (Learned: `{g['adaptive_score']:.1f}/10`)",
        f"• Location: {'✅ Golden Pocket' if g['in_golden_pocket'] else 'Outside GP'} | Trap: `{g['trap_state']}`",
        f"• RSI: `{g['rsi']:.1f}`",
        f"• Verdict: {gold_status}",
        ""
    ]

    if b['is_ready']:
        lines.extend([
            f"⚡ *ACTIONABLE BTC TICKET:*",
            f"• Entry: `${b['entry']:,.2f}` | Stop: `${b['stop_loss']:,.2f}`",
            f"• TP1: `${b['tp1']:,.2f}` | TP2: `${b['tp2']:,.2f}` (R:R 1:{b['rr']:.2f})",
            ""
        ])

    if g['is_ready']:
        lines.extend([
            f"⚡ *ACTIONABLE GOLD TICKET:*",
            f"• Entry: `${g['entry']:,.2f}` | Stop: `${g['stop_loss']:,.2f}`",
            f"• TP1: `${g['tp1']:,.2f}` | TP2: `${g['tp2']:,.2f}` (R:R 1:{g['rr']:.2f})",
            ""
        ])

    lines.append("Commands: `/scan`, `/btc`, `/gold`, `/macro`, `/learn`, `/train`")
    return "\n".join(lines)


def auto_scanner_worker(token: str, chat_id_getter):
    """Background loop: checks markets every 30 minutes and broadcasts A+ signals."""
    print("⏰ Background Automated Scanner Active (Scans every 30 mins)")
    while True:
        try:
            time.sleep(1800)  # 30 minutes
            target_chat_id = chat_id_getter()
            if not target_chat_id:
                continue

            data = run_full_market_scan()
            b = data["btc"]
            g = data["gold"]

            # Alert if an A+ setup is detected
            if b['is_ready'] or g['is_ready']:
                print(f"🚨 [{datetime.now().strftime('%H:%M:%S')}] A+ Setup detected! Broadcasting Telegram alert...")
                alert_text = "🚨 *INSTITUTIONAL TRADE ALERT (SCORE >= 8/10)*\n\n" + format_scan_report(data)
                send_message(token, target_chat_id, alert_text)
        except Exception as e:
            time.sleep(10)


def start_bot():
    token, chat_id = get_credentials()

    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        print("\n" + "=" * 70)
        print("  ⚠️ TELEGRAM BOT TOKEN REQUIRED")
        print("=" * 70)
        print("  1. Open Telegram, message '@BotFather', and send: /newbot")
        print("  2. Copy your bot token.")
        print("  3. Run: python test_telegram.py")
        print("     Or put it in your '.env' file: TELEGRAM_BOT_TOKEN=your_token")
        print("=" * 70 + "\n")
        return

    # Verify connection with Telegram
    ok, bot_username, bot_first_name = verify_token(token)
    if not ok:
        print("\n" + "=" * 70)
        if bot_username == "401_UNAUTHORIZED":
            print("  ❌ INVALID TELEGRAM BOT TOKEN (401 Unauthorized)")
            print("  Your bot_token is incorrect. Please check with @BotFather.")
        else:
            print(f"  ❌ Telegram Connection Error: {bot_first_name}")
        print("=" * 70 + "\n")
        return

    print("=" * 70)
    print("  🚀 GOLD & BITCOIN QUANTITATIVE TRADING BOT (ZERO MT5)")
    print("=" * 70)
    print(f"  🟢 Telegram Connected : @{bot_username} ({bot_first_name})")
    print(f"  🧠 Self-Learning      : {'ONLINE (learning_memory.json)' if LEARNING_AVAILABLE else 'OFFLINE'}")
    print(f"  🛡️ Broker Dependency  : NONE (100% Standalone)")
    print("=" * 70)
    print(f"\n📱 Open Telegram, search @{bot_username}, and send: /start\n")

    current_chat_id = chat_id

    def get_active_chat_id():
        return current_chat_id

    # Start automated background scanner thread
    t = threading.Thread(target=auto_scanner_worker, args=(token, get_active_chat_id), daemon=True)
    t.start()

    offset = None
    while True:
        try:
            url = f"https://api.telegram.org/bot{token}/getUpdates?timeout=25"
            if offset:
                url += f"&offset={offset}"
            req = urllib.request.Request(url, headers={"User-Agent": "GoldBtcTelegramBot/2.0"})
            with urllib.request.urlopen(req, timeout=35) as r:
                updates = json.loads(r.read())

            for u in updates.get("result", []):
                offset = u["update_id"] + 1

                if "message" in u and "text" in u["message"]:
                    msg_text = u["message"]["text"].strip()
                    sender_id = str(u["message"]["chat"]["id"])
                    sender_name = u["message"]["from"].get("first_name", "User")

                    # Auto-bind Chat ID on first incoming message
                    if not current_chat_id or current_chat_id in ("YOUR_TELEGRAM_CHAT_ID_HERE", "0", ""):
                        print(f"🔑 Auto-authorized Chat ID: {sender_id} ({sender_name}). Saved for alerts!")
                        current_chat_id = sender_id
                        save_chat_id(sender_id)

                    print(f"📩 [{datetime.now().strftime('%H:%M:%S')}] From {sender_name}: '{msg_text}'")

                    if msg_text.startswith("/start") or msg_text.startswith("/help"):
                        welcome = (
                            f"🚀 *Gold & Bitcoin Institutional Trading Engine*\n\n"
                            f"Welcome {sender_name}! The bot is active and continuously scanning hard monetary assets.\n\n"
                            f"Commands:\n"
                            f"• `/scan` - Full confluence scan for Gold & BTC\n"
                            f"• `/btc` - Detailed Bitcoin structure & trade ticket\n"
                            f"• `/gold` - Detailed Gold structure & trade ticket\n"
                            f"• `/macro` - Global macro dashboard (DXY, 10Y Yields, GSR)\n"
                            f"• `/learn` - View self-learning factor rankings\n"
                            f"• `/train` - Run walk-forward historical self-calibration\n\n"
                            f"🔔 *Automated Alerts:* Active! You will receive high-priority alerts whenever an A+ setup (≥8/10) appears."
                        )
                        send_message(token, sender_id, welcome)

                    elif msg_text.startswith("/scan"):
                        send_message(token, sender_id, "⏳ Scanning market structure & macro context...")
                        data = run_full_market_scan()
                        report = format_scan_report(data)
                        send_message(token, sender_id, report)

                    elif msg_text.startswith("/btc"):
                        data = run_full_market_scan()
                        b = data["btc"]
                        status = "🟢 *A+ READY*" if b['is_ready'] else "🔴 *WAIT / VETOED*"
                        ticket = (
                            f"₿ *Bitcoin (BTC-USD) Audit:*\n"
                            f"• Price: `${b['price']:,.2f}` | Score: `{b['base_score']}/10` (Learned: `{b['adaptive_score']:.1f}/10`)\n"
                            f"• 200 SMA: `${b['ma200']:,.0f}` | 50 SMA: `${b['ma50']:,.0f}`\n"
                            f"• RSI: `{b['rsi']:.1f}` | Mayer: `{b['mayer']:.2f}x`\n"
                            f"• Location: {'✅ Inside Golden Pocket' if b['in_golden_pocket'] else 'Outside Golden Pocket'}\n"
                            f"• Trap Filter: `{b['trap_state']}`\n"
                            f"• Verdict: {status}\n\n"
                            f"📋 *Trade Parameters:*\n"
                            f"• Entry: `${b['entry']:,.2f}`\n"
                            f"• Stop-Loss: `${b['stop_loss']:,.2f}` (-{b['risk_pct']:.2f}%)\n"
                            f"• Target 1: `${b['tp1']:,.2f}` (+{b['reward_pct']:.2f}%)\n"
                            f"• Target 2: `${b['tp2']:,.2f}`\n"
                            f"• Risk/Reward: 1:{b['rr']:.2f}"
                        )
                        send_message(token, sender_id, ticket)

                    elif msg_text.startswith("/gold"):
                        data = run_full_market_scan()
                        g = data["gold"]
                        status = "🟢 *A+ READY*" if g['is_ready'] else "🔴 *WAIT / VETOED*"
                        ticket = (
                            f"🥇 *Gold (XAU/USD / GC=F) Audit:*\n"
                            f"• Price: `${g['price']:,.2f}` | Score: `{g['base_score']}/10` (Learned: `{g['adaptive_score']:.1f}/10`)\n"
                            f"• 200 SMA: `${g['ma200']:,.0f}` | 50 SMA: `${g['ma50']:,.0f}`\n"
                            f"• RSI: `{g['rsi']:.1f}`\n"
                            f"• Location: {'✅ Inside Golden Pocket' if g['in_golden_pocket'] else 'Outside Golden Pocket'}\n"
                            f"• Trap Filter: `{g['trap_state']}`\n"
                            f"• Verdict: {status}\n\n"
                            f"📋 *Trade Parameters:*\n"
                            f"• Entry: `${g['entry']:,.2f}`\n"
                            f"• Stop-Loss: `${g['stop_loss']:,.2f}` (-{g['risk_pct']:.2f}%)\n"
                            f"• Target 1: `${g['tp1']:,.2f}` (+{g['reward_pct']:.2f}%)\n"
                            f"• Target 2: `${g['tp2']:,.2f}`\n"
                            f"• Risk/Reward: 1:{g['rr']:.2f}"
                        )
                        send_message(token, sender_id, ticket)

                    elif msg_text.startswith("/macro"):
                        data = run_full_market_scan()
                        m = data["macro"]
                        macro_text = (
                            f"🌐 *GLOBAL MACRO RADAR*\n\n"
                            f"• US Dollar Index (DXY): `{m['dxy']:.2f}` ({m['dxy_chg']:+.2f}%)\n"
                            f"• US 10-Year Real Yield: `{m['tnx']:.2f}%` ({m['tnx_chg']:+.2f}%)\n"
                            f"• Gold/Silver Ratio (GSR): `{m['gsr']:.1f}x` (Undervalued: {m['gsr'] >= 75})\n"
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
        except Exception as e:
            time.sleep(3)


if __name__ == "__main__":
    start_bot()
