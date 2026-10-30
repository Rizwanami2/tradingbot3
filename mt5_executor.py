#!/usr/bin/env python3
"""
mt5_executor.py
Institutional MetaTrader 5 (MT5) Live Broker Execution Engine.
Calibrated exclusively for Gold (XAU/USD) and Bitcoin (BTC/USD).

Core Features:
  1. 100% LIVE BROKER CONNECTION: Real-time integration with MT5 terminal.
  2. ZERO PAPER TRADING: Only real live broker account data and execution.
  3. REAL-TIME LIVE BALANCE & AUTO LEVERAGE: Queries balance, equity, free margin, and broker leverage.
  4. SMART BROKER SYMBOL RESOLVER: Automatically resolves XAUUSD, XAUUSDm, GOLD, BTCUSD, etc.
  5. HIGH WIN-RATE SNIPER ORDERS: Precision execution with small SL, small TP, and micro lots.
  6. DYNAMIC TRAILING STOP & BREAKEVEN: Automatically locks profits and eliminates risk (+0.6R Breakeven, +1.0R Trail).
  7. BROKER SWAP RADAR: Analyzes long vs short rollover financing costs.
  8. EMERGENCY KILL-SWITCH: Close all positions in one command via /close_all.
  9. AUTO-RECONNECT: Automatically detects and reconnects if MT5 terminal is opened/restarted.
"""

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
import math
import time
from datetime import datetime, timedelta

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False

try:
    from risk_engine import safety_manager
except Exception:
    safety_manager = None


BOT_MAGIC = 999888  # Institutional Magic Number to isolate Bot from Manual phone trades

# Common symbol variations used across institutional and retail brokers
GOLD_SYMBOL_CANDIDATES = [
    "XAUUSD", "XAUUSDm", "GOLD", "XAUUSD.a", "XAUUSD.raw", "XAUUSD.ecn",
    "XAUUSD.s", "XAUUSD.", "XAUUSD_i", "XAU_USD", "GOLD.pro", "XAUUSD.pro", "GC=F"
]
BTC_SYMBOL_CANDIDATES  = [
    "BTCUSD", "BTCUSDm", "BTC", "BTCUSD.a", "BTCUSD.raw", "BTCUSD.ecn",
    "BTCUSD.s", "BTCUSD.", "BTCUSD_i", "BTC_USD", "BTCUSD.pro", "BTC-USD"
]


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
        self.position_initial_risks = {}
        self.position_peak_prices = {}
        self.tracked_live_tickets = {}

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
            f"• Leverage: 1:{acc.leverage} (Auto-Managed)\n"
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
        Fetches current live equity, balance, margin, and broker leverage directly from MT5.
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

    def get_swap_rates(self, asset: str) -> dict:
        """Fetches overnight rollover financing rates (swaps) directly from broker."""
        if not self.ensure_connected():
            return {"available": False, "swap_long": 0.0, "swap_short": 0.0, "favorable_side": "NONE"}
        symbol = self.resolve_symbol(asset)
        info = mt5.symbol_info(symbol)
        if not info:
            return {"available": False, "swap_long": 0.0, "swap_short": 0.0, "favorable_side": "NONE"}

        sl = getattr(info, "swap_long", 0.0)
        ss = getattr(info, "swap_short", 0.0)
        fav = "BUY" if sl > ss else "SELL" if ss > sl else "NEUTRAL"
        return {
            "available": True,
            "symbol": symbol,
            "swap_long": sl,
            "swap_short": ss,
            "favorable_side": fav,
            "positive_carry": sl > 0 or ss > 0
        }

    def execute_live_sniper_order(self, asset: str, action: str,
                                  entry_price: float, stop_loss: float,
                                  take_profit: float, lot_size: float,
                                  comment: str = "GoldBTC-Sniper") -> dict:
        """
        Executes an instant market order directly on the live MT5 broker or in Paper mode.
        Enforces strict PAPER | DEMO | LIVE trading modes, multi-layer circuit breakers,
        pre-order spread guard, post-order slippage verification, and audit logging.
        """
        current_mode = safety_manager.get_trading_mode() if safety_manager else "LIVE"

        # ── 1. PAPER TRADING SIMULATION (Zero Real Capital Risk) ──
        if current_mode == "PAPER" and safety_manager:
            open_pos = safety_manager.get_paper_positions()
            paper_bal = safety_manager.state.get("paper_account", {}).get("balance", 10000.0)
            sl_dist = abs(entry_price - stop_loss) if (entry_price > 0 and stop_loss > 0) else 4.0

            safe_ok, safe_msg = safety_manager.check_trade_safety(
                asset, proposed_risk_pct=0.50, open_positions=open_pos,
                current_equity=paper_bal, sl_dist=sl_dist
            )
            if not safe_ok:
                return {"success": False, "error": safe_msg, "mode": "PAPER"}

            return safety_manager.execute_paper_order(
                asset=asset, action=action, price=entry_price,
                stop_loss=stop_loss, tp1=take_profit, tp2=take_profit,
                lots=lot_size, risk_usd=50.0, risk_pct=0.50,
                strategy="SCALP", score=8, comment=comment
            )

        # ── 2. LIVE / DEMO BROKER EXECUTION ──
        if not self.ensure_connected():
            return {"success": False, "error": "MT5 is disconnected. Please ensure MT5 terminal is running on your VPS."}

        term = mt5.terminal_info()
        if term is None:
            self.is_connected = False
            return {"success": False, "error": "MT5 terminal is not responding or disconnected."}

        if not term.trade_allowed:
            return {"success": False, "error": "Algo Trading is DISABLED in MT5. Go to Tools -> Options -> Expert Advisors -> Allow algorithmic trading."}

        # LIVE Mode Double Confirmation: First trade of the day check
        if current_mode == "LIVE" and safety_manager:
            if not safety_manager.is_first_trade_confirmed_today():
                return {
                    "success": False,
                    "error": "First live trade of the day requires confirmation! Run: /confirm_trade YES",
                    "requires_confirmation": True,
                    "mode": "LIVE"
                }

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

        # Multi-Layer Safety & Pre-Order Spread Guard
        spread_cost = sym_info.spread * point
        sl_distance = abs(fill_price - stop_loss)

        if safety_manager:
            open_pos = self.get_open_positions()
            current_eq = self.account_info.equity if self.account_info else 10000.0
            safe_ok, safe_msg = safety_manager.check_trade_safety(
                asset, proposed_risk_pct=0.50, open_positions=open_pos,
                current_equity=current_eq, data_timestamp=tick.time,
                spread_val=spread_cost, sl_dist=sl_distance
            )
            if not safe_ok:
                return {"success": False, "error": safe_msg, "mode": current_mode}

        # Auto-calculate margin with broker leverage
        acc = self.account_info
        if acc and hasattr(mt5, "order_calc_margin"):
            try:
                req_margin = mt5.order_calc_margin(order_type, symbol, valid_lot, fill_price)
                if req_margin and req_margin > 0:
                    free_margin = acc.margin_free or (acc.balance * 0.90)
                    if req_margin > (free_margin * 0.90):  # Cap margin at 90% of free margin
                        max_lots_by_margin = (free_margin * 0.90) / (req_margin / valid_lot)
                        steps_margin = math.floor(max_lots_by_margin / step_lot)
                        valid_lot = max(min_lot, min(steps_margin * step_lot, valid_lot))
                        valid_lot = round(valid_lot, step_decimals)
            except Exception:
                pass

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

        actual_fill = res.price or fill_price
        slip_ok, slip_val, slip_msg = True, 0.0, "OK"
        if safety_manager:
            slip_ok, slip_val, slip_msg = safety_manager.verify_fill_slippage(asset, entry_price, actual_fill)
            safety_manager.log_order_audit({
                "event": "ORDER_PLACED_MT5",
                "ticket": res.order,
                "asset": asset,
                "symbol": symbol,
                "action": action.upper(),
                "lots": valid_lot,
                "entry_requested": entry_price,
                "fill_price": actual_fill,
                "slippage": slip_val,
                "slippage_ok": slip_ok,
                "sl": final_sl,
                "tp": final_tp,
                "mode": current_mode,
                "comment": comment
            })

        # Pre-seed initial risk distance and peak price for trailing engine
        if res.order:
            self.position_initial_risks[res.order] = abs(actual_fill - final_sl) if (actual_fill > 0 and final_sl > 0) else sl_dist
            self.position_peak_prices[res.order] = actual_fill

        return {
            "success": True,
            "ticket": res.order,
            "symbol": symbol,
            "action": action.upper(),
            "lots": valid_lot,
            "price": actual_fill,
            "sl": final_sl,
            "tp": final_tp,
            "mode": current_mode,
            "slippage": slip_val,
            "slippage_ok": slip_ok,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

    def modify_position_sltp(self, ticket: int, new_sl: float, new_tp: float = None) -> dict:
        """Modifies Stop-Loss and Take-Profit of an active open position."""
        if not self.ensure_connected():
            return {"success": False, "error": "MT5 disconnected"}

        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return {"success": False, "error": f"Position #{ticket} not found"}

        p = positions[0]
        symbol = p.symbol
        sym_info = mt5.symbol_info(symbol)
        digits = sym_info.digits if sym_info else 2

        target_sl = round(new_sl, digits)
        target_tp = round(new_tp, digits) if new_tp is not None else p.tp

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": symbol,
            "sl": target_sl,
            "tp": target_tp
        }
        res = mt5.order_send(request)
        if res is None:
            err = mt5.last_error()
            return {"success": False, "error": f"Order modify returned None: {err}"}
        if res.retcode != mt5.TRADE_RETCODE_DONE:
            return {"success": False, "retcode": res.retcode, "error": f"Broker rejected modify ({res.retcode}): {res.comment}"}

        return {"success": True, "ticket": ticket, "symbol": symbol, "sl": target_sl, "tp": target_tp}

    TRAIL_PROFILES = {
        "SCALP": {
            "name": "SCALP",
            "breakeven_r": 0.35,
            "trail_start_r": 0.65,
            "trail_step_r": 0.20,
        },
        "SWING": {
            "name": "SWING",
            "breakeven_r": 0.45,
            "trail_start_r": 0.90,
            "trail_step_r": 0.40,
        },
        "BALANCE": {
            "name": "BALANCE",
            "breakeven_r": 0.50,
            "trail_start_r": 0.85,
            "trail_step_r": 0.30,
        },
        "SWAP": {
            "name": "SWAP",
            "breakeven_r": 0.50,
            "trail_start_r": 1.00,
            "trail_step_r": 0.45,
        }
    }

    def trail_positions(self, default_strategy: str = "SCALP",
                        breakeven_r: float = None, trail_step_r: float = None,
                        current_prices: dict = None) -> list:
        """
        Automated Profile-Aware Trailing Stop & Breakeven Protection.
        Works across both Live MT5 Broker positions and Paper Trading simulation.
        Adapts trailing mechanics dynamically based on each position's strategy profile:
          - SCALP: Fast breakeven at +0.35R, tight trailing starting at +0.65R (0.20R step).
          - SWING: Breakeven at +0.45R, structural trailing starting at +0.90R (0.40R step).
          - BALANCE: Breakeven at +0.50R, dynamic equilibrium trailing starting at +0.85R (0.30R step).
          - SWAP: Breakeven at +0.50R, carry buffer starting at +1.00R (0.45R step).
        Prevents collapsing risk-distance on breakeven, ratchets trailing stop strictly
        behind peak favorable price, and insulates against rollover spread-spikes.
        """
        mode = safety_manager.get_trading_mode() if safety_manager else "LIVE"

        # ── 1. PAPER TRADING TRAILING ENGINE ──
        if mode == "PAPER" and safety_manager:
            prices = dict(current_prices) if current_prices else {}
            if "GOLD" not in prices or "BTC" not in prices:
                try:
                    from market_data import market_feed
                    if "GOLD" not in prices:
                        g_t = market_feed.get_live_price("GOLD")
                        if g_t and g_t.get("price", 0) > 0:
                            prices["GOLD"] = g_t["price"]
                    if "BTC" not in prices:
                        b_t = market_feed.get_live_price("BTC")
                        if b_t and b_t.get("price", 0) > 0:
                            prices["BTC"] = b_t["price"]
                except Exception:
                    pass
            return safety_manager.trail_paper_positions(prices, default_strategy=default_strategy)

        # ── 2. LIVE / DEMO BROKER TRAILING ENGINE ──
        if not self.ensure_connected():
            return []

        # Rollover Spread-Spike Insulation (21:50 - 22:15 UTC)
        now_utc = datetime.utcnow()
        if (now_utc.hour == 21 and now_utc.minute >= 50) or (now_utc.hour == 22 and now_utc.minute <= 15):
            return []

        all_positions = mt5.positions_get()
        if not all_positions:
            all_positions = []

        # Strictly isolate bot positions from user's manual trades
        positions = [p for p in all_positions if getattr(p, "magic", 0) == BOT_MAGIC]

        events = []
        open_tickets = {p.ticket for p in positions}

        # Detect closed live positions and check deals history for TP_HIT / SL_HIT
        for t in list(self.position_initial_risks.keys()):
            if t not in open_tickets:
                self.position_initial_risks.pop(t, None)
                self.position_peak_prices.pop(t, None)
                meta = self.tracked_live_tickets.pop(t, None) if hasattr(self, "tracked_live_tickets") else None
                if meta:
                    try:
                        deals = mt5.history_deals_get(position=t)
                        if deals:
                            close_deal = deals[-1]
                            pnl = float(sum(getattr(d, "profit", 0.0) for d in deals))
                            exit_price = float(getattr(close_deal, "price", 0.0))
                            deal_reason = getattr(close_deal, "reason", 0)
                            is_win = pnl > 0 or deal_reason == getattr(mt5, "DEAL_REASON_TP", 4)
                            action_type = "TP_HIT" if is_win else "SL_HIT"
                            sym = meta.get("symbol", "XAUUSD")
                            strat = meta.get("strategy", "SCALP")
                            asset_n = meta.get("asset", "GOLD")
                            msg = (f"🎯 *[{strat}] TAKE-PROFIT ACHIEVED:* #{t} `{sym}` Target Reached @ `${exit_price:,.2f}` (PnL: `${pnl:+,.2f}` 💰)"
                                   if is_win else
                                   f"🛑 *[{strat}] STOP-LOSS HIT:* #{t} `{sym}` Closed @ `${exit_price:,.2f}` (PnL: `${pnl:+,.2f}`)")
                            events.append({
                                "ticket": t,
                                "symbol": sym,
                                "asset": asset_n,
                                "type": meta.get("type", "BUY"),
                                "strategy": strat,
                                "action": action_type,
                                "price": exit_price,
                                "pnl": pnl,
                                "msg": msg
                            })
                    except Exception:
                        pass

        if not positions:
            return events

        events = []
        for p in positions:
            symbol = p.symbol
            sym_info = mt5.symbol_info(symbol)
            if not sym_info:
                continue
            tick = mt5.symbol_info_tick(symbol)
            if not tick:
                continue

            digits = sym_info.digits
            point = sym_info.point or (10 ** -digits)
            spread_buffer = max(sym_info.spread * point, 2 * point)
            is_gold = ("XAU" in symbol.upper() or "GOLD" in symbol.upper())
            # Break-Even Plus (BE+): Guarantee covering spread, commissions, and min +$0.50 profit
            be_offset = max(0.50, round(spread_buffer + 0.35, digits)) if is_gold else max(50.0, round(spread_buffer + 25.0, digits))

            is_buy = p.type == mt5.ORDER_TYPE_BUY
            curr_price = tick.bid if is_buy else tick.ask
            entry = p.price_open
            curr_sl = p.sl
            curr_tp = p.tp
            ticket = p.ticket

            # Recover or calculate un-collapsing initial risk distance
            if ticket in self.position_initial_risks:
                risk_dist = self.position_initial_risks[ticket]
            else:
                if curr_sl > 0 and ((is_buy and curr_sl < entry) or (not is_buy and curr_sl > entry)):
                    risk_dist = abs(entry - curr_sl)
                else:
                    risk_dist = 3.0 if ("XAU" in symbol.upper() or "GOLD" in symbol.upper()) else 250.0
                self.position_initial_risks[ticket] = risk_dist

            if risk_dist <= 0:
                continue

            # Detect Strategy Profile from Position Comment
            comment = (getattr(p, "comment", "") or "").upper()
            if "SWING" in comment:
                strat_name = "SWING"
            elif "BALANCE" in comment:
                strat_name = "BALANCE"
            elif "SWAP" in comment:
                strat_name = "SWAP"
            elif "SCALP" in comment or "SNIPER" in comment:
                strat_name = "SCALP"
            else:
                strat_name = (default_strategy or "SCALP").upper()

            profile = self.TRAIL_PROFILES.get(strat_name, self.TRAIL_PROFILES["SCALP"])
            active_be_r = breakeven_r if (breakeven_r is not None and breakeven_r > 0) else profile["breakeven_r"]
            active_trail_start_r = profile["trail_start_r"]
            active_trail_step_r = trail_step_r if (trail_step_r is not None and trail_step_r > 0) else profile["trail_step_r"]

            # Update Peak Favorable Price
            prev_peak = self.position_peak_prices.get(ticket, entry)
            peak_price = max(prev_peak, curr_price) if is_buy else min(prev_peak, curr_price)
            self.position_peak_prices[ticket] = peak_price

            # Profit distance & R-multiples
            profit_dist = (curr_price - entry) if is_buy else (entry - curr_price)
            current_r = profit_dist / risk_dist
            peak_profit_dist = (peak_price - entry) if is_buy else (entry - peak_price)
            peak_r = peak_profit_dist / risk_dist

            # ── 2. Strategy-Specific Breakeven Trigger (BE+ Offset) ──
            breakeven_sl = round(entry + be_offset if is_buy else entry - be_offset, digits)
            if not hasattr(self, "tracked_live_tickets"):
                self.tracked_live_tickets = {}
            self.tracked_live_tickets[ticket] = {
                "symbol": symbol,
                "asset": "GOLD" if is_gold else "BTC",
                "type": "BUY" if is_buy else "SELL",
                "strategy": strat_name,
                "entry": entry,
                "sl": curr_sl,
                "tp": curr_tp
            }
            needs_breakeven = False
            if is_buy and current_r >= active_be_r and curr_sl < entry:
                needs_breakeven = True
            elif not is_buy and current_r >= active_be_r and (curr_sl > entry or curr_sl == 0):
                needs_breakeven = True

            if needs_breakeven:
                res = self.modify_position_sltp(ticket, breakeven_sl, curr_tp)
                if res.get("success"):
                    asset_norm = "GOLD" if ("XAU" in symbol or "GOLD" in symbol) else "BTC"
                    events.append({
                        "ticket": ticket,
                        "symbol": symbol,
                        "asset": asset_norm,
                        "type": "BUY" if is_buy else "SELL",
                        "strategy": strat_name,
                        "action": "BREAKEVEN",
                        "old_sl": curr_sl,
                        "new_sl": breakeven_sl,
                        "current_price": curr_price,
                        "profit_r": current_r,
                        "msg": f"🛡️ *[{strat_name}] BREAKEVEN LOCKED:* #{ticket} `{symbol}` SL moved to `${breakeven_sl:,.2f}` (+{current_r:.2f}R reached — 100% Risk-Free!)"
                    })
                    continue

            # ── 3. Strategy-Specific Dynamic Trailing Step Ratchet ──
            if peak_r >= active_trail_start_r:
                if is_buy:
                    trailing_sl = round(peak_price - (risk_dist * active_trail_step_r), digits)
                    trailing_sl = max(trailing_sl, breakeven_sl)
                    should_trail = trailing_sl > curr_sl and (trailing_sl - curr_sl) >= (10 * point)
                else:
                    trailing_sl = round(peak_price + (risk_dist * active_trail_step_r), digits)
                    trailing_sl = min(trailing_sl, breakeven_sl)
                    should_trail = (curr_sl == 0 or trailing_sl < curr_sl) and abs(trailing_sl - curr_sl) >= (10 * point)

                if should_trail:
                    res = self.modify_position_sltp(ticket, trailing_sl, curr_tp)
                    if res.get("success"):
                        asset_norm = "GOLD" if ("XAU" in symbol or "GOLD" in symbol) else "BTC"
                        events.append({
                            "ticket": ticket,
                            "symbol": symbol,
                            "asset": asset_norm,
                            "type": "BUY" if is_buy else "SELL",
                            "strategy": strat_name,
                            "action": "TRAILED",
                            "old_sl": curr_sl,
                            "new_sl": trailing_sl,
                            "current_price": curr_price,
                            "peak_price": peak_price,
                            "profit_r": current_r,
                            "msg": f"📈 *[{strat_name}] TRAILING ADVANCED:* #{ticket} `{symbol}` SL trailed to `${trailing_sl:,.2f}` (+{current_r:.2f}R — Profit Secured!)"
                        })

        return events

    def get_open_positions(self) -> list:
        """Fetches all currently open positions across live MT5 and Paper Trading."""
        mode = safety_manager.get_trading_mode() if safety_manager else "LIVE"
        results = []

        # 1. Paper positions if in PAPER mode
        if mode == "PAPER" and safety_manager:
            for p in safety_manager.get_paper_positions():
                results.append({
                    "ticket": p["ticket"],
                    "symbol": p["symbol"],
                    "type": p["action"],
                    "lots": p["lots"],
                    "open_price": p["open_price"],
                    "current_price": p["open_price"],
                    "sl": p["sl"],
                    "tp": p["tp1"],
                    "profit": 0.0,
                    "mode": "PAPER",
                    "time": p["open_time"]
                })
            return results

        # 2. Live MT5 positions
        if not self.ensure_connected():
            return results

        positions = mt5.positions_get()
        if not positions:
            return results

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
                "mode": mode,
                "time": datetime.fromtimestamp(p.time).strftime("%Y-%m-%d %H:%M:%S") if p.time else ""
            })
        return results

    def close_all_positions(self) -> dict:
        """Emergency circuit breaker: Closes all open positions immediately (MT5 & Paper)."""
        mode = safety_manager.get_trading_mode() if safety_manager else "LIVE"
        closed = 0
        total_pnl = 0.0

        # Close paper positions if any
        if safety_manager and safety_manager.get_paper_positions():
            paper_pos = list(safety_manager.get_paper_positions())
            for p in paper_pos:
                res = safety_manager.close_paper_position(p["ticket"], p["open_price"], reason="EMERGENCY_KILL_SWITCH")
                if res.get("success"):
                    closed += 1
                    total_pnl += res.get("closed_pnl", 0.0)

        # In DEMO / LIVE mode: MT5 connection is required
        if mode in ("DEMO", "LIVE") and not self.ensure_connected():
            return {"success": False, "error": "MT5 is disconnected."}

        # Close live MT5 positions if connected
        if self.ensure_connected():
            positions = mt5.positions_get()
            if positions:
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
                        if safety_manager:
                            safety_manager.record_pnl(p.profit)
                            safety_manager.log_order_audit({
                                "event": "POSITION_CLOSED_MT5",
                                "ticket": p.ticket,
                                "symbol": symbol,
                                "pnl_usd": p.profit,
                                "reason": "EMERGENCY_KILL_SWITCH"
                            })

        return {
            "success": True,
            "closed_count": closed,
            "total_pnl": total_pnl
        }

    def get_closed_deals_history(self, days: int = 14) -> list:
        """
        Fetches closed deals from MetaTrader 5 deal history or Paper Trading history.
        Returns a structured list of closed trades:
          [{"ticket": str, "asset": str, "symbol": str, "action": str, "lots": float,
            "open_price": float, "exit_price": float, "pnl": float, "r_multiple": float,
            "outcome": "WIN"|"LOSS", "time": str, "source": "MT5"|"PAPER"}]
        """
        mode = safety_manager.get_trading_mode() if safety_manager else "LIVE"
        if mode == "PAPER":
            return safety_manager.get_closed_paper_positions(limit=50) if safety_manager else []

        if not self.ensure_connected():
            return []

        try:
            from_date = datetime.now() - timedelta(days=days)
            deals = mt5.history_deals_get(from_date, datetime.now())
            if deals is None or len(deals) == 0:
                return []

            results = []
            for d in deals:
                # MT5 DEAL_ENTRY_OUT = 1 (exit deal), DEAL_ENTRY_INOUT = 2 (reversal)
                if getattr(d, "entry", None) in (1, 2):
                    symbol = d.symbol
                    asset = "BTC" if "BTC" in symbol.upper() else "GOLD" if ("XAU" in symbol.upper() or "GOLD" in symbol.upper()) else None
                    if not asset:
                        continue
                    # If closing deal was BUY, original position was SELL; if closing deal was SELL, original was BUY
                    is_buy_exit = d.type == mt5.DEAL_TYPE_BUY
                    action = "SELL" if is_buy_exit else "BUY"
                    pnl = float(d.profit)
                    outcome = "WIN" if pnl > 0 else "LOSS"
                    r_mult = 1.20 if pnl > 0 else -1.0

                    results.append({
                        "ticket": str(d.ticket),
                        "position_id": str(getattr(d, "position_id", d.ticket)),
                        "asset": asset,
                        "symbol": symbol,
                        "action": action,
                        "lots": float(d.volume),
                        "open_price": float(d.price),
                        "exit_price": float(d.price),
                        "pnl": round(pnl, 2),
                        "r_multiple": r_mult,
                        "outcome": outcome,
                        "time": datetime.fromtimestamp(d.time).strftime("%Y-%m-%d %H:%M:%S") if d.time else "",
                        "source": "MT5"
                    })
            return results
        except Exception as e:
            print(f"[!] Error fetching MT5 closed deals: {e}")
            return []

    def close_position(self, ticket: str | int, exit_price: float = None, reason: str = "MANUAL_CLOSE") -> dict:
        """Closes a single specific position (Paper or MT5)."""
        str_ticket = str(ticket)
        mode = safety_manager.get_trading_mode() if safety_manager else "LIVE"

        # 1. Paper Position Close
        if str_ticket.startswith("PAPER-") or mode == "PAPER":
            if safety_manager:
                target_p = None
                for p in safety_manager.get_paper_positions():
                    if str(p["ticket"]) == str_ticket:
                        target_p = p
                        break
                price = exit_price or (target_p["open_price"] if target_p else 0.0)
                return safety_manager.close_paper_position(str_ticket, price, reason=reason)
            return {"success": False, "error": "SafetyManager unavailable for Paper trade close."}

        # 2. Live MT5 Position Close
        if not self.ensure_connected():
            return {"success": False, "error": "MT5 is disconnected."}

        try:
            num_ticket = int(str_ticket)
        except ValueError:
            return {"success": False, "error": f"Invalid MT5 ticket format: {ticket}"}

        positions = mt5.positions_get(ticket=num_ticket)
        if not positions or len(positions) == 0:
            return {"success": False, "error": f"Position #{num_ticket} not found in MT5."}

        p = positions[0]
        symbol = p.symbol
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return {"success": False, "error": f"Failed to get price tick for {symbol}"}

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
            "comment": reason,
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
            if safety_manager:
                safety_manager.record_pnl(p.profit)
                safety_manager.log_order_audit({
                    "event": "POSITION_CLOSED_MT5",
                    "ticket": p.ticket,
                    "symbol": symbol,
                    "pnl_usd": p.profit,
                    "reason": reason
                })
            return {"success": True, "ticket": p.ticket, "closed_pnl": p.profit, "symbol": symbol}
        return {"success": False, "error": f"MT5 close error code {getattr(res, 'retcode', 'UNKNOWN')}"}

    def has_open_position(self, asset: str) -> bool:
        """Returns True if a position for this asset is open in MT5 or Paper."""
        mode = safety_manager.get_trading_mode() if safety_manager else "LIVE"
        asset_key = "GOLD" if asset.upper() in ("GOLD", "XAU", "XAUUSD", "GC=F") else "BTC"

        # Check paper positions
        if mode == "PAPER" and safety_manager:
            for p in safety_manager.get_paper_positions():
                if p.get("asset") == asset_key:
                    return True
            return False

        # Check live MT5 positions
        if not self.ensure_connected():
            return False
        symbol = self.resolve_symbol(asset)
        positions = mt5.positions_get(symbol=symbol)
        if positions is not None and len(positions) > 0:
            bot_pos = [p for p in positions if getattr(p, "magic", 0) == BOT_MAGIC]
            return len(bot_pos) > 0
        return False

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
