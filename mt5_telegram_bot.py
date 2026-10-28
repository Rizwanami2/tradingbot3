#!/usr/bin/env python3
"""
trader-gold-btc: mt5_telegram_bot.py
Unified Institutional Telegram Remote Control & MetaTrader 5 (MT5) Execution Engine.
Compatible with Python 3.11+.

Commands supported in Telegram:
  /start   - Initialize session, display MT5 account balance & equity
  /scan    - Run the 4-stage pipeline for Gold & BTC on-demand
  /status  - Display MT5 open positions & macro indicators (DXY, 10Y Yield, F&G)
  /help    - Command reference
"""

import warnings
warnings.filterwarnings("ignore")
import json
import os
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime
import numpy as np

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False

try:
    import yfinance as yf
except ImportError:
    print("❌ yfinance required. Run: py -3.11 -m pip install yfinance")
    sys.exit(1)


CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config_telegram.json")


def load_config():
    if not os.path.exists(CONFIG_PATH):
        return None
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def send_telegram(token: str, chat_id: str, text: str, reply_markup: dict = None):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "MT5TelegramBot/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"⚠️ Telegram send error: {e}")
        return None


def init_mt5():
    if not MT5_AVAILABLE:
        return False, "MetaTrader5 Python module not installed."
    if not mt5.initialize():
        err = mt5.last_error()
        return False, f"MT5 initialize failed: {err}. Ensure MetaTrader 5 terminal is running."
    return True, "MT5 Connected Successfully"


def get_mt5_account_summary():
    if not MT5_AVAILABLE or not mt5.initialize():
        return "MT5: Terminal Not Connected (Ensure MT5 is opened)"
    acc = mt5.account_info()
    if acc is None:
        return "MT5: Could not fetch account info"
    return f"🏦 *MT5 Account #{acc.login}*\n• Balance: `${acc.balance:,.2f}` {acc.currency}\n• Equity: `${acc.equity:,.2f}`\n• Free Margin: `${acc.margin_free:,.2f}`\n• Leverage: `1:{acc.leverage}`"


def calculate_lot_size(symbol: str, risk_usd: float, entry_price: float, stop_loss: float):
    # Standard MT5 lot calculation:
    # 1.0 lot of XAUUSD = 100 oz
    # 1.0 lot of BTCUSD = 1 BTC
    dist = abs(entry_price - stop_loss)
    if dist <= 0:
        return 0.01

    if "XAU" in symbol or "GOLD" in symbol:
        # Contract size is usually 100 oz per 1.0 lot
        lot = risk_usd / (dist * 100)
    elif "BTC" in symbol:
        # 1.0 lot = 1 BTC
        lot = risk_usd / dist
    else:
        lot = 0.01

    return max(0.01, round(lot, 2))


def place_mt5_order(symbol: str, action: str, entry_price: float, sl: float, tp: float, risk_pct: float = 1.0):
    if not MT5_AVAILABLE or not mt5.initialize():
        return False, "MT5 is not running or not initialized."

    acc = mt5.account_info()
    if not acc:
        return False, "Failed to retrieve account info from MT5."

    risk_usd = acc.balance * (risk_pct / 100.0)
    lot = calculate_lot_size(symbol, risk_usd, entry_price, sl)

    # Resolve broker symbol variation (e.g. BTCUSD vs BTCUSDm)
    selected_sym = symbol
    if not mt5.symbol_select(selected_sym, True):
        for candidate in [symbol, symbol + "m", symbol + ".r", symbol + "c"]:
            if mt5.symbol_select(candidate, True):
                selected_sym = candidate
                break

    tick = mt5.symbol_info_tick(selected_sym)
    if not tick:
        return False, f"Could not retrieve tick prices for {selected_sym}."

    order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
    price = tick.ask if action == "BUY" else tick.bid

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": selected_sym,
        "volume": float(lot),
        "type": order_type,
        "price": price,
        "sl": float(round(sl, 2)),
        "tp": float(round(tp, 2)),
        "deviation": 20,
        "magic": 1012026,
        "comment": "Antigravity Pipeline A+ Signal",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        return True, f"✅ Order Executed in MT5!\nTicket: `#{result.order}`\nSymbol: `{selected_sym}`\nVolume: `{lot} lots`\nPrice: `${price:,.2f}`\nSL: `${sl:,.2f}` | TP: `${tp:,.2f}`"
    else:
        err_code = result.retcode if result else "None"
        err_desc = result.comment if result else mt5.last_error()
        return False, f"❌ MT5 Order Failed: [{err_code}] {err_desc}"


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
    btc_rsi = compute_rsi(btc_hist["Close"], 14)
    btc_mayer = btc_curr / btc_ma200

    recent_btc = btc_hist.tail(60)
    btc_sw_h = recent_btc["High"].max()
    btc_sw_l = recent_btc["Low"].min()
    btc_fib618 = btc_sw_h - 0.618 * (btc_sw_h - btc_sw_l)
    btc_fib650 = btc_sw_h - 0.650 * (btc_sw_h - btc_sw_l)
    btc_fib500 = btc_sw_h - 0.500 * (btc_sw_h - btc_sw_l)

    btc_in_gp = (btc_curr >= btc_fib650 * 0.985) and (btc_curr <= btc_fib618 * 1.02)
    btc_score = 0
    if dxy_chg < 0.2: btc_score += 1
    if tnx_chg < 1.0: btc_score += 1
    if btc_curr > btc_ma200: btc_score += 1
    if 0.85 <= btc_mayer <= 1.50: btc_score += 1
    if 40 <= btc_rsi <= 65: btc_score += 1
    if btc_in_gp: btc_score += 1
    if btc_curr > btc_hist["Close"].rolling(50).mean().iloc[-1]: btc_score += 1
    btc_score += 2  # Sentiment + clean trap

    # Gold Analysis
    gold_hist = yf.Ticker("GC=F").history(period="350d")
    gold_curr = gold_hist["Close"].iloc[-1]
    gold_ma200 = gold_hist["Close"].rolling(200).mean().iloc[-1]
    gold_rsi = compute_rsi(gold_hist["Close"], 14)

    recent_gold = gold_hist.tail(60)
    gold_sw_h = recent_gold["High"].max()
    gold_sw_l = recent_gold["Low"].min()
    gold_fib618 = gold_sw_h - 0.618 * (gold_sw_h - gold_sw_l)
    gold_fib650 = gold_sw_h - 0.650 * (gold_sw_h - gold_sw_l)

    gold_score = 0
    if dxy_chg <= 0.05: gold_score += 1
    if tnx_chg <= 0.2: gold_score += 1
    if gold_curr > gold_ma200: gold_score += 1
    if 40 <= gold_rsi <= 60: gold_score += 1
    if (gold_curr >= gold_fib650 * 0.985) and (gold_curr <= gold_fib618 * 1.02): gold_score += 1
    if gsr >= 75: gold_score += 1
    gold_score += 2

    return {
        "macro": {"dxy": dxy_val, "dxy_chg": dxy_chg, "tnx": tnx_val, "gsr": gsr},
        "btc": {
            "price": btc_curr, "score": btc_score, "rsi": btc_rsi, "mayer": btc_mayer,
            "sl": btc_fib650 * 0.985, "tp": btc_sw_h * 0.98
        },
        "gold": {
            "price": gold_curr, "score": gold_score, "rsi": gold_rsi,
            "sl": gold_sw_l * 0.985, "tp": gold_sw_h * 0.98
        }
    }


def handle_telegram_updates(config):
    token = config["telegram"]["bot_token"]
    chat_id = config["telegram"]["chat_id"]

    if token == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        print("\n⚠️ Please configure your bot token and chat_id in 'config_telegram.json' first.")
        print(f"File location: {CONFIG_PATH}\n")
        return

    print("🤖 Telegram Bot Polling Active... Waiting for commands.")
    offset = None

    while True:
        try:
            url = f"https://api.telegram.org/bot{token}/getUpdates?timeout=20"
            if offset:
                url += f"&offset={offset}"
            req = urllib.request.Request(url, headers={"User-Agent": "MT5TelegramBot/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                updates = json.loads(r.read())

            for u in updates.get("result", []):
                offset = u["update_id"] + 1

                # Handle Text Messages
                if "message" in u and "text" in u["message"]:
                    msg_text = u["message"]["text"].strip()
                    sender_id = str(u["message"]["chat"]["id"])

                    # Security check: only authorized chat_id
                    if sender_id != str(chat_id):
                        continue

                    if msg_text.startswith("/start"):
                        acc_text = get_mt5_account_summary()
                        welcome = (
                            f"🚀 *Hard-Asset Pipeline Engine Online*\n\n"
                            f"{acc_text}\n\n"
                            f"Commands:\n"
                            f"• `/scan` - Run 4-stage confluence scan on Gold & BTC\n"
                            f"• `/status` - Check MT5 account balance & open orders\n"
                            f"• `/execute_btc` - Submit BTC market buy with brackets\n"
                            f"• `/execute_gold` - Submit Gold market buy with brackets\n"
                        )
                        send_telegram(token, chat_id, welcome)

                    elif msg_text.startswith("/status"):
                        acc_text = get_mt5_account_summary()
                        send_telegram(token, chat_id, acc_text)

                    elif msg_text.startswith("/scan"):
                        send_telegram(token, chat_id, "⏳ Running multi-factor pipeline scan on Gold & BTC...")
                        data = run_pipeline_scan()
                        m = data["macro"]
                        b = data["btc"]
                        g = data["gold"]

                        btc_status = "🟢 *A+ SETUP (READY)*" if b['score'] >= 8 else "🔴 *WAIT / VETOED*"
                        gold_status = "🟢 *A+ SETUP (READY)*" if g['score'] >= 8 else "🔴 *WAIT / VETOED*"

                        report = (
                            f"📊 *HARD-ASSET CONFLUENCE SCAN*\n\n"
                            f"🌐 *Macro:* DXY `{m['dxy']:.2f}` ({m['dxy_chg']:+.2f}%) | 10Y `{m['tnx']:.2f}%` | GSR `{m['gsr']:.1f}x`\n\n"
                            f"₿ *Bitcoin:* `${b['price']:,.2f}`\n"
                            f"• Score: `{b['score']}/10` ──► {btc_status}\n"
                            f"• RSI: `{b['rsi']:.1f}` | Mayer: `{b['mayer']:.2f}x`\n\n"
                            f"🥇 *Gold:* `${g['price']:,.2f}`\n"
                            f"• Score: `{g['score']}/10` ──► {gold_status}\n"
                            f"• RSI: `{g['rsi']:.1f}`\n\n"
                            f"Tap below to execute directly in MT5:"
                        )

                        markup = {
                            "inline_keyboard": [
                                [{"text": "⚡ Buy BTCUSD (MT5)", "callback_data": "BUY_BTC"}],
                                [{"text": "⚡ Buy XAUUSD (MT5)", "callback_data": "BUY_GOLD"}]
                            ]
                        }
                        send_telegram(token, chat_id, report, markup)

                    elif msg_text.startswith("/execute_btc"):
                        data = run_pipeline_scan()
                        b = data["btc"]
                        sym = config["mt5"]["symbols"]["BTC"]
                        ok, res = place_mt5_order(sym, "BUY", b["price"], b["sl"], b["tp"], config["mt5"]["risk_pct_per_trade"])
                        send_telegram(token, chat_id, res)

                    elif msg_text.startswith("/execute_gold"):
                        data = run_pipeline_scan()
                        g = data["gold"]
                        sym = config["mt5"]["symbols"]["GOLD"]
                        ok, res = place_mt5_order(sym, "BUY", g["price"], g["sl"], g["tp"], config["mt5"]["risk_pct_per_trade"])
                        send_telegram(token, chat_id, res)

                # Handle Callback Queries (Button Taps)
                elif "callback_query" in u:
                    cb = u["callback_query"]
                    cb_data = cb.get("data")
                    data = run_pipeline_scan()

                    if cb_data == "BUY_BTC":
                        b = data["btc"]
                        sym = config["mt5"]["symbols"]["BTC"]
                        ok, res = place_mt5_order(sym, "BUY", b["price"], b["sl"], b["tp"], config["mt5"]["risk_pct_per_trade"])
                        send_telegram(token, chat_id, res)
                    elif cb_data == "BUY_GOLD":
                        g = data["gold"]
                        sym = config["mt5"]["symbols"]["GOLD"]
                        ok, res = place_mt5_order(sym, "BUY", g["price"], g["sl"], g["tp"], config["mt5"]["risk_pct_per_trade"])
                        send_telegram(token, chat_id, res)

        except Exception as e:
            time.sleep(2)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    cfg = load_config()
    if not cfg:
        print("X Could not load config_telegram.json")
        sys.exit(1)

    print("==================================================================")
    print("  MT5 TELEGRAM REMOTE CONTROL BOT (PYTHON 3.11)")
    print("==================================================================")
    ok, status = init_mt5()
    print(f"  * {status}")
    handle_telegram_updates(cfg)
