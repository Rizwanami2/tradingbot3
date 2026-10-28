#!/usr/bin/env python3
"""
trader-gold-btc: mt5_telegram_bot.py
Unified Institutional Telegram Remote Control & MetaTrader 5 (MT5) Execution Engine
with Autonomous Self-Learning & Adaptive Weight Optimization.
Compatible with Python 3.11+.

Commands supported in Telegram:
  /start   - Initialize session, display MT5 account balance & equity
  /scan    - Run the 4-stage confluence scan on Gold & BTC (Base + Learned Adaptive Scores)
  /status  - Display MT5 open positions & macro indicators (DXY, 10Y Yield, F&G)
  /learn   - Display current learned factor weights, trade stats & win-rate attribution
  /train   - Trigger walk-forward self-training across historical price action
  /sync    - Sync and learn from closed MT5 trade history
  /help    - Command reference
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

# Import Self-Learning Engine
try:
    from self_learning import SelfLearningEngine
    learning_engine = SelfLearningEngine()
    LEARNING_AVAILABLE = True
except Exception:
    learning_engine = None
    LEARNING_AVAILABLE = False


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
        payload["reply_markup"] = reply_markup

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"⚠️ Telegram send error: {e}")
        return None


def init_mt5():
    if not MT5_AVAILABLE:
        return False, "MetaTrader5 module not installed"
    
    if not mt5.initialize():
        err = mt5.last_error()
        return False, f"MT5 initialize() failed: {err}"
    
    terminal_info = mt5.terminal_info()
    account_info = mt5.account_info()
    
    if not terminal_info.trade_allowed:
        return False, "MT5 Trade is disabled! Please enable 'Allow Algo Trading' in MT5 Tools -> Options -> Expert Advisors"
    
    acc_id = account_info.login if account_info else "Unknown"
    balance = account_info.balance if account_info else 0.0
    return True, f"Connected to MT5 Account #{acc_id} | Balance: ${balance:,.2f}"


def get_mt5_account_summary():
    if not MT5_AVAILABLE or not mt5.initialize():
        return "⚠️ MT5 not connected or Algo Trading disabled."
    
    acc = mt5.account_info()
    if not acc:
        return "⚠️ Could not retrieve account details."

    positions = mt5.positions_get()
    pos_count = len(positions) if positions else 0

    text = (
        f"🏦 *MT5 Account Summary:*\n"
        f"• Account ID: `{acc.login}`\n"
        f"• Broker: `{acc.company}`\n"
        f"• Balance: `${acc.balance:,.2f}`\n"
        f"• Equity: `${acc.equity:,.2f}`\n"
        f"• Free Margin: `${acc.margin_free:,.2f}`\n"
        f"• Open Positions: `{pos_count}`"
    )
    if pos_count > 0:
        text += "\n\n📋 *Active Trades:*"
        for p in positions:
            p_type = "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL"
            text += f"\n• `{p.symbol}` {p_type} `{p.volume}` lots @ `${p.price_open:,.2f}` | PnL: `${p.profit:+,.2f}`"

    return text


def calculate_lot_size(symbol: str, risk_amount: float, entry: float, stop_loss: float) -> float:
    if not MT5_AVAILABLE:
        return 0.01

    sym_info = mt5.symbol_info(symbol)
    if not sym_info:
        return 0.01

    sl_dist = abs(entry - stop_loss)
    if sl_dist == 0:
        return sym_info.volume_min

    tick_size = sym_info.trade_tick_size or 0.01
    tick_val = sym_info.trade_tick_value or 1.0

    risk_per_lot = (sl_dist / tick_size) * tick_val
    if risk_per_lot <= 0:
        return sym_info.volume_min

    lots = risk_amount / risk_per_lot
    
    step = sym_info.volume_step or 0.01
    lots = round(lots / step) * step
    lots = max(sym_info.volume_min, min(lots, sym_info.volume_max))
    return round(lots, 2)


def place_mt5_order(symbol: str, action: str, entry: float, sl: float, tp: float, risk_pct: float = 1.0):
    if not MT5_AVAILABLE or not mt5.initialize():
        return False, "MT5 not connected."

    sym_info = mt5.symbol_info(symbol)
    if not sym_info:
        return False, f"Symbol '{symbol}' not found in MT5."

    if not sym_info.visible:
        mt5.symbol_select(symbol, True)

    acc = mt5.account_info()
    balance = acc.balance if acc else 10000.0
    risk_amount = balance * (risk_pct / 100.0)

    lot_size = calculate_lot_size(symbol, risk_amount, entry, sl)
    order_type = mt5.ORDER_TYPE_BUY if action.upper() == "BUY" else mt5.ORDER_TYPE_SELL
    price = mt5.symbol_info_tick(symbol).ask if action.upper() == "BUY" else mt5.symbol_info_tick(symbol).bid

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot_size,
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

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        return False, f"Order failed (Code {result.retcode}): {result.comment}"

    # Log to Self-Learning journal
    if LEARNING_AVAILABLE and learning_engine:
        asset = "BTC" if "BTC" in symbol.upper() else "GOLD"
        feat = {
            "in_golden_pocket": True, "no_trap": True, "macro_dxy_tailwind": True,
            "macro_yield_tailwind": True, "trend_ma200": True, "trend_ma50": True,
            "rsi_sweet_spot": True, "mayer_sweet_spot": True if asset == "BTC" else False,
            "gsr_undervalued": True if asset == "GOLD" else False, "volatility_orderly": True,
            "near_swing_support": True
        }
        learning_engine.log_signal(asset, symbol, price, sl, tp, tp * 1.05, 8.5, feat)

    return True, f"✅ Order Executed: {action} {lot_size} lots {symbol} @ ${price:,.2f} | Ticket: #{result.order}"


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
    token = config["telegram"]["bot_token"]
    chat_id = config["telegram"]["chat_id"]

    if token == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        print("\n⚠️ Please configure your bot token and chat_id in 'config_telegram.json' first.")
        print(f"File location: {CONFIG_PATH}\n")
        return

    print("🤖 Telegram Bot Polling Active... Waiting for commands.")
    offset = None
    last_sync_time = time.time()

    while True:
        try:
            # Auto-sync MT5 closed trade history every 10 minutes
            if time.time() - last_sync_time > 600:
                last_sync_time = time.time()
                if LEARNING_AVAILABLE and learning_engine:
                    learning_engine.sync_mt5_history()

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

                    if sender_id != str(chat_id):
                        continue

                    if msg_text.startswith("/start") or msg_text.startswith("/help"):
                        acc_text = get_mt5_account_summary()
                        welcome = (
                            f"🚀 *Hard-Asset Autotrader & Self-Learning Engine*\n\n"
                            f"{acc_text}\n\n"
                            f"Commands:\n"
                            f"• `/scan` - Run 4-stage confluence scan on Gold & BTC\n"
                            f"• `/status` - Check MT5 account balance & open orders\n"
                            f"• `/learn` - View adaptive weights & win-rate attribution\n"
                            f"• `/train` - Run walk-forward historical self-calibration\n"
                            f"• `/sync` - Synchronize and learn from closed MT5 trades\n"
                            f"• `/execute_btc` - Submit BTC market buy with brackets\n"
                            f"• `/execute_gold` - Submit Gold market buy with brackets\n"
                        )
                        send_telegram(token, chat_id, welcome)

                    elif msg_text.startswith("/status"):
                        acc_text = get_mt5_account_summary()
                        send_telegram(token, chat_id, acc_text)

                    elif msg_text.startswith("/learn") or msg_text.startswith("/weights"):
                        if LEARNING_AVAILABLE and learning_engine:
                            summary = learning_engine.get_summary_text()
                            send_telegram(token, chat_id, f"```\n{summary}\n```")
                        else:
                            send_telegram(token, chat_id, "⚠️ Self-Learning module not available.")

                    elif msg_text.startswith("/train"):
                        send_telegram(token, chat_id, "🧠 Initiating walk-forward self-training across past 180 days...")
                        if LEARNING_AVAILABLE and learning_engine:
                            trades, wins = learning_engine.train_on_historical_data(lookback_days=180, verbose=False)
                            win_pct = (wins / trades * 100) if trades > 0 else 0
                            send_telegram(token, chat_id, f"✅ Self-Training complete!\n• Trades Evaluated: `{trades}`\n• Win Rate: `{win_pct:.1f}%`\n• Weights updated in `learning_memory.json`.\nType `/learn` to see new rankings.")
                        else:
                            send_telegram(token, chat_id, "⚠️ Self-Learning engine not available.")

                    elif msg_text.startswith("/sync"):
                        if LEARNING_AVAILABLE and learning_engine:
                            cnt, msg = learning_engine.sync_mt5_history()
                            send_telegram(token, chat_id, f"🔄 MT5 History Sync: {msg}")
                        else:
                            send_telegram(token, chat_id, "⚠️ Self-Learning module not available.")

                    elif msg_text.startswith("/scan"):
                        send_telegram(token, chat_id, "⏳ Running multi-factor pipeline scan on Gold & BTC...")
                        data = run_pipeline_scan()
                        m = data["macro"]
                        b = data["btc"]
                        g = data["gold"]

                        btc_ready = b['score'] >= 8 or b['adaptive_score'] >= 8.0
                        gold_ready = g['score'] >= 8 or g['adaptive_score'] >= 8.0

                        btc_status = "🟢 *A+ SETUP (READY)*" if btc_ready else "🔴 *WAIT / VETOED*"
                        gold_status = "🟢 *A+ SETUP (READY)*" if gold_ready else "🔴 *WAIT / VETOED*"

                        report = (
                            f"📊 *HARD-ASSET CONFLUENCE SCAN*\n\n"
                            f"🌐 *Macro:* DXY `{m['dxy']:.2f}` ({m['dxy_chg']:+.2f}%) | 10Y `{m['tnx']:.2f}%` | GSR `{m['gsr']:.1f}x`\n\n"
                            f"₿ *Bitcoin:* `${b['price']:,.2f}`\n"
                            f"• Base Score: `{b['score']}/10` | Adaptive: `{b['adaptive_score']:.1f}/10`\n"
                            f"• Verdict: {btc_status}\n"
                            f"• RSI: `{b['rsi']:.1f}` | Mayer: `{b['mayer']:.2f}x`\n\n"
                            f"🥇 *Gold:* `${g['price']:,.2f}`\n"
                            f"• Base Score: `{g['score']}/10` | Adaptive: `{g['adaptive_score']:.1f}/10`\n"
                            f"• Verdict: {gold_status}\n"
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

        except Exception:
            time.sleep(2)


if __name__ == "__main__":
    cfg = load_config()
    if not cfg:
        print("[!] Could not load config_telegram.json")
        sys.exit(1)

    print("==================================================================")
    print("  MT5 TELEGRAM REMOTE CONTROL & SELF-LEARNING BOT (PYTHON 3.11)")
    print("==================================================================")
    ok, status = init_mt5()
    print(f"  * {status}")
    if LEARNING_AVAILABLE:
        print("  * Self-Learning Engine: Online & Connected (learning_memory.json)")
    handle_telegram_updates(cfg)
