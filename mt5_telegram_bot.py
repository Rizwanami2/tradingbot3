#!/usr/bin/env python3
"""
trader-gold-btc: mt5_telegram_bot.py
Unified Institutional Telegram Remote Control & MetaTrader 5 (MT5) Execution Engine
with Autonomous Self-Learning & Built-in Paper Trading Fallback.
Compatible with Python 3.11+.

Features:
  1. Instant Token & Bot Verification: Tests token via /getMe and prints @BotUsername.
  2. Auto Chat ID Authorization: Automatically captures and binds your Chat ID on /start.
  3. Robust Markdown Fallback: Guaranteed message delivery even if formatting fails.
  4. Real-time Console Event Log: Logs every message received and order executed.
  5. Live MT5 + Paper Trading Dual Mode.
"""

import warnings
warnings.filterwarnings("ignore")
import json
import os
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
import numpy as np

try:
    import MetaTrader5 as mt5
    MT5_PACKAGE_INSTALLED = True
except ImportError:
    MT5_PACKAGE_INSTALLED = False

try:
    import yfinance as yf
except ImportError:
    print("❌ yfinance required. Run: py -3.11 -m pip install yfinance")
    sys.exit(1)

# Import Self-Learning Engine
try:
    from self_learning import SelfLearningEngine
    learning_engine = SelfLearningEngine()
    LEARNING_AVAILABLE = True
except Exception:
    learning_engine = None
    LEARNING_AVAILABLE = False


CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config_telegram.json")
PAPER_STATE_PATH = os.path.join(os.path.dirname(__file__), "paper_trading_state.json")

# Runtime Mode Tracker
IS_LIVE_MT5 = False
PAPER_ACCOUNT = {
    "balance": 10000.0,
    "equity": 10000.0,
    "positions": []
}


def load_config():
    if not os.path.exists(CONFIG_PATH):
        print(f"[!] Config file not found: {CONFIG_PATH}")
        return None
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print("\n" + "=" * 70)
        print("  ❌ SYNTAX ERROR IN 'config_telegram.json'")
        print("=" * 70)
        print(f"  Error details: {e}")
        print("\n  Common cause: Did you forget a comma (,) after your bot_token?")
        print("  Make sure your file looks exactly like this:")
        print('  {')
        print('    "telegram": {')
        print('      "bot_token": "YOUR_TOKEN_HERE",  <-- Note the comma here!')
        print('      "chat_id": "YOUR_CHAT_ID_HERE"')
        print('    },')
        print('    ...')
        print("=" * 70 + "\n")
        return None


def load_paper_state():
    global PAPER_ACCOUNT
    if os.path.exists(PAPER_STATE_PATH):
        try:
            with open(PAPER_STATE_PATH, "r", encoding="utf-8") as f:
                PAPER_ACCOUNT = json.load(f)
        except Exception:
            pass


def save_paper_state():
    try:
        with open(PAPER_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(PAPER_ACCOUNT, f, indent=2)
    except Exception:
        pass


def verify_telegram_token(token: str):
    """Checks token against Telegram getMe API."""
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MT5TelegramBot/1.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            res = json.loads(r.read())
            if res.get("ok"):
                bot_user = res["result"].get("username", "UnknownBot")
                bot_name = res["result"].get("first_name", "Bot")
                return True, bot_user, bot_name
            return False, "API_ERROR", str(res)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, "401_UNAUTHORIZED", "Token is invalid"
        return False, f"HTTP_{e.code}", str(e)
    except Exception as e:
        return False, "NETWORK_ERROR", str(e)


def send_telegram(token: str, chat_id: str, text: str, reply_markup: dict = None):
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
    except urllib.error.HTTPError as e:
        # Fallback to plain text if Markdown parsing fails (prevents dropped messages)
        try:
            payload.pop("parse_mode", None)
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=12) as r:
                return json.loads(r.read())
        except Exception as retry_err:
            print(f"⚠️ Telegram send error: {retry_err}")
            return None
    except Exception as e:
        print(f"⚠️ Telegram send error: {e}")
        return None


def init_mt5(config=None):
    global IS_LIVE_MT5
    if not MT5_PACKAGE_INSTALLED:
        IS_LIVE_MT5 = False
        return False, "MetaTrader5 Python library not available. Running in 📝 PAPER TRADING MODE."

    custom_path = None
    if config and "mt5" in config and "path" in config["mt5"]:
        custom_path = config["mt5"]["path"]

    init_ok = False
    if custom_path and os.path.exists(custom_path):
        init_ok = mt5.initialize(path=custom_path)
    else:
        init_ok = mt5.initialize()

    if not init_ok:
        err = mt5.last_error()
        IS_LIVE_MT5 = False
        return False, f"MT5 Terminal not running ({err}). Activated 📝 PAPER TRADING MODE (Simulation)."

    terminal_info = mt5.terminal_info()
    account_info = mt5.account_info()

    if not terminal_info.trade_allowed:
        IS_LIVE_MT5 = False
        return False, "MT5 connected, but 'Allow Algo Trading' is OFF in MT5. Running in 📝 PAPER TRADING MODE."

    acc_id = account_info.login if account_info else "Unknown"
    balance = account_info.balance if account_info else 0.0
    IS_LIVE_MT5 = True
    return True, f"🟢 LIVE MT5 Connected | Account #{acc_id} | Balance: ${balance:,.2f}"


def get_account_summary():
    global IS_LIVE_MT5, PAPER_ACCOUNT
    if IS_LIVE_MT5 and MT5_PACKAGE_INSTALLED:
        acc = mt5.account_info()
        if acc:
            positions = mt5.positions_get()
            pos_count = len(positions) if positions else 0
            text = (
                f"🏦 *LIVE MT5 Account:*\n"
                f"• Status: 🟢 *LIVE BROKER EXECUTION*\n"
                f"• Account ID: `{acc.login}`\n"
                f"• Broker: `{acc.company}`\n"
                f"• Balance: `${acc.balance:,.2f}`\n"
                f"• Equity: `${acc.equity:,.2f}`\n"
                f"• Open Positions: `{pos_count}`"
            )
            if pos_count > 0:
                text += "\n\n📋 *Active Trades:*"
                for p in positions:
                    p_type = "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL"
                    text += f"\n• `{p.symbol}` {p_type} `{p.volume}` lots @ `${p.price_open:,.2f}` | PnL: `${p.profit:+,.2f}`"
            return text

    load_paper_state()
    pos_count = len(PAPER_ACCOUNT.get("positions", []))
    text = (
        f"📝 *PAPER TRADING (SIMULATION MODE):*\n"
        f"• Status: 🟡 *Virtual Simulation (No real funds at risk)*\n"
        f"• Virtual Balance: `${PAPER_ACCOUNT['balance']:,.2f}`\n"
        f"• Virtual Equity: `${PAPER_ACCOUNT['equity']:,.2f}`\n"
        f"• Open Paper Positions: `{pos_count}`"
    )
    if pos_count > 0:
        text += "\n\n📋 *Paper Trades:*"
        for p in PAPER_ACCOUNT["positions"]:
            text += f"\n• `{p['symbol']}` BUY `{p['lots']}` lots @ `${p['entry']:,.2f}` | SL: `${p['sl']:,.2f}` | TP: `${p['tp']:,.2f}`"
    return text


def execute_order(symbol: str, action: str, entry: float, sl: float, tp: float, risk_pct: float = 1.0):
    global IS_LIVE_MT5, PAPER_ACCOUNT

    if IS_LIVE_MT5 and MT5_PACKAGE_INSTALLED:
        sym_info = mt5.symbol_info(symbol)
        if not sym_info:
            return False, f"Symbol '{symbol}' not found in MT5."
        if not sym_info.visible:
            mt5.symbol_select(symbol, True)

        acc = mt5.account_info()
        balance = acc.balance if acc else 10000.0
        risk_amount = balance * (risk_pct / 100.0)

        sl_dist = abs(entry - sl)
        tick_size = sym_info.trade_tick_size or 0.01
        tick_val = sym_info.trade_tick_value or 1.0
        risk_per_lot = (sl_dist / tick_size) * tick_val if sl_dist > 0 else 1.0
        lots = round(risk_amount / risk_per_lot, 2) if risk_per_lot > 0 else 0.01
        lots = max(sym_info.volume_min, min(lots, sym_info.volume_max))

        order_type = mt5.ORDER_TYPE_BUY if action.upper() == "BUY" else mt5.ORDER_TYPE_SELL
        price = mt5.symbol_info_tick(symbol).ask if action.upper() == "BUY" else mt5.symbol_info_tick(symbol).bid

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lots,
            "type": order_type,
            "price": price,
            "sl": round(sl, sym_info.digits),
            "tp": round(tp, sym_info.digits),
            "deviation": 20,
            "magic": 888101,
            "comment": "GoldBTC-AutoTrader",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        res = mt5.order_send(request)
        if res.retcode != mt5.TRADE_RETCODE_DONE:
            return False, f"MT5 Order Failed ({res.retcode}): {res.comment}"

        if LEARNING_AVAILABLE and learning_engine:
            asset = "BTC" if "BTC" in symbol.upper() else "GOLD"
            feat = {"in_golden_pocket": True, "no_trap": True, "macro_dxy_tailwind": True,
                    "macro_yield_tailwind": True, "trend_ma200": True, "trend_ma50": True,
                    "rsi_sweet_spot": True, "volatility_orderly": True, "near_swing_support": True}
            learning_engine.log_signal(asset, symbol, price, sl, tp, tp * 1.05, 8.5, feat)

        return True, f"🟢 *LIVE MT5 ORDER EXECUTED!*\n• {action} `{lots}` lots `{symbol}` @ `${price:,.2f}`\n• Ticket: `#{res.order}`"

    # Paper Trading Simulation
    load_paper_state()
    balance = PAPER_ACCOUNT["balance"]
    risk_amount = balance * (risk_pct / 100.0)
    sl_dist = abs(entry - sl)
    lots = round((risk_amount / sl_dist) * 0.01, 2) if sl_dist > 0 else 0.10
    lots = max(0.01, min(lots, 5.0))

    ticket_id = int(time.time() * 1000) % 1000000
    pos = {
        "ticket": ticket_id,
        "symbol": symbol,
        "action": action,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "lots": lots,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    PAPER_ACCOUNT["positions"].append(pos)
    save_paper_state()

    if LEARNING_AVAILABLE and learning_engine:
        asset = "BTC" if "BTC" in symbol.upper() else "GOLD"
        feat = {"in_golden_pocket": True, "no_trap": True, "macro_dxy_tailwind": True,
                "macro_yield_tailwind": True, "trend_ma200": True, "trend_ma50": True,
                "rsi_sweet_spot": True, "volatility_orderly": True, "near_swing_support": True}
        learning_engine.log_signal(asset, symbol, entry, sl, tp, tp * 1.05, 8.5, feat)

    return True, (
        f"📝 *PAPER ORDER EXECUTED (SIMULATION)*\n"
        f"• Asset: `{symbol}` ({action})\n"
        f"• Virtual Lots: `{lots}`\n"
        f"• Entry Price: `${entry:,.2f}`\n"
        f"• Stop-Loss: `${sl:,.2f}`\n"
        f"• Take-Profit: `${tp:,.2f}`\n"
        f"• Ticket: `#{ticket_id}`\n\n"
        f"*(No real money was risked)*"
    )


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


def run_pipeline_scan():
    dxy = yf.Ticker("DX-Y.NYB").history(period="5d")
    tnx = yf.Ticker("^TNX").history(period="5d")
    silver = yf.Ticker("SI=F").history(period="5d")
    gold_5d = yf.Ticker("GC=F").history(period="5d")

    dxy_val = dxy["Close"].iloc[-1] if not dxy.empty else 102.0
    dxy_chg = (((dxy_val / dxy["Close"].iloc[-2]) - 1) * 100) if len(dxy) >= 2 else 0.0
    tnx_val = tnx["Close"].iloc[-1] if not tnx.empty else 5.0
    tnx_chg = (((tnx_val / tnx["Close"].iloc[-2]) - 1) * 100) if len(tnx) >= 2 else 0.0
    gsr = (gold_5d["Close"].iloc[-1] / silver["Close"].iloc[-1]) if (not gold_5d.empty and not silver.empty) else 75.0

    # BTC Analysis
    btc_hist = yf.Ticker("BTC-USD").history(period="350d")
    btc_curr = btc_hist["Close"].iloc[-1]
    btc_ma200 = btc_hist["Close"].rolling(200).mean().iloc[-1]
    btc_ma50 = btc_hist["Close"].rolling(50).mean().iloc[-1]
    btc_rsi = compute_rsi(btc_hist["Close"], 14)
    btc_mayer = btc_curr / btc_ma200

    recent_btc = btc_hist.tail(60)
    btc_sw_h = recent_btc["High"].max()
    btc_sw_l = recent_btc["Low"].min()
    btc_fib618 = btc_sw_h - 0.618 * (btc_sw_h - btc_sw_l)
    btc_fib650 = btc_sw_h - 0.650 * (btc_sw_h - btc_sw_l)

    btc_in_gp = (btc_curr >= btc_fib650 * 0.985) and (btc_curr <= btc_fib618 * 1.02)
    btc_features = {
        "in_golden_pocket": bool(btc_in_gp),
        "no_trap": True,
        "macro_dxy_tailwind": bool(dxy_chg < 0.2),
        "macro_yield_tailwind": bool(tnx_chg < 1.0),
        "trend_ma200": bool(btc_curr > btc_ma200),
        "trend_ma50": bool(btc_curr > btc_ma50),
        "rsi_sweet_spot": bool(40 <= btc_rsi <= 65),
        "mayer_sweet_spot": bool(0.85 <= btc_mayer <= 1.50),
        "gsr_undervalued": False,
        "volatility_orderly": True,
        "near_swing_support": bool((btc_curr - btc_sw_l) / btc_curr <= 0.05)
    }

    btc_score = sum(1 for v in btc_features.values() if v)
    btc_adaptive = btc_score
    if LEARNING_AVAILABLE and learning_engine:
        btc_adaptive, _ = learning_engine.calculate_score("BTC", btc_features)

    # Gold Analysis
    gold_hist = yf.Ticker("GC=F").history(period="350d")
    gold_curr = gold_hist["Close"].iloc[-1]
    gold_ma200 = gold_hist["Close"].rolling(200).mean().iloc[-1]
    gold_ma50 = gold_hist["Close"].rolling(50).mean().iloc[-1]
    gold_rsi = compute_rsi(gold_hist["Close"], 14)

    recent_gold = gold_hist.tail(60)
    gold_sw_h = recent_gold["High"].max()
    gold_sw_l = recent_gold["Low"].min()
    gold_fib618 = gold_sw_h - 0.618 * (gold_sw_h - gold_sw_l)
    gold_fib650 = gold_sw_h - 0.650 * (gold_sw_h - gold_sw_l)

    gold_in_gp = (gold_curr >= gold_fib650 * 0.985) and (gold_curr <= gold_fib618 * 1.02)
    gold_features = {
        "in_golden_pocket": bool(gold_in_gp),
        "no_trap": True,
        "macro_dxy_tailwind": bool(dxy_chg <= 0.05),
        "macro_yield_tailwind": bool(tnx_chg <= 0.2),
        "trend_ma200": bool(gold_curr > gold_ma200),
        "trend_ma50": bool(gold_curr > gold_ma50),
        "rsi_sweet_spot": bool(40 <= gold_rsi <= 60),
        "mayer_sweet_spot": False,
        "gsr_undervalued": bool(gsr >= 75),
        "volatility_orderly": True,
        "near_swing_support": bool((gold_curr - gold_sw_l) / gold_curr <= 0.05)
    }

    gold_score = sum(1 for v in gold_features.values() if v)
    gold_adaptive = gold_score
    if LEARNING_AVAILABLE and learning_engine:
        gold_adaptive, _ = learning_engine.calculate_score("GOLD", gold_features)

    return {
        "macro": {"dxy": dxy_val, "dxy_chg": dxy_chg, "tnx": tnx_val, "gsr": gsr},
        "btc": {
            "price": btc_curr, "score": btc_score, "adaptive_score": btc_adaptive,
            "rsi": btc_rsi, "mayer": btc_mayer,
            "sl": btc_fib650 * 0.985, "tp": btc_sw_h * 0.98
        },
        "gold": {
            "price": gold_curr, "score": gold_score, "adaptive_score": gold_adaptive,
            "rsi": gold_rsi,
            "sl": gold_sw_l * 0.985, "tp": gold_sw_h * 0.98
        }
    }


def handle_telegram_updates(config):
    token = config["telegram"].get("bot_token", "").strip()
    chat_id = str(config["telegram"].get("chat_id", "")).strip()

    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        print("\n" + "=" * 70)
        print("  ⚠️ TELEGRAM BOT TOKEN REQUIRED")
        print("=" * 70)
        print("  1. Open Telegram, search '@BotFather' and send: /newbot")
        print("  2. Copy the token and paste it into 'config_telegram.json'")
        print("=" * 70 + "\n")
        return

    # Verify Token against Telegram API
    is_valid, bot_user, bot_name = verify_telegram_token(token)
    if not is_valid:
        print("\n" + "=" * 70)
        if bot_user == "401_UNAUTHORIZED":
            print("  ❌ INVALID TELEGRAM BOT TOKEN (401 Unauthorized)")
            print("=" * 70)
            print("  The bot_token in 'config_telegram.json' is incorrect.")
            print("  1. Open Telegram, search '@BotFather'")
            print("  2. Run /mybots, select your bot, and click 'API Token'")
            print("  3. Copy the token and paste it into 'config_telegram.json'")
        else:
            print(f"  ❌ Telegram Connection Error: {bot_name}")
        print("=" * 70 + "\n")
        return

    print(f"🟢 Telegram Connected: @{bot_user} ({bot_name})")
    print(f"🤖 Bot is listening for Telegram messages...")
    print(f"💡 Open Telegram, search for @{bot_user}, and send: /start\n")

    offset = None
    last_sync_time = time.time()

    while True:
        try:
            if time.time() - last_sync_time > 600:
                last_sync_time = time.time()
                if IS_LIVE_MT5 and LEARNING_AVAILABLE and learning_engine:
                    learning_engine.sync_mt5_history()

            url = f"https://api.telegram.org/bot{token}/getUpdates?timeout=20"
            if offset:
                url += f"&offset={offset}"
            req = urllib.request.Request(url, headers={"User-Agent": "MT5TelegramBot/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                updates = json.loads(r.read())

            for u in updates.get("result", []):
                offset = u["update_id"] + 1

                if "message" in u and "text" in u["message"]:
                    msg_text = u["message"]["text"].strip()
                    sender_id = str(u["message"]["chat"]["id"])
                    sender_name = u["message"]["from"].get("first_name", "User")

                    # Auto-capture Chat ID on first use if not yet configured
                    if not chat_id or chat_id in ("YOUR_TELEGRAM_CHAT_ID_HERE", "0", ""):
                        print(f"🔑 Auto-authorized Chat ID: {sender_id} ({sender_name}). Saving to config_telegram.json...")
                        chat_id = sender_id
                        config["telegram"]["chat_id"] = sender_id
                        try:
                            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                                json.dump(config, f, indent=2)
                        except Exception:
                            pass
                    elif sender_id != chat_id:
                        print(f"⚠️ Ignored message from unauthorized Chat ID: {sender_id} (Expected: {chat_id})")
                        continue

                    print(f"📩 [{datetime.now().strftime('%H:%M:%S')}] Received from {sender_name}: '{msg_text}'")

                    if msg_text.startswith("/start") or msg_text.startswith("/help"):
                        acc_text = get_account_summary()
                        mode_label = "🟢 LIVE MT5" if IS_LIVE_MT5 else "📝 PAPER TRADING"
                        welcome = (
                            f"🚀 *Hard-Asset Autotrader Engine ({mode_label})*\n\n"
                            f"{acc_text}\n\n"
                            f"Commands:\n"
                            f"• `/scan` - Run 4-stage confluence scan on Gold & BTC\n"
                            f"• `/status` - Check account balance & open positions\n"
                            f"• `/learn` - View adaptive weights & win-rate attribution\n"
                            f"• `/train` - Run walk-forward self-calibration\n"
                            f"• `/sync` - Synchronize and learn from closed MT5 trades\n"
                            f"• `/execute_btc` - Submit BTC buy order\n"
                            f"• `/execute_gold` - Submit Gold buy order\n"
                        )
                        send_telegram(token, sender_id, welcome)

                    elif msg_text.startswith("/status"):
                        acc_text = get_account_summary()
                        send_telegram(token, sender_id, acc_text)

                    elif msg_text.startswith("/learn") or msg_text.startswith("/weights"):
                        if LEARNING_AVAILABLE and learning_engine:
                            summary = learning_engine.get_summary_text()
                            send_telegram(token, sender_id, f"```\n{summary}\n```")
                        else:
                            send_telegram(token, sender_id, "⚠️ Self-Learning module not available.")

                    elif msg_text.startswith("/train"):
                        send_telegram(token, sender_id, "🧠 Running walk-forward self-training across past 180 days...")
                        if LEARNING_AVAILABLE and learning_engine:
                            trades, wins = learning_engine.train_on_historical_data(lookback_days=180, verbose=False)
                            win_pct = (wins / trades * 100) if trades > 0 else 0
                            send_telegram(token, sender_id, f"✅ Self-Training complete!\n• Trades: `{trades}` | Win Rate: `{win_pct:.1f}%`\nType `/learn` to see updated rankings.")
                        else:
                            send_telegram(token, sender_id, "⚠️ Self-Learning engine not available.")

                    elif msg_text.startswith("/sync"):
                        if IS_LIVE_MT5 and LEARNING_AVAILABLE and learning_engine:
                            cnt, msg = learning_engine.sync_mt5_history()
                            send_telegram(token, sender_id, f"🔄 MT5 History Sync: {msg}")
                        else:
                            send_telegram(token, sender_id, "📝 Running in Paper Mode. No broker history to sync.")

                    elif msg_text.startswith("/scan"):
                        send_telegram(token, sender_id, "⏳ Running multi-factor pipeline scan on Gold & BTC...")
                        data = run_pipeline_scan()
                        m = data["macro"]
                        b = data["btc"]
                        g = data["gold"]

                        btc_ready = b['score'] >= 8 or b['adaptive_score'] >= 8.0
                        gold_ready = g['score'] >= 8 or g['adaptive_score'] >= 8.0

                        btc_status = "🟢 *A+ SETUP (READY)*" if btc_ready else "🔴 *WAIT / VETOED*"
                        gold_status = "🟢 *A+ SETUP (READY)*" if gold_ready else "🔴 *WAIT / VETOED*"

                        mode_tag = "[LIVE MT5]" if IS_LIVE_MT5 else "[PAPER TRADING]"
                        report = (
                            f"📊 *HARD-ASSET CONFLUENCE SCAN {mode_tag}*\n\n"
                            f"🌐 *Macro:* DXY `{m['dxy']:.2f}` ({m['dxy_chg']:+.2f}%) | 10Y `{m['tnx']:.2f}%` | GSR `{m['gsr']:.1f}x`\n\n"
                            f"₿ *Bitcoin:* `${b['price']:,.2f}`\n"
                            f"• Base Score: `{b['score']}/10` | Adaptive: `{b['adaptive_score']:.1f}/10`\n"
                            f"• Verdict: {btc_status}\n"
                            f"• RSI: `{b['rsi']:.1f}` | Mayer: `{b['mayer']:.2f}x`\n\n"
                            f"🥇 *Gold:* `${g['price']:,.2f}`\n"
                            f"• Base Score: `{g['score']}/10` | Adaptive: `{g['adaptive_score']:.1f}/10`\n"
                            f"• Verdict: {gold_status}\n"
                            f"• RSI: `{g['rsi']:.1f}`\n\n"
                            f"Tap below to execute:"
                        )

                        markup = {
                            "inline_keyboard": [
                                [{"text": f"⚡ Buy BTCUSD ({'MT5' if IS_LIVE_MT5 else 'Paper'})", "callback_data": "BUY_BTC"}],
                                [{"text": f"⚡ Buy XAUUSD ({'MT5' if IS_LIVE_MT5 else 'Paper'})", "callback_data": "BUY_GOLD"}]
                            ]
                        }
                        send_telegram(token, sender_id, report, markup)

                    elif msg_text.startswith("/execute_btc"):
                        data = run_pipeline_scan()
                        b = data["btc"]
                        sym = config["mt5"]["symbols"]["BTC"]
                        ok, res = execute_order(sym, "BUY", b["price"], b["sl"], b["tp"], config["mt5"]["risk_pct_per_trade"])
                        send_telegram(token, sender_id, res)

                    elif msg_text.startswith("/execute_gold"):
                        data = run_pipeline_scan()
                        g = data["gold"]
                        sym = config["mt5"]["symbols"]["GOLD"]
                        ok, res = execute_order(sym, "BUY", g["price"], g["sl"], g["tp"], config["mt5"]["risk_pct_per_trade"])
                        send_telegram(token, sender_id, res)

                elif "callback_query" in u:
                    cb = u["callback_query"]
                    cb_data = cb.get("data")
                    sender_id = str(cb["from"]["id"])
                    sender_name = cb["from"].get("first_name", "User")
                    print(f"🔘 [{datetime.now().strftime('%H:%M:%S')}] Button tapped by {sender_name}: '{cb_data}'")
                    data = run_pipeline_scan()

                    if cb_data == "BUY_BTC":
                        b = data["btc"]
                        sym = config["mt5"]["symbols"]["BTC"]
                        ok, res = execute_order(sym, "BUY", b["price"], b["sl"], b["tp"], config["mt5"]["risk_pct_per_trade"])
                        send_telegram(token, sender_id, res)
                    elif cb_data == "BUY_GOLD":
                        g = data["gold"]
                        sym = config["mt5"]["symbols"]["GOLD"]
                        ok, res = execute_order(sym, "BUY", g["price"], g["sl"], g["tp"], config["mt5"]["risk_pct_per_trade"])
                        send_telegram(token, sender_id, res)

        except urllib.error.HTTPError as e:
            if e.code == 401:
                print("❌ Telegram Error: 401 Unauthorized! Invalid bot token.")
                time.sleep(10)
            else:
                print(f"⚠️ Telegram HTTP Error: {e}")
                time.sleep(3)
        except Exception as e:
            print(f"⚠️ Polling loop error: {e}")
            time.sleep(3)


if __name__ == "__main__":
    cfg = load_config()
    if not cfg:
        sys.exit(1)

    print("==================================================================")
    print("  MT5 TELEGRAM REMOTE CONTROL & SELF-LEARNING BOT (PYTHON 3.11)")
    print("==================================================================")
    ok, status = init_mt5(cfg)
    print(f"  * {status}")
    if LEARNING_AVAILABLE:
        print("  * Self-Learning Engine: Online & Connected (learning_memory.json)")
    handle_telegram_updates(cfg)
