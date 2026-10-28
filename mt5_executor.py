#!/usr/bin/env python3
"""
mt5_executor.py
Institutional MetaTrader 5 (MT5) Live Broker Execution Engine.
Calibrated exclusively for Gold (XAU/USD) and Bitcoin (BTC/USD).

Core Features:
  1. 100% LIVE BROKER CONNECTION: Real-time integration with MT5 terminal.
  2. ZERO PAPER TRADING: Only real live broker account data and execution.
  3. REAL-TIME LIVE BALANCE: Queries balance, equity, and free margin directly from MT5.
  4. SMART BROKER SYMBOL RESOLVER: Automatically resolves XAUUSD, XAUUSDm, GOLD, BTCUSD, etc.
  5. HIGH WIN-RATE SNIPER ORDERS: Precision execution with small SL, small TP, and micro lots.
  6. EMERGENCY KILL-SWITCH: Close all positions in one command via /close_all.
  7. AUTO-RECONNECT: Automatically detects and reconnects if MT5 terminal is opened/restarted.
"""

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
import math
import time
from datetime import datetime

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False


# Common symbol variations used across institutional and retail brokers
GOLD_SYMBOL_CANDIDATES = ["XAUUSD", "XAUUSDm", "GOLD", "XAUUSD.a", "XAUUSD.raw", "XAUUSD.ecn", "XAUUSD.s", "XAUUSD.", "GC=F"]
BTC_SYMBOL_CANDIDATES  = ["BTCUSD", "BTCUSDm", "BTC", "BTCUSD.a", "BTCUSD.raw", "BTCUSD.ecn", "BTCUSD.s", "BTCUSD.", "BTC-USD"]


class MT5LiveBroker:
    def __init__(self):
        self.is_connected = False
        self.account_info = None
        self.terminal_info = None
        self.resolved_symbols = {}
        self.last_login = None
        self.last_password = None
        self.last_server = None
        self.last_path = None

    def connect(self, login: int = None, password: str = None, server: str = None, path: str = None) -> tuple:
        """
        Connects to live MetaTrader 5 terminal.
        If credentials provided, logs into the specific account.
        Otherwise, attaches directly to the currently running logged-in terminal.
        """
        if not MT5_AVAILABLE:
            self.is_connected = False
            return False, "MetaTrader5 Python library not installed. Run: py -3.11 -m pip install MetaTrader5"

        self.last_login = login
        self.last_password = password
        self.last_server = server
        self.last_path = path

        # Step 1: Initialize terminal
        init_ok = False
        if path and os.path.exists(path):
            init_ok = mt5.initialize(path=path)
        else:
            init_ok = mt5.initialize()

        if not init_ok:
            err = mt5.last_error()
            self.is_connected = False
            return False, f"MT5 terminal initialization failed: {err}. Ensure MetaTrader 5 is running on your VPS."

        # Step 2: Login if explicit credentials provided
        if login and password and server:
            login_ok = mt5.login(login=int(login), password=str(password), server=str(server))
            if not login_ok:
                err = mt5.last_error()
                self.is_connected = False
                return False, f"MT5 live login failed for account #{login} on {server}: {err}"

        # Step 3: Verify terminal and account status
        term = mt5.terminal_info()
        acc = mt5.account_info()

        if not acc:
            self.is_connected = False
            return False, "Could not fetch MT5 account info. Please ensure you are logged into a live account in MT5."

        self.terminal_info = term
        self.account_info = acc
        self.is_connected = True

        trade_status = "ENABLED ✅" if (term and term.trade_allowed) else "DISABLED ⚠️ (Enable 'Allow Algo Trading' in MT5 Tools -> Options)"

        return True, (
            f"🟢 LIVE MT5 BROKER CONNECTED\n"
            f"• Broker: {acc.company}\n"
            f"• Account: #{acc.login} ({acc.server})\n"
            f"• Balance: ${acc.balance:,.2f} {acc.currency}\n"
            f"• Equity:  ${acc.equity:,.2f} {acc.currency}\n"
            f"• Algo Trading: {trade_status}"
        )

    def ensure_connected(self) -> bool:
        """Verifies active connection and auto-reconnects if disconnected."""
        if not MT5_AVAILABLE:
            return False

        if self.is_connected:
            term = mt5.terminal_info()
            if term is not None:
                self.terminal_info = term
                return True
            self.is_connected = False

        # Attempt auto-reconnect
        ok, _ = self.connect(self.last_login, self.last_password, self.last_server, self.last_path)
        return ok

    def get_live_account_data(self) -> dict:
        """
        Fetches current live equity, balance, and margin directly from MT5.
        Auto-reconnects if connection was temporarily lost.
        Returns None if not connected.
        """
        if not self.ensure_connected():
            return None

        acc = mt5.account_info()
        if not acc:
            self.is_connected = False
            return None

        self.account_info = acc
        positions = mt5.positions_get()
        pos_count = len(positions) if positions else 0

        term = mt5.terminal_info()
        self.terminal_info = term

        return {
            "login": acc.login,
            "broker": acc.company,
            "server": acc.server,
            "balance": acc.balance,
            "equity": acc.equity,
            "margin": acc.margin,
            "margin_free": acc.margin_free,
            "margin_level": acc.margin_level,
            "currency": acc.currency,
            "leverage": acc.leverage,
            "open_positions_count": pos_count,
            "trade_allowed": term.trade_allowed if term else False
        }

    def resolve_symbol(self, asset: str) -> str:
        """
        Finds the exact symbol name supported by the broker's market watch.
        """
        asset_key = "GOLD" if asset.upper() in ("GOLD", "XAU", "XAUUSD", "GC=F") else "BTC"
        if asset_key in self.resolved_symbols:
            return self.resolved_symbols[asset_key]

        if not self.ensure_connected():
            return "XAUUSD" if asset_key == "GOLD" else "BTCUSD"

        candidates = GOLD_SYMBOL_CANDIDATES if asset_key == "GOLD" else BTC_SYMBOL_CANDIDATES

        for sym in candidates:
            info = mt5.symbol_info(sym)
            if info is not None:
                if not info.visible:
                    mt5.symbol_select(sym, True)
                self.resolved_symbols[asset_key] = sym
                return sym

        # Fallback search in all broker symbols
        all_syms = mt5.symbols_get()
        if all_syms:
            for s in all_syms:
                name_upper = s.name.upper()
                if asset_key == "GOLD" and ("XAU" in name_upper or "GOLD" in name_upper):
                    mt5.symbol_select(s.name, True)
                    self.resolved_symbols[asset_key] = s.name
                    return s.name
                elif asset_key == "BTC" and ("BTC" in name_upper and "USD" in name_upper):
                    mt5.symbol_select(s.name, True)
                    self.resolved_symbols[asset_key] = s.name
                    return s.name

        default_sym = "XAUUSD" if asset_key == "GOLD" else "BTCUSD"
        self.resolved_symbols[asset_key] = default_sym
        return default_sym

    def execute_live_sniper_order(self, asset: str, action: str,
                                  entry_price: float, stop_loss: float,
                                  take_profit: float, lot_size: float,
                                  comment: str = "GoldBTC-Sniper") -> dict:
        """
        Executes an instant market order directly on the live MT5 broker.
        Enforces small lot sizes, small SL, and small TP anchored to live fill price.
        """
        if not self.ensure_connected():
            return {"success": False, "error": "MT5 is disconnected. Please ensure MT5 terminal is running on your VPS."}

        term = mt5.terminal_info()
        if term is None:
            self.is_connected = False
            return {"success": False, "error": "MT5 terminal is not responding or disconnected."}

        if not term.trade_allowed:
            return {"success": False, "error": "Algo Trading is DISABLED in MT5. Go to Tools -> Options -> Expert Advisors -> Allow algorithmic trading."}

        symbol = self.resolve_symbol(asset)
        sym_info = mt5.symbol_info(symbol)
        if not sym_info:
            return {"success": False, "error": f"Symbol '{symbol}' not recognized by broker."}

        if not sym_info.visible:
            mt5.symbol_select(symbol, True)

        # Enforce broker lot limits and step alignment
        min_lot = sym_info.volume_min or 0.01
        max_lot = min(sym_info.volume_max or 50.0, 1.0)  # Conservative live cap (max 1.0 lot)
        step_lot = sym_info.volume_step or 0.01

        steps = math.floor(lot_size / step_lot) if step_lot > 0 else 1
        aligned_lot = steps * step_lot
        valid_lot = max(min_lot, min(aligned_lot, max_lot))

        step_decimals = max(0, -int(math.floor(math.log10(step_lot)))) if (step_lot > 0 and step_lot < 1) else 2
        valid_lot = round(valid_lot, step_decimals)

        is_buy = action.upper() in ("BUY", "LONG")
        order_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL

        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return {"success": False, "error": f"Could not fetch live price tick for '{symbol}'."}

        fill_price = tick.ask if is_buy else tick.bid
        digits = sym_info.digits
        point = sym_info.point or (10 ** -digits)

        # Calculate exact SL and TP distances from entry and anchor to live fill_price
        sl_dist = abs(entry_price - stop_loss) if (entry_price > 0 and stop_loss > 0) else (5.0 if "XAU" in symbol or "GOLD" in symbol else 400.0)
        tp_dist = abs(take_profit - entry_price) if (entry_price > 0 and take_profit > 0) else (sl_dist * 1.20)

        # Respect broker's minimum stops level
        stops_level_pts = sym_info.trade_stops_level or 0
        min_stop_dist = (stops_level_pts + 5) * point
        if sl_dist < min_stop_dist:
            sl_dist = min_stop_dist
        if tp_dist < min_stop_dist:
            tp_dist = min_stop_dist

        final_sl = round(fill_price - sl_dist if is_buy else fill_price + sl_dist, digits)
        final_tp = round(fill_price + tp_dist if is_buy else fill_price - tp_dist, digits)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": valid_lot,
            "type": order_type,
            "price": fill_price,
            "sl": final_sl,
            "tp": final_tp,
            "deviation": 25,
            "magic": 999888,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        # First attempt with IOC, fallback to FOK or RETURN if broker requires
        res = mt5.order_send(request)
        if res is None:
            err = mt5.last_error()
            return {"success": False, "error": f"MT5 order_send returned None: {err}"}

        if res.retcode != mt5.TRADE_RETCODE_DONE:
            for filling in [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]:
                request["type_filling"] = filling
                res = mt5.order_send(request)
                if res is not None and res.retcode == mt5.TRADE_RETCODE_DONE:
                    break

        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            comment_str = res.comment if res else str(mt5.last_error())
            retcode_val = res.retcode if res else -1
            return {
                "success": False,
                "retcode": retcode_val,
                "error": f"MT5 Broker Rejected ({retcode_val}): {comment_str}"
            }

        return {
            "success": True,
            "ticket": res.order,
            "symbol": symbol,
            "action": action.upper(),
            "lots": valid_lot,
            "price": res.price or fill_price,
            "sl": final_sl,
            "tp": final_tp,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

    def get_open_positions(self) -> list:
        """Fetches all currently open live positions."""
        if not self.ensure_connected():
            return []

        positions = mt5.positions_get()
        if not positions:
            return []

        results = []
        for p in positions:
            p_type = "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL"
            results.append({
                "ticket": p.ticket,
                "symbol": p.symbol,
                "type": p_type,
                "lots": p.volume,
                "open_price": p.price_open,
                "current_price": p.price_current,
                "sl": p.sl,
                "tp": p.tp,
                "profit": p.profit,
                "time": datetime.fromtimestamp(p.time).strftime("%Y-%m-%d %H:%M:%S") if p.time else ""
            })
        return results

    def close_all_positions(self) -> dict:
        """Emergency circuit breaker: Closes all open live positions immediately."""
        if not self.ensure_connected():
            return {"success": False, "closed_count": 0, "error": "MT5 Disconnected. Open MT5 on your VPS."}

        positions = mt5.positions_get()
        if not positions:
            return {"success": True, "closed_count": 0, "msg": "No open positions to close."}

        closed = 0
        total_pnl = 0.0

        for p in positions:
            symbol = p.symbol
            tick = mt5.symbol_info_tick(symbol)
            if not tick:
                continue

            order_type = mt5.ORDER_TYPE_SELL if p.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
            price = tick.bid if p.type == mt5.ORDER_TYPE_BUY else tick.ask

            req = {
                "action": mt5.TRADE_ACTION_DEAL,
                "position": p.ticket,
                "symbol": symbol,
                "volume": p.volume,
                "type": order_type,
                "price": price,
                "deviation": 35,
                "magic": 999888,
                "comment": "Close-All-Trigger",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC
            }
            res = mt5.order_send(req)
            if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
                for filling in [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]:
                    req["type_filling"] = filling
                    res = mt5.order_send(req)
                    if res is not None and res.retcode == mt5.TRADE_RETCODE_DONE:
                        break

            if res is not None and res.retcode == mt5.TRADE_RETCODE_DONE:
                closed += 1
                total_pnl += p.profit

        return {
            "success": True,
            "closed_count": closed,
            "total_pnl": total_pnl,
            "remaining": len(positions) - closed
        }

    def has_open_position(self, asset: str) -> bool:
        """Returns True if a live position for this asset is already open in MT5."""
        if not self.ensure_connected():
            return False
        symbol = self.resolve_symbol(asset)
        positions = mt5.positions_get(symbol=symbol)
        return positions is not None and len(positions) > 0

    def get_live_1m_rates(self, asset: str, count: int = 60):
        """Fetches the latest N 1-minute candles directly from the live broker."""
        if not self.ensure_connected():
            return None
        symbol = self.resolve_symbol(asset)
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, count)
        if rates is None or len(rates) == 0:
            return None
        import pandas as pd
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        return df


# Global Singleton Instance
live_broker = MT5LiveBroker()
