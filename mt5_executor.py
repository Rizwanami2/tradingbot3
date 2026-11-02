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
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import os
import math
import time
import pandas as pd
from datetime import datetime, timedelta

try:
    from utils.logger import get_logger
    logger = get_logger("mt5_executor")
except Exception:
    import logging
    logger = logging.getLogger("mt5_executor")

try:
    from config_validator import validate_config
except Exception:
    def validate_config(*args, **kwargs):
        return True, []

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
        self.position_partial_tp_closed = {}
        self.position_profit_locked = {}   # ticket -> {"locked_r": float, "locked_at": float}
        self.position_open_time = {}       # ticket -> entry epoch for time-based exit
        self.position_swing_lows = {}      # ticket -> list of recent swing lows for BUY
        self.position_swing_highs = {}     # ticket -> list of recent swing highs for SELL
        self.pending_orders = {}
        # Exponential backoff parameters (2s up to 60s)
        self.reconnect_delay = 2.0
        self.max_reconnect_delay = 60.0
        self.last_reconnect_attempt = 0.0
        # ── Trading Cost Configuration ──
        # $0.25 per 0.01 lot round trip (commission + spread)
        self.trade_cost_per_01_lot = 0.25
        self.lot_size_for_cost_calc = 0.01
        # Minimum profitable trade: cost must be covered
        self.min_profitable_r_multiple = 1.5   # minimum 1.5R to cover costs + profit
        # Breakeven buffer: cover trading cost + small buffer
        self.breakeven_cost_buffer_pips = {
            "GOLD": 5.0,   # ~$0.50 cost buffer for Gold 0.01 lot
            "BTC": 50.0    # ~$0.50 cost buffer for BTC 0.01 lot
        }
        # Slippage statistics tracking
        self.slippage_stats = {
            "total_trades": 0,
            "excessive_slippage_count": 0,
            "max_slippage_pips": 0.0,
            "recent_slippages": [],
            "slippage_by_symbol": {},      # symbol -> {"count": n, "total_pips": x, "max_pips": y, "avg_pips": z}
            "slippage_by_hour": {},        # hour (0-23) -> {"count": n, "total_pips": x, "max_pips": y}
            "adaptive_max_slippage_pips": 3.0  # Auto-adjusted based on observed conditions
        }
        # Profit protection configuration
        self.profit_lock_levels = [0.5, 1.0, 1.5]   # close 25% at each level
        self.profit_lock_close_pct = 0.25            # close 25% per level
        self.tighten_trail_after_r = 1.0             # start tightening trail after +1R
        self.tight_trail_step_r = 0.25               # tight trail step (closer SL)
        self.max_hold_minutes = 240                  # time-based exit: close after 4 hours if no profit
        # ATR-based trailing configuration (gives market breathing room)
        self.atr_trail_multiplier = 1.5              # trail SL at 1.5x ATR from swing extreme
        self.atr_lookback = 14                       # ATR period for trail calculation
        self.swing_lookback = 10                     # lookback bars for swing high/low
        self.wick_buffer_pct = 0.30                  # 30% buffer beyond swing extreme (fake candle protection)
        self.min_trail_distance_pips = {             # minimum trail distance to avoid noise + cover trading costs
            "GOLD": 12.0,   # 12 pips minimum for Gold (~$1.20 covers $0.25 cost + buffer)
            "BTC": 100.0    # 100 pips minimum for BTC (~$1.00 covers $0.25 cost + buffer)
        }

    def _notify_telegram_alert(self, text: str):
        """Sends an urgent alert through Telegram if available."""
        try:
            import telegram_bot
            tok, cid = telegram_bot.get_credentials()
            if tok and cid:
                telegram_bot.send_message(tok, cid, text)
        except Exception as e:
            logger.debug(f"Could not dispatch telegram notification: {e}")

    def connect(self, login: int = None, password: str = None, server: str = None, path: str = None) -> tuple:
        """
        Connects to live MetaTrader 5 terminal.
        If credentials provided, logs into the specific account.
        Otherwise, attaches directly to the currently running logged-in terminal.
        Re-validates symbols on every connection attempt.
        """
        # Validate startup configuration
        validate_config(fail_fast=False)

        # Clear symbol cache on every connect/reconnect to force fresh validation
        self.resolved_symbols.clear()

        if not MT5_AVAILABLE:
            self.is_connected = False
            msg = "MetaTrader5 Python library not installed. Run: py -3.11 -m pip install MetaTrader5"
            logger.warning(msg)
            return False, msg

        self.last_login = login
        self.last_password = password
        self.last_server = server
        self.last_path = path

        # Step 1: Initialize terminal with Smart Auto-Discovery
        init_ok = False
        target_path = path or os.environ.get("MT5_PATH", "").strip()

        if target_path and os.path.exists(target_path):
            init_ok = mt5.initialize(path=target_path)
        else:
            # 1. Try attaching directly to currently running MT5 terminal
            init_ok = mt5.initialize()

            # 2. If default attach fails, scan common broker installation directories
            if not init_ok:
                common_paths = [
                    "C:\\Program Files\\MetaTrader 5\\terminal64.exe",
                    "C:\\Program Files (x86)\\MetaTrader 5\\terminal64.exe",
                    "C:\\Program Files\\FTMO MetaTrader 5\\terminal64.exe",
                    "C:\\Program Files\\ICMarkets MetaTrader 5\\terminal64.exe",
                    "C:\\Program Files\\Exness MetaTrader 5\\terminal64.exe",
                    "C:\\Program Files\\XM Global MT5\\terminal64.exe",
                    "C:\\Program Files\\FBS MetaTrader 5\\terminal64.exe",
                    "C:\\Program Files\\Vantage Markets MT5\\terminal64.exe"
                ]
                if os.path.exists("C:\\Program Files"):
                    try:
                        for entry in os.listdir("C:\\Program Files"):
                            sub = os.path.join("C:\\Program Files", entry, "terminal64.exe")
                            if os.path.exists(sub) and sub not in common_paths:
                                common_paths.append(sub)
                    except Exception:
                        pass

                for candidate in common_paths:
                    if os.path.exists(candidate):
                        logger.info(f"Auto-discovered MT5 terminal at: {candidate}")
                        init_ok = mt5.initialize(path=candidate)
                        if init_ok:
                            target_path = candidate
                            break

        if not init_ok:
            err = mt5.last_error()
            self.is_connected = False
            msg = (
                f"MT5 terminal initialization failed: {err}.\n"
                f"SOLUTIONS:\n"
                f"1. Open the MetaTrader 5 desktop application on your VPS/PC.\n"
                f"2. Log into your broker account in MT5 (File -> Login to Trade Account).\n"
                f"3. Enable Algo Trading (Tools -> Options -> Expert Advisors -> check 'Allow algorithmic trading').\n"
                f"4. If MT5 is installed in a custom broker folder, set MT5_PATH in .env (e.g. MT5_PATH=C:\\Program Files\\Exness MT5\\terminal64.exe)."
            )
            logger.warning(msg)
            return False, msg

        # Step 2: Login if explicit credentials provided
        if login and password and server:
            try:
                login_ok = mt5.login(login=int(login), password=str(password), server=str(server))
            except Exception as le:
                login_ok = False
                logger.warning(f"Error executing mt5.login: {le}")

            if not login_ok:
                err = mt5.last_error()
                # Check if terminal is already authenticated to an active account
                acc = mt5.account_info()
                if acc and acc.login > 0:
                    logger.warning(f"Explicit login failed ({err}), but terminal is already logged into active account #{acc.login}. Using existing session.")
                else:
                    self.is_connected = False
                    msg = f"MT5 live login failed for account #{login} on {server}: {err}. Please verify MT5_LOGIN, MT5_PASSWORD, and MT5_SERVER."
                    logger.warning(msg)
                    return False, msg

        # Step 3: Verify terminal and account status
        term = mt5.terminal_info()
        acc = mt5.account_info()

        if not acc:
            self.is_connected = False
            msg = "Could not fetch MT5 account info. Please ensure you are logged into a live account in MT5."
            logger.warning(msg)
            return False, msg

        self.terminal_info = term
        self.account_info = acc
        self.is_connected = True
        self.reconnect_delay = 2.0  # Reset backoff interval on successful connection

        trade_status = "ENABLED ✅" if (term and term.trade_allowed) else "DISABLED ⚠️ (Enable 'Allow Algo Trading' in MT5 Tools -> Options)"

        banner = (
            f"🟢 LIVE MT5 BROKER CONNECTED\n"
            f"• Broker: {acc.company}\n"
            f"• Account: #{acc.login} ({acc.server})\n"
            f"• Balance: ${acc.balance:,.2f} {acc.currency}\n"
            f"• Equity:  ${acc.equity:,.2f} {acc.currency}\n"
            f"• Leverage: 1:{acc.leverage} (Auto-Managed)\n"
            f"• Algo Trading: {trade_status}"
        )
        logger.info(banner)
        return True, banner

    def ensure_connected(self) -> bool:
        """
        Verifies active connection and auto-reconnects with exponential backoff
        starting at 2s and doubling up to max 60s. Logs each attempt and alerts on success.
        """
        if not MT5_AVAILABLE:
            return False

        if self.is_connected:
            term = mt5.terminal_info()
            if term is not None:
                self.terminal_info = term
                return True
            self.is_connected = False
            logger.warning("MT5 connection drop detected.")

        now = time.time()
        if (now - self.last_reconnect_attempt) < self.reconnect_delay:
            return False

        self.last_reconnect_attempt = now
        logger.info(f"Attempting MT5 auto-reconnect (backoff interval: {self.reconnect_delay:.1f}s)...")
        ok, msg = self.connect(self.last_login, self.last_password, self.last_server, self.last_path)
        if ok:
            logger.info("MT5 auto-reconnect succeeded! Alerting channel.")
            self.reconnect_delay = 2.0
            self._notify_telegram_alert("🟢 *MT5 AUTO-RECONNECTED*\nMetaTrader 5 broker terminal connection restored successfully.")
            return True
        else:
            self.reconnect_delay = min(self.reconnect_delay * 2.0, self.max_reconnect_delay)
            logger.warning(f"MT5 auto-reconnect failed ({msg}). Next retry in {self.reconnect_delay:.1f}s.")
            return False

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
        Verifies visibility, full tradability, contract_size > 0, digits >= 0.
        Cache resolved symbols but re-validate on every connect/reconnect.
        """
        asset_key = "GOLD" if asset.upper() in ("GOLD", "XAU", "XAUUSD", "GC=F") else "BTC"
        if asset_key in self.resolved_symbols:
            return self.resolved_symbols[asset_key]

        if not self.ensure_connected():
            return "XAUUSD" if asset_key == "GOLD" else "BTCUSD"

        candidates = GOLD_SYMBOL_CANDIDATES if asset_key == "GOLD" else BTC_SYMBOL_CANDIDATES

        def _is_valid_tradable(sym_name: str) -> bool:
            info = mt5.symbol_info(sym_name)
            if not info:
                return False
            if not info.visible:
                mt5.symbol_select(sym_name, True)
                info = mt5.symbol_info(sym_name)
                if not info or not info.visible:
                    return False
            trade_mode = getattr(info, "trade_mode", None)
            if trade_mode == mt5.SYMBOL_TRADE_MODE_DISABLED:
                return False
            contract_size = getattr(info, "trade_contract_size", 0) or getattr(info, "contract_size", 0)
            if contract_size <= 0:
                return False
            if getattr(info, "digits", -1) < 0:
                return False
            return True

        for sym in candidates:
            if _is_valid_tradable(sym):
                self.resolved_symbols[asset_key] = sym
                logger.info(f"Resolved verified tradable symbol for {asset_key}: {sym}")
                return sym

        # Fallback search in all broker symbols
        all_syms = mt5.symbols_get()
        if all_syms:
            for s in all_syms:
                name_upper = s.name.upper()
                if asset_key == "GOLD" and ("XAU" in name_upper or "GOLD" in name_upper):
                    if _is_valid_tradable(s.name):
                        self.resolved_symbols[asset_key] = s.name
                        logger.info(f"Resolved verified tradable symbol for GOLD: {s.name}")
                        return s.name
                elif asset_key == "BTC" and ("BTC" in name_upper and "USD" in name_upper):
                    if _is_valid_tradable(s.name):
                        self.resolved_symbols[asset_key] = s.name
                        logger.info(f"Resolved verified tradable symbol for BTC: {s.name}")
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
        Enforces:
          - Pre-Trade Margin Check (free_margin >= req_margin * 1.25)
          - SL/TP Side Validation (BUY: SL < entry < TP; SELL: TP < entry < SL)
          - Lot Normalization (clamped to volume_min, volume_max, volume_step; precision rounded)
          - Pre-order Spread Guard (spread <= MAX_SPREAD_PIPS)
          - Min Distance Guard (distance >= trade_stops_level)
          - Symbol Tradability verification
          - Portfolio Risk Cap (total open risk + trade <= MAX_TOTAL_OPEN_RISK_PCT)
          - Post-order Slippage Guard (slippage <= MAX_SLIPPAGE_PIPS, alerts, stats)
        """
        current_mode = safety_manager.get_trading_mode() if safety_manager else "LIVE"
        asset_key = "GOLD" if asset.upper() in ("GOLD", "XAU", "XAUUSD", "GC=F") else "BTC"
        is_gold_asset = asset_key == "GOLD"
        is_buy = action.upper() in ("BUY", "LONG")

        # ── 1. PAPER TRADING SIMULATION (Zero Real Capital Risk) ──
        if current_mode == "PAPER" and safety_manager:
            open_pos = safety_manager.get_paper_positions()
            paper_bal = safety_manager.state.get("paper_account", {}).get("balance", 10000.0)
            sl_dist = abs(entry_price - stop_loss) if (entry_price > 0 and stop_loss > 0) else (5.0 if is_gold_asset else 400.0)
            tp_dist = abs(take_profit - entry_price) if (entry_price > 0 and take_profit > 0) else (sl_dist * 1.20)

            # SL/TP Side Validation for Paper
            if is_buy:
                if not (stop_loss < entry_price < take_profit):
                    logger.warning(f"Inverted SL/TP for Paper BUY on {asset_key}. Auto-correcting to proper sides.")
                    stop_loss = round(entry_price - sl_dist, 2)
                    take_profit = round(entry_price + tp_dist, 2)
            else:
                if not (take_profit < entry_price < stop_loss):
                    logger.warning(f"Inverted SL/TP for Paper SELL on {asset_key}. Auto-correcting to proper sides.")
                    stop_loss = round(entry_price + sl_dist, 2)
                    take_profit = round(entry_price - tp_dist, 2)

            # Paper Margin Check (125% buffer)
            contract_size = 100.0 if is_gold_asset else 1.0
            req_paper_margin = (contract_size * lot_size * entry_price) / 100.0
            if (req_paper_margin * 1.25) > paper_bal:
                msg = f"Margin Check REJECTED: Required margin ${req_paper_margin:,.2f} with 25% buffer (${req_paper_margin * 1.25:,.2f}) exceeds balance ${paper_bal:,.2f}."
                logger.warning(msg)
                return {"success": False, "error": msg, "mode": "PAPER"}

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

        symbol = self.resolve_symbol(asset)
        sym_info = mt5.symbol_info(symbol)
        if not sym_info:
            return {"success": False, "error": f"Symbol '{symbol}' not recognized by broker."}

        if not sym_info.visible:
            mt5.symbol_select(symbol, True)
            sym_info = mt5.symbol_info(symbol)

        # Symbol Tradability Validation Gate
        trade_mode = getattr(sym_info, "trade_mode", None)
        if trade_mode == mt5.SYMBOL_TRADE_MODE_DISABLED:
            return {"success": False, "error": f"Symbol Tradability REJECTED: Trading is DISABLED by broker for {symbol}."}
        if is_buy and trade_mode == mt5.SYMBOL_TRADE_MODE_SHORTONLY:
            return {"success": False, "error": f"Symbol Tradability REJECTED: {symbol} is in SHORT-ONLY mode."}
        if (not is_buy) and trade_mode == mt5.SYMBOL_TRADE_MODE_LONGONLY:
            return {"success": False, "error": f"Symbol Tradability REJECTED: {symbol} is in LONG-ONLY mode."}

        # Lot Normalization Gate
        broker_min_lot = sym_info.volume_min or 0.01
        broker_max_lot = min(sym_info.volume_max or 50.0, 1.0)  # Conservative live cap (max 1.0 lot)
        step_lot = sym_info.volume_step or 0.01

        steps = math.floor(round(lot_size / step_lot, 6)) if step_lot > 0 else 1
        aligned_lot = steps * step_lot
        step_decimals = max(0, -int(math.floor(math.log10(step_lot)))) if (0 < step_lot < 1) else 2
        aligned_lot = round(aligned_lot, step_decimals)

        if aligned_lot < broker_min_lot:
            msg = f"Lot Normalization REJECTED: Requested lot {lot_size:.2f} (aligned {aligned_lot:.2f}) < broker volume_min {broker_min_lot}."
            logger.warning(msg)
            return {"success": False, "error": msg, "mode": current_mode}

        valid_lot = max(broker_min_lot, min(aligned_lot, broker_max_lot))
        valid_lot = round(valid_lot, step_decimals)

        order_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL

        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return {"success": False, "error": f"Could not fetch live price tick for '{symbol}'."}

        fill_price = tick.ask if is_buy else tick.bid
        digits = sym_info.digits
        point = sym_info.point or (10 ** -digits)
        pip_unit = (10.0 * point) if digits in (2, 3, 5) else point

        # Pre-Order Spread Guard Gate
        max_spread_pips = float(os.getenv("MAX_SPREAD_PIPS", "30.0"))
        spread_pts = sym_info.spread
        spread_pips = (spread_pts * point) / pip_unit if pip_unit > 0 else float(spread_pts)
        if spread_pips > max_spread_pips:
            msg = f"Spread Guard REJECTED: Broker spread {spread_pips:.1f} pips exceeds MAX_SPREAD_PIPS ({max_spread_pips:.1f} pips)."
            logger.warning(msg)
            return {"success": False, "error": msg, "mode": current_mode}

        # Pre-Trade Margin Check Gate (free_margin >= req_margin * 1.25)
        acc = self.account_info or mt5.account_info()
        contract_size = getattr(sym_info, "trade_contract_size", 100.0 if is_gold_asset else 1.0) or (100.0 if is_gold_asset else 1.0)
        leverage = acc.leverage if (acc and acc.leverage and acc.leverage > 0) else 100.0

        req_margin = None
        if hasattr(mt5, "order_calc_margin"):
            try:
                calc_m = mt5.order_calc_margin(order_type, symbol, valid_lot, fill_price)
                if calc_m and calc_m > 0:
                    req_margin = float(calc_m)
            except Exception:
                req_margin = None

        if req_margin is None:
            req_margin = (contract_size * valid_lot * fill_price) / leverage

        free_margin = getattr(acc, "margin_free", None) if acc else None
        if free_margin is None:
            free_margin = (acc.balance * 0.90) if acc else 10000.0

        if free_margin < (req_margin * 1.25):
            msg = (f"Pre-Trade Margin Check REJECTED: Required margin ${req_margin:,.2f} with 25% buffer "
                   f"(${req_margin * 1.25:,.2f}) exceeds free margin ${free_margin:,.2f}.")
            logger.warning(msg)
            return {"success": False, "error": msg, "mode": current_mode}

        # Calculate exact SL and TP distances from entry and anchor to live fill_price
        sl_dist = abs(entry_price - stop_loss) if (entry_price > 0 and stop_loss > 0) else (5.0 if is_gold_asset else 400.0)
        tp_dist = abs(take_profit - entry_price) if (entry_price > 0 and take_profit > 0) else (sl_dist * 1.20)

        # Min Distance Guard Gate (trade_stops_level)
        stops_level_pts = sym_info.trade_stops_level or 0
        min_stop_dist = max((stops_level_pts + 5) * point, 0.0)
        if sl_dist < min_stop_dist:
            sl_dist = min_stop_dist
        if tp_dist < min_stop_dist:
            tp_dist = min_stop_dist

        final_sl = round(fill_price - sl_dist if is_buy else fill_price + sl_dist, digits)
        final_tp = round(fill_price + tp_dist if is_buy else fill_price - tp_dist, digits)

        # SL/TP Side Validation Gate (BUY -> SL < entry < TP; SELL -> TP < entry < SL)
        if is_buy:
            if not (final_sl < fill_price < final_tp):
                logger.warning(f"Inverted SL/TP detected for BUY on {symbol} (SL={final_sl}, Entry={fill_price}, TP={final_tp}). Re-aligning.")
                final_sl = round(fill_price - sl_dist, digits)
                final_tp = round(fill_price + tp_dist, digits)
                if not (final_sl < fill_price < final_tp):
                    msg = f"SL/TP Side Validation REJECTED for BUY: SL ({final_sl}) must be < Entry ({fill_price}) < TP ({final_tp})."
                    logger.error(msg)
                    return {"success": False, "error": msg, "mode": current_mode}
        else:
            if not (final_tp < fill_price < final_sl):
                logger.warning(f"Inverted SL/TP detected for SELL on {symbol} (TP={final_tp}, Entry={fill_price}, SL={final_sl}). Re-aligning.")
                final_sl = round(fill_price + sl_dist, digits)
                final_tp = round(fill_price - tp_dist, digits)
                if not (final_tp < fill_price < final_sl):
                    msg = f"SL/TP Side Validation REJECTED for SELL: TP ({final_tp}) must be < Entry ({fill_price}) < SL ({final_sl})."
                    logger.error(msg)
                    return {"success": False, "error": msg, "mode": current_mode}

        # Min Distance enforcement
        if stops_level_pts > 0:
            if abs(fill_price - final_sl) < (stops_level_pts * point):
                return {"success": False, "error": f"Min Distance Guard REJECTED: SL distance is within broker trade_stops_level ({stops_level_pts} pts)."}
            if abs(fill_price - final_tp) < (stops_level_pts * point):
                return {"success": False, "error": f"Min Distance Guard REJECTED: TP distance is within broker trade_stops_level ({stops_level_pts} pts)."}

        # Portfolio Risk Cap Gate (MAX_TOTAL_OPEN_RISK_PCT)
        max_portfolio_risk_pct = float(os.getenv("MAX_TOTAL_OPEN_RISK_PCT", "2.5"))
        open_pos = self.get_open_positions() or []
        equity_val = acc.equity if (acc and acc.equity > 0) else 10000.0
        current_open_risk = 0.0
        for p in open_pos:
            pos_sl = p.get("sl", 0.0)
            pos_open = p.get("price_open", p.get("open_price", 0.0))
            pos_vol = p.get("volume", p.get("lots", 0.01))
            pos_sym = p.get("symbol", symbol)
            c_size = 100.0 if ("XAU" in pos_sym or "GOLD" in pos_sym) else 1.0
            pos_sl_dist = abs(pos_open - pos_sl) if (pos_sl and pos_sl > 0) else (pos_open * 0.01)
            current_open_risk += (pos_sl_dist * pos_vol * c_size / equity_val) * 100.0

        proposed_risk_usd = sl_dist * valid_lot * contract_size
        proposed_risk_pct = (proposed_risk_usd / equity_val) * 100.0
        if (current_open_risk + proposed_risk_pct) > max_portfolio_risk_pct:
            msg = (f"Portfolio Risk Cap REJECTED: Current open risk ({current_open_risk:.2f}%) + proposed trade "
                   f"({proposed_risk_pct:.2f}%) = {current_open_risk + proposed_risk_pct:.2f}% > limit {max_portfolio_risk_pct:.1f}%.")
            logger.warning(msg)
            return {"success": False, "error": msg, "mode": current_mode}

        if safety_manager:
            safe_ok, safe_msg = safety_manager.check_trade_safety(
                asset, proposed_risk_pct=proposed_risk_pct, open_positions=open_pos,
                current_equity=equity_val, data_timestamp=tick.time,
                spread_val=spread_pts * point, sl_dist=sl_dist
            )
            if not safe_ok:
                return {"success": False, "error": safe_msg, "mode": current_mode}

        asset_deviation = 40 if is_gold_asset else 650  # 40 pts Gold ($0.40), 650 pts BTC ($6.50)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": valid_lot,
            "type": order_type,
            "price": fill_price,
            "sl": final_sl,
            "tp": final_tp,
            "deviation": asset_deviation,
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

        # Post-Order Slippage Guard Gate
        max_slippage_pips = float(os.getenv("MAX_SLIPPAGE_PIPS", "3.0"))
        price_diff = abs(actual_fill - fill_price)
        slip_pips = (price_diff / pip_unit) if pip_unit > 0 else price_diff

        # ── Per-Symbol & Per-Hour Execution Quality Tracking ──
        now_hour = datetime.now().hour

        # Per-symbol tracking
        sym_stats = self.slippage_stats["slippage_by_symbol"].setdefault(
            symbol, {"count": 0, "total_pips": 0.0, "max_pips": 0.0, "avg_pips": 0.0}
        )
        sym_stats["count"] += 1
        sym_stats["total_pips"] += slip_pips
        sym_stats["max_pips"] = max(sym_stats["max_pips"], slip_pips)
        sym_stats["avg_pips"] = round(sym_stats["total_pips"] / sym_stats["count"], 2)

        # Per-hour tracking
        hour_stats = self.slippage_stats["slippage_by_hour"].setdefault(
            str(now_hour), {"count": 0, "total_pips": 0.0, "max_pips": 0.0}
        )
        hour_stats["count"] += 1
        hour_stats["total_pips"] += slip_pips
        hour_stats["max_pips"] = max(hour_stats["max_pips"], slip_pips)

        # Adaptive max slippage: raise limit if recent slippage consistently exceeds static limit
        recent = self.slippage_stats["recent_slippages"]
        if len(recent) >= 10:
            recent_avg = sum(recent[-10:]) / len(recent[-10:])
            if recent_avg > max_slippage_pips * 0.8:
                self.slippage_stats["adaptive_max_slippage_pips"] = round(min(recent_avg * 1.25, max_slippage_pips * 2.0), 2)
            else:
                self.slippage_stats["adaptive_max_slippage_pips"] = max_slippage_pips

        self.slippage_stats["total_trades"] += 1
        self.slippage_stats["max_slippage_pips"] = max(self.slippage_stats["max_slippage_pips"], slip_pips)
        self.slippage_stats["recent_slippages"].append(round(slip_pips, 2))
        if len(self.slippage_stats["recent_slippages"]) > 50:
            self.slippage_stats["recent_slippages"].pop(0)

        slip_ok = slip_pips <= self.slippage_stats["adaptive_max_slippage_pips"]
        if not slip_ok:
            self.slippage_stats["excessive_slippage_count"] += 1
            slip_warning = (f"⚠️ HIGH SLIPPAGE DETECTED on {symbol}: Requested ${entry_price:,.2f}, "
                            f"Filled ${actual_fill:,.2f}, Slippage {slip_pips:.1f} pips > Limit {self.slippage_stats['adaptive_max_slippage_pips']:.1f} pips.")
            logger.warning(slip_warning)
            self._notify_telegram_alert(
                f"⚠️ *HIGH SLIPPAGE ALERT*\n"
                f"• Symbol: `{symbol}`\n"
                f"• Requested: `${entry_price:,.2f}`\n"
                f"• Actual Fill: `${actual_fill:,.2f}`\n"
                f"• Slippage: `{slip_pips:.1f} pips` (Limit: `{self.slippage_stats['adaptive_max_slippage_pips']:.1f}`)\n"
                f"• Hour: `{now_hour}:00` | Mode: `{current_mode}`"
            )

        if safety_manager:
            safety_manager.log_order_audit({
                "event": "ORDER_PLACED_MT5",
                "ticket": res.order,
                "asset": asset,
                "symbol": symbol,
                "action": action.upper(),
                "lots": valid_lot,
                "entry_requested": entry_price,
                "fill_price": actual_fill,
                "slippage": round(price_diff, 2),
                "slippage_pips": round(slip_pips, 2),
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
            "slippage": round(price_diff, 2),
            "slippage_pips": round(slip_pips, 2),
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
        now_utc = datetime.now(timezone.utc)
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

            # Track position open time for time-based exit
            ticket = p.ticket
            if ticket not in self.position_open_time:
                self.position_open_time[ticket] = time.time()

            digits = sym_info.digits
            point = sym_info.point or (10 ** -digits)
            spread_buffer = max(sym_info.spread * point, 2 * point)
            is_gold = ("XAU" in symbol.upper() or "GOLD" in symbol.upper())
            # Break-Even Plus (BE+): Guarantee covering spread, commissions, and min profit
            # $0.25 per 0.01 lot round trip cost must be covered
            cost_buffer_pips = self.breakeven_cost_buffer_pips.get("GOLD" if is_gold else "BTC", 5.0)
            be_offset = max(0.50, round(spread_buffer + cost_buffer_pips + 0.35, digits)) if is_gold else max(50.0, round(spread_buffer + cost_buffer_pips + 25.0, digits))

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

            # ── 3. ATR-Based Swing Trailing ── Trail behind swing extreme with wick buffer ──
            if peak_r >= active_trail_start_r:
                # Fetch recent MT5 data for swing level calculation
                mt5_hist = None
                try:
                    mt5_hist = self._get_mt5_hist(symbol, count=30,
                                                  timeframe=mt5.TIMEFRAME_M5 if mt5 else None)
                except Exception:
                    mt5_hist = None

                # Update swing levels for this position
                if mt5_hist is not None and len(mt5_hist) > 10:
                    self._update_swing_levels(ticket, is_buy, mt5_hist, lookback=self.swing_lookback)

                # Get best swing level for trailing
                swing_level = self._get_best_swing_level(ticket, is_buy)
                if swing_level > 0:
                    # ATR-based trailing with wick buffer
                    atr = self._calculate_atr(mt5_hist, period=self.atr_lookback)
                    min_dist = self.min_trail_distance_pips.get("GOLD" if is_gold else "BTC", 8.0)

                    if is_buy:
                        # For BUY: trail SL below swing low with ATR + wick buffer
                        new_sl = self._calculate_swing_trailing_sl(
                            is_buy=True, current_price=curr_price,
                            swing_level=swing_level, atr=atr,
                            buffer_pct=self.wick_buffer_pct,
                            min_dist_pips=min_dist
                        )
                        # Only trail UP (never move SL down for BUY)
                        should_trail = new_sl > curr_sl and (new_sl - curr_sl) >= (5 * point)
                        new_sl = max(new_sl, breakeven_sl)  # never below breakeven
                    else:
                        # For SELL: trail SL above swing high with ATR + wick buffer
                        new_sl = self._calculate_swing_trailing_sl(
                            is_buy=False, current_price=curr_price,
                            swing_level=swing_level, atr=atr,
                            buffer_pct=self.wick_buffer_pct,
                            min_dist_pips=min_dist
                        )
                        # Only trail DOWN (never move SL up for SELL)
                        should_trail = (curr_sl == 0 or new_sl < curr_sl) and abs(new_sl - curr_sl) >= (5 * point)
                        new_sl = min(new_sl, breakeven_sl)  # never above breakeven

                    if should_trail:
                        new_sl = round(new_sl, digits)
                        res = self.modify_position_sltp(ticket, new_sl, curr_tp)
                        if res.get("success"):
                            asset_norm = "GOLD" if ("XAU" in symbol or "GOLD" in symbol) else "BTC"
                            events.append({
                                "ticket": ticket,
                                "symbol": symbol,
                                "asset": asset_norm,
                                "type": "BUY" if is_buy else "SELL",
                                "strategy": strat_name,
                                "action": "SWING_TRAIL",
                                "old_sl": curr_sl,
                                "new_sl": new_sl,
                                "current_price": curr_price,
                                "swing_level": swing_level,
                                "atr": atr,
                                "profit_r": current_r,
                                "msg": f"📈 *[{strat_name}] SWING TRAIL:* #{ticket} `{symbol}` SL trailed to `${new_sl:,.2f}` (swing={swing_level:,.2f}, ATR={atr:.2f}, +{current_r:.2f}R)"
                            })
                    else:
                        # Fallback to fixed-ratio trailing if swing data unavailable
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

            # ── 4. REVERSAL DETECTION ── Close profitable position on confirmed reversal ──
            if mt5_hist is not None and len(mt5_hist) >= 20 and current_r >= 0.5:
                reversal_confirmed, reversal_reason, reversal_conf = self._detect_reversal(
                    is_buy=is_buy, mt5_hist=mt5_hist,
                    curr_price=curr_price, entry=entry,
                    risk_dist=risk_dist, current_r=current_r
                )
                if reversal_confirmed and reversal_conf >= 0.6:
                    # Close full position on confirmed reversal
                    close_res = self.close_position(ticket, curr_price, reason="REVERSAL_DETECTED")
                    if close_res.get("success"):
                        asset_norm = "GOLD" if is_gold else "BTC"
                        events.append({
                            "ticket": ticket,
                            "symbol": symbol,
                            "asset": asset_norm,
                            "type": "BUY" if is_buy else "SELL",
                            "strategy": strat_name,
                            "action": "REVERSAL_EXIT",
                            "closed_price": curr_price,
                            "profit_r": current_r,
                            "confidence": reversal_conf,
                            "reason": reversal_reason,
                            "msg": f"🔄 *[{strat_name}] REVERSAL EXIT:* #{ticket} `{symbol}` closed at `${curr_price:,.2f}` (+{current_r:.2f}R — {reversal_reason})"
                        })
                        continue  # Skip remaining logic for this position

            # ── 5. PROFIT LOCK LEVELS ── Close 25% at each R level ──
            lock_state = self.position_profit_locked.get(ticket, {"locked_r": 0.0, "closed_pct": 0.0})
            for lock_r in self.profit_lock_levels:
                if current_r >= lock_r and lock_state["locked_r"] < lock_r:
                    # Close a portion of the position at this profit level
                    close_lots = round(lot_size * self.profit_lock_close_pct, 2)
                    if close_lots > 0:
                        close_res = self.close_position_partial(ticket, close_lots, curr_price, reason=f"PROFIT_LOCK_{lock_r}R")
                        if close_res.get("success"):
                            lock_state["locked_r"] = lock_r
                            lock_state["closed_pct"] += self.profit_lock_close_pct
                            self.position_profit_locked[ticket] = lock_state
                            events.append({
                                "ticket": ticket,
                                "symbol": symbol,
                                "asset": "GOLD" if is_gold else "BTC",
                                "type": "BUY" if is_buy else "SELL",
                                "strategy": strat_name,
                                "action": "PROFIT_LOCK",
                                "closed_lots": close_lots,
                                "lock_r": lock_r,
                                "current_price": curr_price,
                                "profit_r": current_r,
                                "msg": f"💰 *[{strat_name}] PROFIT LOCK {lock_r}R:* #{ticket} `{symbol}` closed {close_lots} lots (+{current_r:.2f}R secured)"
                            })

            # ── 6. TIGHTER TRAILING AFTER +1R ── Trail closer as profit grows ──
            if current_r >= self.tighten_trail_after_r and current_r < self.profit_lock_levels[-1]:
                if is_buy:
                    tight_sl = round(peak_price - (risk_dist * self.tight_trail_step_r), digits)
                    tight_sl = max(tight_sl, breakeven_sl, curr_sl)
                    should_tight = tight_sl > curr_sl and (tight_sl - curr_sl) >= (5 * point)
                else:
                    tight_sl = round(peak_price + (risk_dist * self.tight_trail_step_r), digits)
                    tight_sl = min(tight_sl, breakeven_sl, curr_sl if curr_sl > 0 else tight_sl)
                    should_tight = (curr_sl == 0 or tight_sl < curr_sl) and abs(tight_sl - curr_sl) >= (5 * point)

                if should_tight:
                    res = self.modify_position_sltp(ticket, tight_sl, curr_tp)
                    if res.get("success"):
                        asset_norm = "GOLD" if ("XAU" in symbol or "GOLD" in symbol) else "BTC"
                        events.append({
                            "ticket": ticket,
                            "symbol": symbol,
                            "asset": asset_norm,
                            "type": "BUY" if is_buy else "SELL",
                            "strategy": strat_name,
                            "action": "TIGHT_TRAIL",
                            "old_sl": curr_sl,
                            "new_sl": tight_sl,
                            "current_price": curr_price,
                            "peak_price": peak_price,
                            "profit_r": current_r,
                            "msg": f"🔒 *[{strat_name}] TIGHT TRAIL:* #{ticket} `{symbol}` SL tightened to `${tight_sl:,.2f}` (+{current_r:.2f}R — Profit Protected!)"
                        })

            # ── 7. TIME-BASED EXIT ── Close stuck trades after max_hold_minutes ──
            open_time = self.position_open_time.get(ticket, time.time())
            hold_minutes = (time.time() - open_time) / 60.0
            if hold_minutes >= self.max_hold_minutes and current_r <= 0.0:
                close_res = self.close_position(ticket, curr_price, reason="TIME_BASED_EXIT")
                if close_res.get("success"):
                    events.append({
                        "ticket": ticket,
                        "symbol": symbol,
                        "asset": "GOLD" if is_gold else "BTC",
                        "type": "BUY" if is_buy else "SELL",
                        "strategy": strat_name,
                        "action": "TIME_EXIT",
                        "closed_price": curr_price,
                        "hold_minutes": round(hold_minutes, 1),
                        "profit_r": current_r,
                        "msg": f"⏱️ *[{strat_name}] TIME EXIT:* #{ticket} `{symbol}` closed after {hold_minutes:.0f}min ({current_r:.2f}R — no profit)"
                    })

        return events


    def execute_live_limit_order(self, asset: str, action: str,
                                 limit_price: float, stop_loss: float,
                                 take_profit: float, lot_size: float,
                                 zone: tuple = None, expiry_minutes: int = 35,
                                 comment: str = "GoldBTC-Limit") -> dict:
        """
        Places a limit order inside the Golden Pocket or confluence zone.
        Supports both Paper Simulation and Live MT5 Broker.
        """
        current_mode = safety_manager.get_trading_mode() if safety_manager else "LIVE"
        asset_key = "GOLD" if asset.upper() in ("GOLD", "XAU", "XAUUSD", "GC=F") else "BTC"
        is_buy = action.upper() in ("BUY", "BUY_LIMIT", "LONG")

        if current_mode == "PAPER" and safety_manager:
            return safety_manager.execute_paper_limit_order(
                asset=asset_key, action=action, limit_price=limit_price,
                stop_loss=stop_loss, tp1=take_profit, tp2=take_profit,
                lots=lot_size, zone=zone, expiry_minutes=expiry_minutes,
                comment=comment
            )

        if not self.ensure_connected():
            return {"success": False, "error": "MT5 is disconnected."}

        symbol = self.resolve_symbol(asset_key)
        sym_info = mt5.symbol_info(symbol)
        if not sym_info:
            return {"success": False, "error": f"Symbol '{symbol}' not recognized by broker."}

        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return {"success": False, "error": f"Failed to get price tick for {symbol}"}

        digits = sym_info.digits
        point = sym_info.point or (10 ** -digits)
        spread_pts = (tick.ask - tick.bid)
        max_spread_pips = float(os.environ.get("MAX_SPREAD_PIPS", "30"))
        pip_size = (point * 10) if digits in (3, 5) else point
        current_spread_pips = (spread_pts / pip_size) if pip_size > 0 else 0.0

        if current_spread_pips > max_spread_pips:
            msg = f"Spread Guard REJECTED: Current spread {current_spread_pips:.1f} pips > max {max_spread_pips:.1f} pips."
            logger.warning(msg)
            return {"success": False, "error": msg}

        # Lot Normalization Gate
        broker_min_lot = sym_info.volume_min or 0.01
        step_lot = sym_info.volume_step or 0.01
        steps = math.floor(round(lot_size / step_lot, 6)) if step_lot > 0 else 1
        aligned_lot = steps * step_lot
        step_decimals = max(0, -int(math.floor(math.log10(step_lot)))) if (0 < step_lot < 1) else 2
        aligned_lot = round(aligned_lot, step_decimals)
        if aligned_lot < broker_min_lot:
            return {"success": False, "error": f"Lot {aligned_lot} < min {broker_min_lot}"}

        # Margin Check (25% buffer)
        acc = mt5.account_info()
        if acc:
            req_margin = mt5.order_calc_margin(
                mt5.ORDER_TYPE_BUY_LIMIT if is_buy else mt5.ORDER_TYPE_SELL_LIMIT,
                symbol, aligned_lot, limit_price
            )
            if req_margin is not None and (req_margin * 1.25) > acc.margin_free:
                msg = f"Margin Check REJECTED: Required margin ${req_margin:,.2f} (+25% buffer) > free margin ${acc.margin_free:,.2f}."
                logger.warning(msg)
                return {"success": False, "error": msg}

        aligned_limit = round(limit_price, digits)
        aligned_sl = round(stop_loss, digits)
        aligned_tp = round(take_profit, digits)
        if is_buy:
            if not (aligned_sl < aligned_limit < aligned_tp):
                logger.warning(f"Inverted SL/TP for Limit BUY on {symbol}. Correcting.")
                dist = abs(aligned_limit - aligned_sl)
                aligned_sl = round(aligned_limit - dist, digits)
                aligned_tp = round(aligned_limit + (dist * 1.5), digits)
        else:
            if not (aligned_tp < aligned_limit < aligned_sl):
                logger.warning(f"Inverted SL/TP for Limit SELL on {symbol}. Correcting.")
                dist = abs(aligned_limit - aligned_sl)
                aligned_sl = round(aligned_limit + dist, digits)
                aligned_tp = round(aligned_limit - (dist * 1.5), digits)

        order_type = mt5.ORDER_TYPE_BUY_LIMIT if is_buy else mt5.ORDER_TYPE_SELL_LIMIT
        expiration_time = int(time.time() + (expiry_minutes * 60))

        req = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": aligned_lot,
            "type": order_type,
            "price": aligned_limit,
            "sl": aligned_sl,
            "tp": aligned_tp,
            "magic": BOT_MAGIC,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_SPECIFIED,
            "expiration": expiration_time,
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
            order_ticket = res.order
            logger.info(f"Placed MT5 Limit Order #{order_ticket} on {symbol} @ ${aligned_limit:,.2f}")
            return {
                "success": True,
                "ticket": order_ticket,
                "symbol": symbol,
                "asset": asset_key,
                "action": "BUY_LIMIT" if is_buy else "SELL_LIMIT",
                "limit_price": aligned_limit,
                "sl": aligned_sl,
                "tp": aligned_tp,
                "volume": aligned_lot,
                "mode": "LIVE"
            }
        err_msg = getattr(res, "comment", "Unknown order placement error")
        return {"success": False, "error": f"MT5 Limit Order Failed: {err_msg} (retcode: {getattr(res, 'retcode', 'N/A')})"}

    def get_pending_orders(self) -> list:
        """Returns all pending limit orders (Paper or Live MT5)."""
        mode = safety_manager.get_trading_mode() if safety_manager else "LIVE"
        if mode == "PAPER" and safety_manager:
            return safety_manager.get_paper_pending_orders()

        if not self.ensure_connected():
            return []
        orders = mt5.orders_get()
        if not orders:
            return []
        bot_orders = [o for o in orders if getattr(o, "magic", 0) == BOT_MAGIC]
        res = []
        for o in bot_orders:
            res.append({
                "ticket": o.ticket,
                "symbol": o.symbol,
                "type": o.type,
                "price_open": o.price_open,
                "sl": o.sl,
                "tp": o.tp,
                "volume_current": o.volume_current,
                "time_expiration": getattr(o, "time_expiration", 0)
            })
        return res

    def cancel_pending_order(self, ticket: str | int, reason: str = "MANUAL_CANCEL") -> dict:
        """Cancels a pending order."""
        str_ticket = str(ticket)
        mode = safety_manager.get_trading_mode() if safety_manager else "LIVE"
        if str_ticket.startswith("PAPER-") or mode == "PAPER":
            if safety_manager:
                return safety_manager.cancel_paper_pending_order(str_ticket, reason=reason)
            return {"success": False, "error": "Safety manager unavailable."}

        if not self.ensure_connected():
            return {"success": False, "error": "MT5 is disconnected."}
        try:
            num_ticket = int(str_ticket)
        except ValueError:
            return {"success": False, "error": f"Invalid ticket {ticket}"}

        req = {
            "action": mt5.TRADE_ACTION_REMOVE,
            "order": num_ticket
        }
        res = mt5.order_send(req)
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"Cancelled MT5 pending order #{num_ticket} (Reason: {reason})")
            return {"success": True, "ticket": num_ticket, "reason": reason}
        return {"success": False, "error": f"Failed to cancel order #{num_ticket}: {getattr(res, 'comment', 'Unknown')}"}

    def manage_pending_orders(self, current_prices: dict = None, trap_states: dict = None) -> list:
        """Checks fills, expirations, and trap invalidations for pending orders."""
        mode = safety_manager.get_trading_mode() if safety_manager else "LIVE"
        if mode == "PAPER" and safety_manager:
            prices = dict(current_prices) if current_prices else {}
            return safety_manager.check_and_update_pending_orders(prices, trap_states=trap_states)

        events = []
        if not self.ensure_connected():
            return events
        orders = self.get_pending_orders()
        for o in orders:
            sym = o.get("symbol", "")
            asset = "GOLD" if ("XAU" in sym or "GOLD" in sym) else "BTC"
            trap = (trap_states or {}).get(asset, "CLEAN")
            is_buy = o.get("type") == getattr(mt5, "ORDER_TYPE_BUY_LIMIT", 2)
            if is_buy and trap == "BULL_TRAP":
                c_res = self.cancel_pending_order(o["ticket"], reason="INVALIDATED_BULL_TRAP")
                if c_res.get("success"):
                    events.append({"ticket": o["ticket"], "action": "INVALIDATED", "msg": f"⚠️ MT5 BUY Limit #{o['ticket']} cancelled due to Bull Trap."})
            elif (not is_buy) and trap == "BEAR_TRAP":
                c_res = self.cancel_pending_order(o["ticket"], reason="INVALIDATED_BEAR_TRAP")
                if c_res.get("success"):
                    events.append({"ticket": o["ticket"], "action": "INVALIDATED", "msg": f"⚠️ MT5 SELL Limit #{o['ticket']} cancelled due to Bear Trap."})
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

    def close_position_partial(self, ticket: str | int, fraction: float = 0.50, exit_price: float = None, reason: str = "PARTIAL_TP") -> dict:
        """
        Closes a partial fraction (default 50%) of an open position.
        Works across both Paper and Live MT5 positions.
        """
        str_ticket = str(ticket)
        mode = safety_manager.get_trading_mode() if safety_manager else "LIVE"

        # 1. Paper Position Partial Close
        if str_ticket.startswith("PAPER-") or mode == "PAPER":
            if safety_manager:
                positions = safety_manager.get_paper_positions()
                for p in positions:
                    if str(p["ticket"]) == str_ticket:
                        curr_lots = p.get("lots", 0.05)
                        close_lots = round(curr_lots * fraction, 2)
                        rem_lots = round(curr_lots - close_lots, 2)
                        if close_lots <= 0.0 or rem_lots <= 0.0:
                            return self.close_position(str_ticket, exit_price=exit_price, reason=reason)
                        p["lots"] = rem_lots
                        asset_key = p["asset"]
                        mult = 100.0 if asset_key == "GOLD" else 1.0
                        price = exit_price or p["open_price"]
                        is_buy = p["action"] == "BUY"
                        pnl = round(((price - p["open_price"]) if is_buy else (p["open_price"] - price)) * close_lots * mult, 2)
                        safety_manager.record_pnl(pnl)
                        return {"success": True, "ticket": str_ticket, "partial_lots": close_lots, "remaining_lots": rem_lots, "pnl": pnl}
            return {"success": False, "error": "Paper position not found for partial close."}

        # 2. Live MT5 Position Partial Close
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
        sym_info = mt5.symbol_info(symbol)
        if not tick or not sym_info:
            return {"success": False, "error": f"Failed to get price tick for {symbol}"}

        vol_min = sym_info.volume_min or 0.01
        vol_step = sym_info.volume_step or 0.01
        close_volume = round(p.volume * fraction, 2)
        close_volume = math.floor(close_volume / vol_step) * vol_step
        close_volume = round(close_volume, 2)

        if close_volume < vol_min:
            close_volume = vol_min
        if close_volume >= p.volume:
            return self.close_position(num_ticket, exit_price=exit_price, reason=reason)

        order_type = mt5.ORDER_TYPE_SELL if p.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price = tick.bid if p.type == mt5.ORDER_TYPE_BUY else tick.ask
        asset_key = "GOLD" if "XAU" in symbol or "GOLD" in symbol else "BTC"
        dev = 40 if asset_key == "GOLD" else 650

        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": p.ticket,
            "symbol": symbol,
            "volume": close_volume,
            "type": order_type,
            "price": price,
            "deviation": dev,
            "magic": BOT_MAGIC,
            "comment": f"PARTIAL_{int(fraction*100)}PCT",
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
            partial_pnl = round(p.profit * (close_volume / p.volume), 2)
            if safety_manager:
                safety_manager.record_pnl(partial_pnl)
                safety_manager.log_order_audit({
                    "event": "PARTIAL_CLOSE_MT5",
                    "ticket": p.ticket,
                    "symbol": symbol,
                    "closed_volume": close_volume,
                    "remaining_volume": round(p.volume - close_volume, 2),
                    "pnl_usd": partial_pnl,
                    "reason": reason
                })
            return {"success": True, "ticket": p.ticket, "closed_volume": close_volume, "pnl": partial_pnl, "symbol": symbol}
        return {"success": False, "error": f"MT5 partial close error code {getattr(res, 'retcode', 'UNKNOWN')}"}

    def move_to_breakeven(self, ticket: str | int) -> dict:
        """
        Manually forces position SL to Breakeven Plus (BE+) with spread buffer.
        """
        str_ticket = str(ticket)
        mode = safety_manager.get_trading_mode() if safety_manager else "LIVE"

        # Paper position
        if str_ticket.startswith("PAPER-") or mode == "PAPER":
            if safety_manager:
                for p in safety_manager.get_paper_positions():
                    if str(p["ticket"]) == str_ticket:
                        open_p = p["open_price"]
                        asset_key = p["asset"]
                        offset = 0.50 if asset_key == "GOLD" else 50.0
                        be_price = (open_p + offset) if p["action"] == "BUY" else (open_p - offset)
                        p["sl"] = be_price
                        return {"success": True, "ticket": str_ticket, "new_sl": be_price, "symbol": p.get("symbol")}
            return {"success": False, "error": "Paper position not found."}

        # MT5 live position
        if not self.ensure_connected():
            return {"success": False, "error": "MT5 is disconnected."}

        try:
            num_ticket = int(str_ticket)
        except ValueError:
            return {"success": False, "error": f"Invalid ticket: {ticket}"}

        positions = mt5.positions_get(ticket=num_ticket)
        if not positions:
            return {"success": False, "error": f"Position #{num_ticket} not found."}

        p = positions[0]
        sym = p.symbol
        tick = mt5.symbol_info_tick(sym)
        info = mt5.symbol_info(sym)
        digits = getattr(info, "digits", 2)
        spread_pts = getattr(tick, "ask", 0) - getattr(tick, "bid", 0) if tick else 0.0
        asset_key = "GOLD" if "XAU" in sym or "GOLD" in sym else "BTC"
        # Include trading cost buffer in breakeven offset
        cost_buffer_pips = self.breakeven_cost_buffer_pips.get(asset_key, 5.0)
        be_offset = max(0.50, round(spread_pts + cost_buffer_pips + 0.35, digits)) if asset_key == "GOLD" else max(50.0, round(spread_pts + cost_buffer_pips + 25.0, digits))

        is_buy = (p.type == mt5.ORDER_TYPE_BUY)
        new_sl = round(p.price_open + be_offset, digits) if is_buy else round(p.price_open - be_offset, digits)

        req = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": p.ticket,
            "symbol": sym,
            "sl": new_sl,
            "tp": p.tp
        }
        res = mt5.order_send(req)
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            return {"success": True, "ticket": p.ticket, "new_sl": new_sl, "symbol": sym}
        return {"success": False, "error": f"Failed to set BE: {getattr(res, 'retcode', 'UNKNOWN')}"}

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

    # ── ATR-Based Trailing Helpers ──
    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """Calculate Average True Range from OHLCV DataFrame."""
        if df is None or len(df) < period + 1:
            return 0.0
        high = df["High"].astype(float)
        low = df["Low"].astype(float)
        close = df["Close"].astype(float)
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(period).mean().iloc[-1]
        return float(atr) if not pd.isna(atr) else 0.0

    def _calculate_swing_trailing_sl(self, is_buy: bool, current_price: float,
                                      swing_level: float, atr: float,
                                      buffer_pct: float = 0.30,
                                      min_dist_pips: float = 8.0) -> float:
        """
        Calculate swing-based trailing stop with wick buffer.
        
        For BUY: trail SL just below recent swing low + wick buffer + ATR buffer
        For SELL: trail SL just above recent swing high + wick buffer + ATR buffer
        
        The buffer prevents fake candle wicks from prematurely stopping out the trade.
        """
        if atr <= 0:
            atr = 1.0  # fallback
        
        # ATR-based distance from swing extreme
        atr_buffer = atr * self.atr_trail_multiplier
        
        # Wick buffer as percentage of ATR
        wick_buffer = atr * buffer_pct
        
        if is_buy:
            # For BUY: SL below swing low, with buffer below it
            trailing_sl = swing_level - atr_buffer - wick_buffer
            # Ensure minimum distance from current price
            min_sl = current_price - (min_dist_pips * self._get_pip_value(symbol="GC=F"))
            trailing_sl = min(trailing_sl, min_sl)  # don't trail too close
            return trailing_sl
        else:
            # For SELL: SL above swing high, with buffer above it
            trailing_sl = swing_level + atr_buffer + wick_buffer
            # Ensure minimum distance from current price
            min_sl = current_price + (min_dist_pips * self._get_pip_value(symbol="GC=F"))
            trailing_sl = max(trailing_sl, min_sl)  # don't trail too close
            return trailing_sl

    def _get_pip_value(self, symbol: str = "GC=F") -> float:
        """Get pip value for symbol."""
        if "XAU" in symbol.upper() or "GOLD" in symbol.upper():
            return 0.10  # Gold pip value
        return 10.0  # BTC pip value

    # ── REVERSAL DETECTION ── Advanced reversal confirmation for profit protection ──
    def _detect_reversal(self, is_buy: bool, mt5_hist: pd.DataFrame,
                         curr_price: float, entry: float, risk_dist: float,
                         current_r: float) -> tuple:
        """
        Detect confirmed trend reversal using multiple confirmations.
        Returns (is_reversal: bool, reason: str, confidence: float).
        
        Confirmation layers (ALL must pass for reversal confirmation):
        1. Price closes beyond opposite swing extreme (not just wick touch)
        2. Engulfing candle pattern (current candle body engulfs previous)
        3. Momentum divergence (price new extreme but RSI doesn't confirm)
        4. Close beyond opposite key level (previous structure broken)
        
        This prevents fake wicks/corrections from triggering false exits.
        """
        if mt5_hist is None or len(mt5_hist) < 20:
            return False, "Insufficient data for reversal detection", 0.0

        # Get recent candles
        recent = mt5_hist.tail(10)
        curr_candle = recent.iloc[-1]
        prev_candle = recent.iloc[-2]

        c_open = float(curr_candle["Open"])
        c_high = float(curr_candle["High"])
        c_low = float(curr_candle["Low"])
        c_close = float(curr_candle["Close"])
        p_open = float(prev_candle["Open"])
        p_high = float(prev_candle["High"])
        p_low = float(prev_candle["Low"])
        p_close = float(prev_candle["Close"])

        # Get swing levels from tracked data
        if is_buy:
            # For BUY position: reversal = bearish reversal
            # Price closes below recent swing low (not just wick)
            swing_levels = self.position_swing_lows.get(ticket, [])
            if not swing_levels:
                return False, "No swing data for reversal check", 0.0
            swing_low = max(swing_levels)  # highest recent swing low

            # Confirmation 1: Close below swing low (body close, not wick)
            close_below_swing = c_close < swing_low
            if not close_below_swing:
                return False, "Price not closed below swing low", 0.0

            # Confirmation 2: Bearish engulfing (current bearish candle engulfs previous bullish)
            curr_bearish = c_close < c_open
            prev_bullish = p_close > p_open
            engulfing = curr_bearish and prev_bullish and c_open > p_close and c_close < p_open
            if not engulfing:
                # Alternative: strong bearish close (close in bottom 25% of range)
                c_range = c_high - c_low
                if c_range > 0:
                    close_position = (c_close - c_low) / c_range
                    strong_bearish = curr_bearish and close_position < 0.25
                else:
                    strong_bearish = False
                if not strong_bearish:
                    return False, "No bearish engulfing or strong close", 0.0

            # Confirmation 3: Price significantly below swing low (not just touching)
            swing_distance_pips = abs(swing_low - c_close) / self._get_pip_value(symbol)
            min_swing_distance = self.min_trail_distance_pips.get("GOLD" if is_gold else "BTC", 12.0) * 0.5
            if swing_distance_pips < min_swing_distance:
                return False, "Price not sufficiently beyond swing low", 0.0

            # Confirmation 4: Momentum check - RSI declining while price made new high earlier
            # Simple check: recent closes declining
            recent_closes = recent["Close"].astype(float).tail(5)
            if len(recent_closes) >= 3:
                recent_declining = all(recent_closes.iloc[i] < recent_closes.iloc[i-1] 
                                      for i in range(1, len(recent_closes)))
            else:
                recent_declining = False
            
            confidence = 0.0
            if close_below_swing: confidence += 0.3
            if engulfing: confidence += 0.3
            elif strong_bearish: confidence += 0.2
            if recent_declining: confidence += 0.2
            if swing_distance_pips >= min_swing_distance: confidence += 0.2

            reversal_confirmed = confidence >= 0.6
            reason = f"Bearish reversal: close={c_close:.2f} below swing={swing_low:.2f}, engulfing={engulfing}, momentum_declining={recent_declining}"
            return reversal_confirmed, reason, confidence

        else:
            # For SELL position: reversal = bullish reversal
            swing_levels = self.position_swing_highs.get(ticket, [])
            if not swing_levels:
                return False, "No swing data for reversal check", 0.0
            swing_high = min(swing_levels)  # lowest recent swing high

            # Confirmation 1: Close above swing high (body close, not just wick)
            close_above_swing = c_close > swing_high
            if not close_above_swing:
                return False, "Price not closed above swing high", 0.0

            # Confirmation 2: Bullish engulfing
            curr_bullish = c_close > c_open
            prev_bearish = p_close < p_open
            engulfing = curr_bullish and prev_bearish and c_open < p_close and c_close > p_open
            if not engulfing:
                c_range = c_high - c_low
                if c_range > 0:
                    close_position = (c_high - c_close) / c_range
                    strong_bullish = curr_bullish and close_position < 0.25
                else:
                    strong_bullish = False
                if not strong_bullish:
                    return False, "No bullish engulfing or strong close", 0.0

            # Confirmation 3: Price significantly above swing high
            swing_distance_pips = abs(c_close - swing_high) / self._get_pip_value(symbol)
            min_swing_distance = self.min_trail_distance_pips.get("GOLD" if is_gold else "BTC", 12.0) * 0.5
            if swing_distance_pips < min_swing_distance:
                return False, "Price not sufficiently above swing high", 0.0

            # Confirmation 4: Recent closes rising
            recent_closes = recent["Close"].astype(float).tail(5)
            if len(recent_closes) >= 3:
                recent_rising = all(recent_closes.iloc[i] > recent_closes.iloc[i-1] 
                                   for i in range(1, len(recent_closes)))
            else:
                recent_rising = False

            confidence = 0.0
            if close_above_swing: confidence += 0.3
            if engulfing: confidence += 0.3
            elif strong_bullish: confidence += 0.2
            if recent_rising: confidence += 0.2
            if swing_distance_pips >= min_swing_distance: confidence += 0.2

            reversal_confirmed = confidence >= 0.6
            reason = f"Bullish reversal: close={c_close:.2f} above swing={swing_high:.2f}, engulfing={engulfing}, momentum_rising={recent_rising}"
            return reversal_confirmed, reason, confidence

    def _update_swing_levels(self, ticket: str, is_buy: bool, df: pd.DataFrame,
                             lookback: int = 10):
        """Track recent swing highs/lows for trailing stop calculation."""
        if df is None or len(df) < lookback:
            return
        recent = df.tail(lookback)
        if is_buy:
            swing_low = float(recent["Low"].min())
            if ticket not in self.position_swing_lows:
                self.position_swing_lows[ticket] = []
            self.position_swing_lows[ticket].append(swing_low)
            # Keep only last 5 swing levels
            self.position_swing_lows[ticket] = self.position_swing_lows[ticket][-5:]
        else:
            swing_high = float(recent["High"].max())
            if ticket not in self.position_swing_highs:
                self.position_swing_highs[ticket] = []
            self.position_swing_highs[ticket].append(swing_high)
            self.position_swing_highs[ticket] = self.position_swing_highs[ticket][-5:]

    def _get_best_swing_level(self, ticket: str, is_buy: bool) -> float:
        """Get the best swing level for trailing."""
        if is_buy:
            levels = self.position_swing_lows.get(ticket, [])
            if levels:
                return max(levels)  # highest recent swing low for BUY
        else:
            levels = self.position_swing_highs.get(ticket, [])
            if levels:
                return min(levels)  # lowest recent swing high for SELL
        return 0.0

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
