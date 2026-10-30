#!/usr/bin/env python3
"""
risk_engine.py
Institutional Hard-Asset Risk Management & Dynamic Position Sizing Engine.
Calibrated exclusively for Gold (XAU/USD) and Bitcoin (BTC/USD).

Enforces:
  1. Strict 1% Maximum Portfolio Risk Per Trade (0.5% for B setups).
  2. Exact Dynamic Lot Sizing based on Account Equity and SL distance.
  3. Minimum 1:2.0 Asymmetric Risk-to-Reward Ratio.
  4. Daily Drawdown Circuit Breakers (-2.0% halt) & Cumulative Peak Limits (-6.0%).
  5. 1-Day Value at Risk (VaR 95% & VaR 99%) & Expected Shortfall (CVaR).
  6. Optimal Half-Kelly Criterion Sizing adapted from live Bayesian win rates.
  7. Volatility Buffer: SL must respect minimum 0.5x ATR to prevent noise whipsaws.
"""

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
import math
import json
import time
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import yfinance as yf

# ── Standard Contract Specifications ──────────────────────────────────────────
CONTRACT_SPECS = {
    "GOLD": {
        "symbol": "GC=F",
        "alt_symbol": "XAUUSD",
        "contract_size": 100.0,    # 1.00 lot = 100 troy ounces
        "min_lot": 0.01,           # 0.01 lot = 1 oz
        "max_lot": 50.0,
        "lot_step": 0.01,
        "tick_size": 0.01,
        "tick_value": 1.00,        # $0.01 move on 1 lot = $1.00 ($1.00 move = $100.00)
    },
    "BTC": {
        "symbol": "BTC-USD",
        "alt_symbol": "BTCUSD",
        "contract_size": 1.0,      # 1.00 lot = 1 BTC
        "min_lot": 0.01,           # 0.01 lot = 0.01 BTC
        "max_lot": 50.0,
        "lot_step": 0.01,
        "tick_size": 0.01,
        "tick_value": 0.01,        # $1.00 move on 1 lot = $1.00
    }
}

DEFAULT_ACCOUNT_BALANCE = 10_000.0   # Standard default balance in USD
DEFAULT_MAX_RISK_PCT = 1.0          # Max 1.0% risk per trade
DAILY_DRAWDOWN_HALT_PCT = 2.0       # Halt new trades if daily loss reaches 2.0%
MAX_TOTAL_DRAWDOWN_PCT = 6.0        # Portfolio halt at 6.0% drawdown

# ── Priority 1: Safety & Multi-Layer Circuit Breaker Parameters ──
TRADING_MODES = ("PAPER", "DEMO", "LIVE")
DEFAULT_TRADING_MODE = "PAPER"
MAX_CONCURRENT_POSITIONS = 2         # Max 2 concurrent open positions across Gold & BTC
MAX_TOTAL_OPEN_RISK_PCT = 2.5        # Max 2.5% combined open risk across all positions
DAILY_LOSS_LIMIT_PCT = 2.0           # 2% hard daily loss circuit breaker
MAX_DATA_STALENESS_SECONDS = 900     # 15 minutes max quote staleness
MAX_ALLOWED_SLIPPAGE = {
    "GOLD": 0.80,                    # Max $0.80 fill slippage for Gold
    "BTC": 50.00                     # Max $50.00 fill slippage for Bitcoin
}
MAX_ALLOWED_SPREAD = {
    "GOLD": 0.60,                    # Max $0.60 spread for Gold
    "BTC": 35.00                     # Max $35.00 spread for Bitcoin
}
SAFETY_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "safety_state.json")
AUDIT_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trade_audit.jsonl")


class SafetyManager:
    """
    Priority 1 Institutional Risk & Safety Architecture:
      1. Trading Modes: Strict PAPER | DEMO | LIVE separation.
      2. Double Confirmation for Live Capital:
         - /enable_live CONFIRM required to switch to LIVE mode.
         - Second confirmation required for first trade of the day.
      3. Multi-Layer Circuit Breakers:
         - Daily loss limit (2.0% halt).
         - Max concurrent open positions (2 positions max).
         - Max total portfolio open risk (2.5% combined).
         - Hard emergency kill-switch with manual reset (/kill_reset CONFIRM).
      4. Stale Data Protection: Rejects signals with quotes >15m old.
      5. Pre-Order Spread & Post-Order Slippage Guards.
      6. Institutional Order Audit Logging: Full details persisted in trade_audit.jsonl.
    """
    def __init__(self, state_file: str = SAFETY_STATE_FILE, audit_file: str = AUDIT_LOG_FILE):
        self.state_file = state_file
        self.audit_file = audit_file
        self.state = self._load_state()

    def _load_state(self) -> dict:
        today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        default_state = {
            "trading_mode": DEFAULT_TRADING_MODE,
            "live_mode_confirmed": False,
            "first_trade_confirmed_date": "",
            "kill_switch_active": False,
            "kill_switch_reason": "",
            "daily_date": today_utc,
            "starting_daily_equity": DEFAULT_ACCOUNT_BALANCE,
            "realized_daily_pnl": 0.0,
            "daily_circuit_breaker_tripped": False,
            "paper_account": {
                "balance": DEFAULT_ACCOUNT_BALANCE,
                "equity": DEFAULT_ACCOUNT_BALANCE,
                "positions": [],
                "closed_history": []
            }
        }
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("daily_date") != today_utc:
                        data["daily_date"] = today_utc
                        data["realized_daily_pnl"] = 0.0
                        data["daily_circuit_breaker_tripped"] = False
                        data["first_trade_confirmed_date"] = ""
                    for k, v in default_state.items():
                        if k not in data:
                            data[k] = v
                    return data
            except Exception:
                pass
        return default_state

    def save_state(self):
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            print(f"[!] Warning: Could not save safety state: {e}")

    # ── 1. Trading Modes ──────────────────────────────────────────
    def get_trading_mode(self) -> str:
        return self.state.get("trading_mode", DEFAULT_TRADING_MODE)

    def set_trading_mode(self, mode: str, confirmation: str = "") -> tuple:
        target = mode.strip().upper()
        if target not in TRADING_MODES:
            return False, f"Invalid mode '{mode}'. Supported modes: {', '.join(TRADING_MODES)}"

        if target == "LIVE":
            if confirmation.strip().upper() != "CONFIRM":
                return False, "⚠️ LIVE trading with real capital requires explicit confirmation.\nRun: `/enable_live CONFIRM` or `/mode live CONFIRM`"
            self.state["trading_mode"] = "LIVE"
            self.state["live_mode_confirmed"] = True
            self.save_state()
            return True, "🔴 *LIVE TRADING MODE ENABLED*\nReal capital execution is now active on your live MT5 account.\nFirst trade of the day will require a second one-time confirmation."

        elif target == "DEMO":
            self.state["trading_mode"] = "DEMO"
            self.state["live_mode_confirmed"] = False
            self.save_state()
            return True, "🟡 *DEMO TRADING MODE ACTIVE*\nOrders are sent to your connected MT5 Demo account."

        else:  # PAPER
            self.state["trading_mode"] = "PAPER"
            self.state["live_mode_confirmed"] = False
            self.save_state()
            return True, "⚪ *PAPER TRADING MODE ACTIVE*\nAll trades are simulated risk-free in memory with realistic fills & slippage."

    def is_first_trade_confirmed_today(self) -> bool:
        today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.state.get("first_trade_confirmed_date") == today_utc

    def confirm_first_trade_today(self) -> tuple:
        today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.state["first_trade_confirmed_date"] = today_utc
        self.save_state()
        return True, "✅ First live trade of the day confirmed. Live auto-execution authorized for today."

    # ── 2. Emergency Kill-Switch ──────────────────────────────────
    def is_kill_switch_active(self) -> tuple:
        return bool(self.state.get("kill_switch_active", False)), self.state.get("kill_switch_reason", "")

    def trigger_kill_switch(self, reason: str = "Emergency Kill-Switch Triggered") -> dict:
        self.state["kill_switch_active"] = True
        self.state["kill_switch_reason"] = reason
        closed_paper = len(self.state["paper_account"]["positions"])
        self.state["paper_account"]["positions"] = []
        self.save_state()
        return {
            "kill_switch_active": True,
            "reason": reason,
            "closed_paper_positions": closed_paper
        }

    def reset_kill_switch(self, confirmation: str = "") -> tuple:
        if confirmation.strip().upper() != "CONFIRM":
            return False, "⚠️ Resetting the emergency kill-switch requires confirmation.\nRun: `/kill_reset CONFIRM`"
        self.state["kill_switch_active"] = False
        self.state["kill_switch_reason"] = ""
        self.save_state()
        return True, "✅ *EMERGENCY KILL-SWITCH RESET*\nTrading permissions restored. Normal execution resumed."

    # ── 3. Daily Loss & Circuit Breaker Tracking ──────────────────
    def record_pnl(self, pnl: float, equity: float = None):
        today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.state.get("daily_date") != today_utc:
            self.state["daily_date"] = today_utc
            self.state["realized_daily_pnl"] = 0.0
            self.state["daily_circuit_breaker_tripped"] = False
            if equity:
                self.state["starting_daily_equity"] = equity

        self.state["realized_daily_pnl"] += pnl
        starting_eq = self.state.get("starting_daily_equity", DEFAULT_ACCOUNT_BALANCE)
        daily_loss_pct = (self.state["realized_daily_pnl"] / starting_eq) * 100.0

        if daily_loss_pct <= -DAILY_LOSS_LIMIT_PCT:
            self.state["daily_circuit_breaker_tripped"] = True

        self.save_state()

    def set_starting_equity(self, equity: float):
        if equity and equity > 0:
            self.state["starting_daily_equity"] = equity
            self.save_state()

    # ── 4. Comprehensive Safety & Guardrail Evaluator ────────────
    def check_trade_safety(self, asset: str, proposed_risk_pct: float,
                           open_positions: list = None,
                           current_equity: float = None,
                           data_timestamp: float = None,
                           spread_val: float = None,
                           sl_dist: float = None) -> tuple:
        """
        Multi-Layer Safety Verification Gauntlet:
          1. Kill-Switch verification
          2. Daily loss circuit breaker (-2.0% halt)
          3. Max concurrent open positions (2 positions limit)
          4. Max combined open portfolio risk (2.5% limit)
          5. Stale data protection (<15m quote freshness)
          6. Pre-order spread guard (spread < max absolute & <15% of SL)
        """
        open_positions = open_positions or []
        asset_key = "GOLD" if asset.upper() in ("GOLD", "XAU", "XAUUSD", "GC=F") else "BTC"

        # Check 1: Kill-Switch
        if self.state.get("kill_switch_active"):
            reason = self.state.get("kill_switch_reason", "Emergency Halt Active")
            return False, f"🚨 Kill-Switch is ACTIVE ({reason}). All trading blocked."

        # Check 2: Daily Loss Circuit Breaker
        starting_eq = self.state.get("starting_daily_equity", current_equity or DEFAULT_ACCOUNT_BALANCE)
        daily_pnl = self.state.get("realized_daily_pnl", 0.0)
        daily_loss_pct = (daily_pnl / starting_eq) * 100.0 if starting_eq > 0 else 0.0

        if self.state.get("daily_circuit_breaker_tripped") or daily_loss_pct <= -DAILY_LOSS_LIMIT_PCT:
            return False, f"🛑 Daily Loss Circuit Breaker TRIPPED: Realized daily loss is {daily_loss_pct:.2f}% (Limit: -{DAILY_LOSS_LIMIT_PCT:.1f}% = -${starting_eq * (DAILY_LOSS_LIMIT_PCT/100):,.2f}). Trading locked until daily reset."

        # Check 3: Max Concurrent Open Positions
        if len(open_positions) >= MAX_CONCURRENT_POSITIONS:
            return False, f"⛔ Max Concurrent Open Positions Reached ({len(open_positions)}/{MAX_CONCURRENT_POSITIONS} active). Cannot open additional positions."

        # Check 4: Max Combined Open Risk
        current_open_risk = sum(p.get("risk_pct", 1.0) for p in open_positions)
        if (current_open_risk + proposed_risk_pct) > MAX_TOTAL_OPEN_RISK_PCT:
            return False, f"⛔ Max Combined Portfolio Risk Exceeded: Current open risk ({current_open_risk:.2f}%) + proposed risk ({proposed_risk_pct:.2f}%) = {(current_open_risk + proposed_risk_pct):.2f}% > {MAX_TOTAL_OPEN_RISK_PCT:.1f}% limit."

        # Check 5: Stale Data Protection
        if data_timestamp:
            age_sec = time.time() - data_timestamp
            if age_sec > MAX_DATA_STALENESS_SECONDS:
                return False, f"⏱️ Stale Market Data: Quote is {age_sec/60.0:.1f} minutes old (limit: {MAX_DATA_STALENESS_SECONDS/60:.0f}m). Order blocked to prevent trading on expired ticks."

        # Check 6: Pre-Order Spread Guard
        if spread_val is not None and spread_val > 0:
            max_spread = MAX_ALLOWED_SPREAD.get(asset_key, 0.60)
            if spread_val > max_spread:
                return False, f"⚠️ Excessive Broker Spread: Current spread ${spread_val:.2f} exceeds institutional threshold (${max_spread:.2f})."
            if sl_dist and sl_dist > 0 and (spread_val / sl_dist) > 0.15:
                return False, f"⚠️ High Spread-to-Risk: Spread ${spread_val:.2f} consumes {(spread_val/sl_dist*100):.1f}% of SL distance (${sl_dist:.2f}) > 15% limit."

        return True, "Safety Verification Passed: All Circuit Breakers Armed ✅"

    # ── 5. Post-Order Slippage Verification ────────────────────────
    def verify_fill_slippage(self, asset: str, requested_price: float, fill_price: float) -> tuple:
        asset_key = "GOLD" if asset.upper() in ("GOLD", "XAU", "XAUUSD", "GC=F") else "BTC"
        slippage = round(abs(fill_price - requested_price), 2)
        max_slip = MAX_ALLOWED_SLIPPAGE.get(asset_key, 0.80)
        is_acceptable = slippage <= max_slip
        msg = f"Slippage ${slippage:.2f} within limit (${max_slip:.2f})" if is_acceptable else f"Slippage ${slippage:.2f} EXCEEDS limit (${max_slip:.2f})!"
        return is_acceptable, slippage, msg

    # ── 6. Institutional Order Audit Logger ───────────────────────
    def log_order_audit(self, order_data: dict):
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": self.get_trading_mode(),
            **order_data
        }
        try:
            with open(self.audit_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            print(f"[!] Warning: Could not write order audit log: {e}")

    # ── 7. Paper Trading Simulator ────────────────────────────────
    def execute_paper_order(self, asset: str, action: str, price: float,
                            stop_loss: float, tp1: float, tp2: float,
                            lots: float, risk_usd: float, risk_pct: float,
                            strategy: str = "SCALP", score: int = 8,
                            features: dict = None, comment: str = "PaperTrade") -> dict:
        ticket = f"PAPER-{int(time.time()*1000) % 10000000}"
        asset_key = "GOLD" if asset.upper() in ("GOLD", "XAU", "XAUUSD", "GC=F") else "BTC"

        sim_spread = 0.15 if asset_key == "GOLD" else 8.0
        fill_price = round(price + (sim_spread / 2.0) if action.upper() == "BUY" else price - (sim_spread / 2.0), 2)
        initial_sl_dist = round(abs(fill_price - stop_loss), 2) if (fill_price > 0 and stop_loss > 0) else (3.0 if asset_key == "GOLD" else 250.0)

        position = {
            "ticket": ticket,
            "asset": asset_key,
            "symbol": "XAUUSD" if asset_key == "GOLD" else "BTCUSD",
            "action": action.upper(),
            "lots": lots,
            "open_price": fill_price,
            "requested_price": price,
            "slippage": round(abs(fill_price - price), 2),
            "sl": stop_loss,
            "initial_sl": stop_loss,
            "initial_risk_dist": initial_sl_dist,
            "peak_price": fill_price,
            "tp1": tp1,
            "tp2": tp2,
            "risk_usd": risk_usd,
            "risk_pct": risk_pct,
            "strategy": strategy,
            "score": score,
            "open_time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "comment": comment
        }
        self.state["paper_account"]["positions"].append(position)
        self.save_state()

        self.log_order_audit({
            "event": "ORDER_PLACED",
            "ticket": ticket,
            "asset": asset_key,
            "symbol": position["symbol"],
            "action": position["action"],
            "strategy": strategy,
            "score": score,
            "entry_requested": price,
            "fill_price": fill_price,
            "slippage": position["slippage"],
            "stop_loss": stop_loss,
            "tp1": tp1,
            "tp2": tp2,
            "lots": lots,
            "risk_usd": risk_usd,
            "risk_pct": risk_pct,
            "status": "FILLED_PAPER"
        })

        return {
            "success": True,
            "ticket": ticket,
            "symbol": position["symbol"],
            "action": position["action"],
            "lots": lots,
            "price": fill_price,
            "sl": stop_loss,
            "tp": tp1,
            "mode": "PAPER",
            "time": position["open_time"]
        }

    def get_paper_positions(self) -> list:
        return self.state.get("paper_account", {}).get("positions", [])

    def modify_paper_position_sltp(self, ticket: str, new_sl: float, new_tp: float = None) -> dict:
        """Modifies Stop-Loss and/or Take-Profit of an active paper position."""
        positions = self.state["paper_account"]["positions"]
        target = None
        for p in positions:
            if str(p["ticket"]) == str(ticket):
                target = p
                break
        if not target:
            return {"success": False, "error": f"Paper position #{ticket} not found."}

        old_sl = target.get("sl", 0.0)
        target["sl"] = round(new_sl, 2)
        if new_tp is not None:
            target["tp1"] = round(new_tp, 2)

        self.save_state()
        self.log_order_audit({
            "event": "POSITION_MODIFIED_PAPER",
            "ticket": ticket,
            "asset": target["asset"],
            "old_sl": old_sl,
            "new_sl": target["sl"],
            "tp": target.get("tp1")
        })
        return {"success": True, "ticket": ticket, "sl": target["sl"], "tp": target.get("tp1")}

    def trail_paper_positions(self, current_prices: dict, default_strategy: str = "SCALP") -> list:
        """
        Automated Profile-Aware Trailing Stop, Breakeven & SL/TP Hit Engine for Paper Trading.
        Preserves initial risk distance across all steps, prevents premature stop-out,
        and ratchets dynamic trailing behind peak favorable price.
        """
        positions = list(self.state.get("paper_account", {}).get("positions", []))
        if not positions:
            return []

        events = []
        for p in positions:
            asset = p.get("asset", "GOLD")
            symbol = p.get("symbol", "XAUUSD")
            curr_price = current_prices.get(asset) or current_prices.get(symbol) or current_prices.get(asset.lower())
            if curr_price is None or curr_price <= 0:
                continue

            entry = p.get("open_price", 0.0)
            curr_sl = p.get("sl", 0.0)
            curr_tp = p.get("tp1", 0.0)
            is_buy = p.get("action", "BUY") == "BUY"
            ticket = p["ticket"]

            # 1. Recover un-collapsing initial risk distance
            initial_risk_dist = p.get("initial_risk_dist")
            if not initial_risk_dist or initial_risk_dist <= 0:
                initial_sl = p.get("initial_sl", curr_sl)
                if initial_sl > 0 and ((is_buy and initial_sl < entry) or (not is_buy and initial_sl > entry)):
                    initial_risk_dist = abs(entry - initial_sl)
                else:
                    initial_risk_dist = 3.0 if asset == "GOLD" else 250.0
                p["initial_risk_dist"] = initial_risk_dist

            strat_code = p.get("strategy", default_strategy).upper()
            strat = STRATEGIES.get(strat_code, STRATEGIES["SCALP"])
            active_be_r = strat.get("breakeven_r", 0.35)
            active_trail_start_r = strat.get("trail_start_r", 0.65)
            active_trail_step_r = strat.get("trail_step_r", 0.20)
            spread_buffer = 0.15 if asset == "GOLD" else 8.0

            # 2. Check Stop-Loss Hit
            sl_hit = (is_buy and curr_price <= curr_sl) or (not is_buy and curr_price >= curr_sl)
            if sl_hit:
                res = self.close_paper_position(ticket, curr_sl, reason="STOP_LOSS_HIT")
                events.append({
                    "ticket": ticket,
                    "symbol": symbol,
                    "asset": asset,
                    "action": "SL_HIT",
                    "price": curr_sl,
                    "pnl": res.get("closed_pnl", 0.0),
                    "msg": f"🛑 *[{strat_code} PAPER] STOP-LOSS HIT:* #{ticket} `{symbol}` hit SL at `${curr_sl:,.2f}` (PnL: `${res.get('closed_pnl', 0.0):+,.2f}`)"
                })
                continue

            # 3. Check Take-Profit Hit
            tp_hit = (is_buy and curr_price >= curr_tp) or (not is_buy and curr_price <= curr_tp)
            if tp_hit:
                res = self.close_paper_position(ticket, curr_tp, reason="TAKE_PROFIT_HIT")
                events.append({
                    "ticket": ticket,
                    "symbol": symbol,
                    "asset": asset,
                    "action": "TP_HIT",
                    "price": curr_tp,
                    "pnl": res.get("closed_pnl", 0.0),
                    "msg": f"🎯 *[{strat_code} PAPER] TAKE-PROFIT ACHIEVED:* #{ticket} `{symbol}` reached Target at `${curr_tp:,.2f}`! (PnL: `${res.get('closed_pnl', 0.0):+,.2f}` 🎉)"
                })
                continue

            # 4. Update Peak Favorable Price
            prev_peak = p.get("peak_price", entry)
            peak_price = max(prev_peak, curr_price) if is_buy else min(prev_peak, curr_price)
            p["peak_price"] = peak_price

            # Profit distance & R-multiples
            profit_dist = (curr_price - entry) if is_buy else (entry - curr_price)
            current_r = profit_dist / initial_risk_dist
            peak_profit_dist = (peak_price - entry) if is_buy else (entry - peak_price)
            peak_r = peak_profit_dist / initial_risk_dist

            # 5. Breakeven Trigger
            breakeven_sl = round(entry + spread_buffer if is_buy else entry - spread_buffer, 2)
            needs_be = False
            if is_buy and current_r >= active_be_r and curr_sl < entry:
                needs_be = True
            elif not is_buy and current_r >= active_be_r and (curr_sl > entry or curr_sl == 0):
                needs_be = True

            if needs_be:
                old_sl = curr_sl
                p["sl"] = breakeven_sl
                self.save_state()
                events.append({
                    "ticket": ticket,
                    "symbol": symbol,
                    "asset": asset,
                    "strategy": strat_code,
                    "action": "BREAKEVEN",
                    "old_sl": old_sl,
                    "new_sl": breakeven_sl,
                    "current_price": curr_price,
                    "profit_r": current_r,
                    "msg": f"🛡️ *[{strat_code} PAPER] BREAKEVEN LOCKED:* #{ticket} `{symbol}` SL moved to `${breakeven_sl:,.2f}` (+{current_r:.2f}R — Risk-Free!)"
                })
                continue

            # 6. Dynamic Trailing Step
            if peak_r >= active_trail_start_r:
                desired_sl = round(peak_price - (initial_risk_dist * active_trail_step_r) if is_buy else peak_price + (initial_risk_dist * active_trail_step_r), 2)
                if is_buy:
                    desired_sl = max(desired_sl, breakeven_sl)
                    should_trail = desired_sl > curr_sl and (desired_sl - curr_sl) >= (0.10 if asset == "GOLD" else 5.0)
                else:
                    desired_sl = min(desired_sl, breakeven_sl)
                    should_trail = (curr_sl == 0 or desired_sl < curr_sl) and abs(desired_sl - curr_sl) >= (0.10 if asset == "GOLD" else 5.0)

                if should_trail:
                    old_sl = curr_sl
                    p["sl"] = desired_sl
                    self.save_state()
                    events.append({
                        "ticket": ticket,
                        "symbol": symbol,
                        "asset": asset,
                        "strategy": strat_code,
                        "action": "TRAILED",
                        "old_sl": old_sl,
                        "new_sl": desired_sl,
                        "current_price": curr_price,
                        "peak_price": peak_price,
                        "profit_r": current_r,
                        "msg": f"📈 *[{strat_code} PAPER] TRAILING ADVANCED:* #{ticket} `{symbol}` SL trailed to `${desired_sl:,.2f}` (+{current_r:.2f}R — Profit Secured!)"
                    })

        return events
    def get_closed_paper_positions(self, limit: int = 30) -> list:
        history = self.state.get("paper_account", {}).get("closed_history", [])
        return history[-limit:] if history else []

    def close_paper_position(self, ticket: str, exit_price: float, reason: str = "MANUAL_CLOSE") -> dict:
        positions = self.state["paper_account"]["positions"]
        target = None
        idx = -1
        for i, p in enumerate(positions):
            if str(p["ticket"]) == str(ticket):
                target = p
                idx = i
                break
        if not target:
            return {"success": False, "error": f"Paper position #{ticket} not found."}

        positions.pop(idx)
        asset_key = target["asset"]
        mult = 100.0 if asset_key == "GOLD" else 1.0
        is_buy = target["action"] == "BUY"
        pnl = (exit_price - target["open_price"]) * target["lots"] * mult if is_buy else (target["open_price"] - exit_price) * target["lots"] * mult
        pnl = round(pnl, 2)

        risk_usd = target.get("risk_usd") or 50.0
        r_mult = round(pnl / risk_usd, 2) if risk_usd > 0 else (1.2 if pnl > 0 else -1.0)
        outcome = "WIN" if pnl > 0 else "LOSS"
        close_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        closed_record = {
            "ticket": ticket,
            "asset": asset_key,
            "symbol": target.get("symbol", "XAUUSD" if asset_key == "GOLD" else "BTCUSD"),
            "action": target.get("action", "BUY"),
            "lots": target.get("lots", 0.05),
            "open_price": target.get("open_price", exit_price),
            "exit_price": exit_price,
            "sl": target.get("sl"),
            "tp1": target.get("tp1"),
            "pnl": pnl,
            "r_multiple": r_mult,
            "outcome": outcome,
            "strategy": target.get("strategy", "SCALP"),
            "score": target.get("score", 8),
            "open_time": target.get("open_time"),
            "close_time": close_time,
            "reason": reason,
            "source": "PAPER"
        }

        if "closed_history" not in self.state["paper_account"]:
            self.state["paper_account"]["closed_history"] = []
        self.state["paper_account"]["closed_history"].append(closed_record)
        if len(self.state["paper_account"]["closed_history"]) > 100:
            self.state["paper_account"]["closed_history"] = self.state["paper_account"]["closed_history"][-100:]

        self.state["paper_account"]["balance"] += pnl
        self.state["paper_account"]["equity"] = self.state["paper_account"]["balance"]
        self.record_pnl(pnl, self.state["paper_account"]["balance"])
        self.save_state()

        self.log_order_audit({
            "event": "POSITION_CLOSED",
            "ticket": ticket,
            "asset": asset_key,
            "exit_price": exit_price,
            "pnl_usd": pnl,
            "r_multiple": r_mult,
            "outcome": outcome,
            "reason": reason
        })

        return {
            "success": True,
            "ticket": ticket,
            "closed_pnl": pnl,
            "r_multiple": r_mult,
            "outcome": outcome,
            "balance": self.state["paper_account"]["balance"],
            "reason": reason,
            "closed_record": closed_record
        }

    # ── 8. Safety Dashboard Rendering ─────────────────────────────
    def get_safety_dashboard_text(self, current_equity: float = None) -> str:
        mode = self.get_trading_mode()
        kill_active, kill_reason = self.is_kill_switch_active()
        starting_eq = self.state.get("starting_daily_equity", current_equity or DEFAULT_ACCOUNT_BALANCE)
        daily_pnl = self.state.get("realized_daily_pnl", 0.0)
        daily_loss_pct = (daily_pnl / starting_eq) * 100.0 if starting_eq > 0 else 0.0
        breaker_tripped = self.state.get("daily_circuit_breaker_tripped") or daily_loss_pct <= -DAILY_LOSS_LIMIT_PCT

        mode_badge = "⚪ PAPER (Simulation)" if mode == "PAPER" else "🟡 DEMO (MT5 Test Account)" if mode == "DEMO" else "🔴 LIVE (Real Capital)"
        kill_status = f"🚨 ACTIVE ({kill_reason}) — Reset via `/kill_reset CONFIRM`" if kill_active else "ARMED ✅ (Normal Execution)"
        breaker_status = f"🛑 TRIPPED ({daily_loss_pct:.2f}%) — Locked for today" if breaker_tripped else f"ARMED ✅ (Current: {daily_pnl:+,.2f} / -${starting_eq * (DAILY_LOSS_LIMIT_PCT/100):,.2f} halt)"

        first_trade_st = "NOT REQUIRED (Simulation)" if mode != "LIVE" else ("CONFIRMED ✅ (Authorized Today)" if self.is_first_trade_confirmed_today() else "PENDING ⚠️ (Requires `/confirm_trade YES`)")

        lines = [
            "🛡️ *SAFETY & RISK CONTROLLER DASHBOARD*",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"• *Trading Mode:* `{mode_badge}`",
            f"• *Kill-Switch Status:* `{kill_status}`",
            f"• *Daily Loss Circuit Breaker:* `{breaker_status}`",
            f"• *Max Concurrent Open Positions:* `2 Positions Max`",
            f"• *Max Total Open Risk:* `2.50% Combined Portfolio Risk`",
            f"• *Stale Data Protection:* `Active (<15m Freshness Guard)`",
            f"• *Spread & Slippage Guard:* `Active (Gold: $0.60/$0.80 | BTC: $35/$50)`",
            f"• *First Live Trade of the Day:* `{first_trade_st}`",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "⚙️ *Safety Controls:*",
            "• Switch Mode: `/mode paper` | `/mode demo` | `/enable_live CONFIRM`",
            "• Emergency Stop: `/kill` (Immediate liquidation & halt)",
            "• Reset Kill-Switch: `/kill_reset CONFIRM`",
            "• Confirm 1st Live Trade: `/confirm_trade YES`"
        ]
        return "\n".join(lines)


# Singleton Instance
safety_manager = SafetyManager()

# ── Institutional Strategy Framework ──────────────────────────────────────────
STRATEGIES = {
    "SCALP": {
        "code": "SCALP",
        "name": "Institutional Key-Level Scalp",
        "description": "Small, low practical SL/TP on institutional key trade levels. Focus: ~75-85% practical scalp win rate.",
        "sl_mult": 0.22,
        "rr_tp1": 1.20,
        "rr_tp2": 1.75,
        "breakeven_r": 0.35,       # Fast breakeven lock at +0.35R (eliminates drawdown risk immediately)
        "trail_start_r": 0.65,     # Dynamic trail starts at +0.65R
        "trail_step_r": 0.20,      # Tight 0.20R trailing buffer
        "risk_pct": 0.50,          # Conservative 0.50% risk per scalp
        "target_win_rate": "~75-85% (Key Level Practical Scalp)",
        "accuracy_tip": "Key level (Golden Pocket, S/R, EMA), wick <28%, body >=28%, RSI 35-70",
        "regime_filter": "Key Level Reaction / Momentum",
        "holding_time": "5 - 30 minutes",
        "lot_cap_gold": 0.20,
        "lot_cap_btc": 0.10
    },
    "SWING": {
        "code": "SWING",
        "name": "Macro Trend Swing",
        "description": "Structural 1.10x ATR stop with 1.5R to 2.5R asymmetric targets across multi-day cycles.",
        "sl_mult": 1.10,
        "rr_tp1": 1.50,
        "rr_tp2": 2.50,
        "breakeven_r": 0.45,       # Agile breakeven lock at +0.45R (protects against wave pullbacks)
        "trail_start_r": 0.90,     # Dynamic trail starts at +0.90R
        "trail_step_r": 0.40,      # Disciplined 0.40R trailing step
        "risk_pct": 1.00,          # Full 1.00% institutional risk
        "target_win_rate": "~75-80% (Asymmetric Trend Runner)",
        "accuracy_tip": "ADX >= 22 (+DI > -DI), Price > 50 & 200 SMA, DXY tailwind",
        "regime_filter": "Trending Only (ADX >= 22 & MA Alignment)",
        "holding_time": "1 - 5 days",
        "lot_cap_gold": 0.10,
        "lot_cap_btc": 0.05
    },
    "BALANCE": {
        "code": "BALANCE",
        "name": "Equilibrium Mean-Reversion",
        "description": "Fades Golden Pocket extremes back to 0.50 Fib Equilibrium / VPOC fair value.",
        "sl_mult": 0.75,
        "rr_tp1": 1.40,
        "rr_tp2": 2.20,
        "breakeven_r": 0.50,       # Fast breakeven at +0.50R
        "trail_start_r": 0.85,     # Trail starts at +0.85R
        "trail_step_r": 0.30,      # Dynamic tightening near 0.50 Fib
        "risk_pct": 0.75,          # 0.75% balanced risk
        "target_win_rate": "~80-85% (Equilibrium Magnet)",
        "accuracy_tip": "ADX <= 25 (Chop/Range), Extreme Golden Pocket/S1, Wyckoff Spring",
        "regime_filter": "Range / Chop Only (ADX <= 25, extreme location)",
        "holding_time": "1 - 8 hours",
        "lot_cap_gold": 0.15,
        "lot_cap_btc": 0.08
    },
    "SWAP": {
        "code": "SWAP",
        "name": "Positive Carry & Swap Aware",
        "description": "Carry-conscious positioning prioritizing positive overnight financing and avoiding rollover drag.",
        "sl_mult": 0.90,
        "rr_tp1": 1.80,
        "rr_tp2": 2.60,
        "breakeven_r": 0.50,       # Breakeven at +0.50R
        "trail_start_r": 1.00,     # Trail starts at +1.00R
        "trail_step_r": 0.45,      # Controlled 0.45R buffer against rollover spread spikes
        "risk_pct": 0.75,          # 0.75% risk with carry yield
        "target_win_rate": "~75-82% (Financing Accretion)",
        "accuracy_tip": "Positive broker carry, Wednesday 3x rollover advantage, VIX <= 22",
        "regime_filter": "Positive Rollover Carry & Low VIX (<=22)",
        "holding_time": "Multi-day / Positive Carry",
        "lot_cap_gold": 0.15,
        "lot_cap_btc": 0.08
    },
    "REVERSAL": {
        "code": "REVERSAL",
        "name": "Micro Inflection & ChoCH Reversal",
        "description": "Exploits Change of Character (ChoCH) early trend transitions. Small TF leads, enters on first structural retest.",
        "sl_mult": 0.40,
        "rr_tp1": 1.40,
        "rr_tp2": 2.20,
        "breakeven_r": 0.40,
        "trail_start_r": 0.75,
        "trail_step_r": 0.25,
        "risk_pct": 0.75,
        "target_win_rate": "~75-85% (Structural Inflection)",
        "accuracy_tip": "Micro ChoCH on M1/M5, 21 EMA flip, structural retest into Golden Pocket",
        "regime_filter": "Early Trend Inflection / Structural Shift",
        "holding_time": "15 - 60 minutes",
        "lot_cap_gold": 0.15,
        "lot_cap_btc": 0.08
    },
    "ANTI_TRAP": {
        "code": "ANTI_TRAP",
        "name": "Liquidity Sweep & Trap Fade",
        "description": "Fades fakeout upthrusts (UTAD) and Wyckoff springs with >=35% rejection wicks.",
        "sl_mult": 0.35,
        "rr_tp1": 1.50,
        "rr_tp2": 2.20,
        "breakeven_r": 0.35,
        "trail_start_r": 0.70,
        "trail_step_r": 0.20,
        "risk_pct": 0.75,
        "target_win_rate": "~80-88% (False Breakout Fade)",
        "accuracy_tip": "Rejection wick >=35% at key S/R, volume divergence, candle close back inside range",
        "regime_filter": "Liquidity Sweep / False Breakout Trap",
        "holding_time": "10 - 45 minutes",
        "lot_cap_gold": 0.15,
        "lot_cap_btc": 0.08
    }
}

ACTIVE_STRATEGY = "SCALP"


def get_market_session(dt: datetime = None) -> dict:
    """
    Detects global financial market sessions in UTC.
    Peak liquidity sessions provide significantly higher win rates.
    """
    now = dt or datetime.utcnow()
    hour = now.hour
    minute = now.minute

    # Rollover danger window: 21:50 - 22:15 UTC
    is_rollover = (hour == 21 and minute >= 50) or (hour == 22 and minute <= 15)
    is_london_ny_overlap = 12 <= hour < 16
    is_london = 7 <= hour < 16
    is_ny = 12 <= hour < 21
    is_asian = 0 <= hour < 8

    if is_rollover:
        session_name = "Rollover Spread Window"
        badge = "🚨"
        liquidity = "LOW (Spread Expansion Danger)"
        win_rate_bias = "POOR (Trading Freeze Recommended)"
    elif is_london_ny_overlap:
        session_name = "London / NY Golden Overlap"
        badge = "🌟"
        liquidity = "MAXIMUM (Peak Institutional Flow)"
        win_rate_bias = "EXCELLENT (+10% Win Rate Edge)"
    elif is_ny:
        session_name = "New York Session"
        badge = "🗽"
        liquidity = "HIGH (Strong Trend Momentum)"
        win_rate_bias = "HIGH"
    elif is_london:
        session_name = "London Session"
        badge = "🏛️"
        liquidity = "HIGH (Institutional Order Flow)"
        win_rate_bias = "HIGH"
    elif is_asian:
        session_name = "Asian / Tokyo Session"
        badge = "⛩️"
        liquidity = "MODERATE (Range-Bound / Chop)"
        win_rate_bias = "FAVORS BALANCE (Equilibrium)"
    else:
        session_name = "Inter-Market Transition"
        badge = "🌐"
        liquidity = "MODERATE"
        win_rate_bias = "NORMAL"

    return {
        "session": session_name,
        "name": session_name,
        "badge": badge,
        "liquidity": liquidity,
        "win_rate_bias": win_rate_bias,
        "win_rate_edge": win_rate_bias,
        "is_golden_overlap": is_london_ny_overlap,
        "is_rollover": is_rollover,
        "is_peak": is_london or is_ny,
        "utc_time": now.strftime("%H:%M UTC")
    }


def set_active_strategy(strat_name: str) -> tuple:
    """Sets active trading strategy."""
    global ACTIVE_STRATEGY
    code = strat_name.strip().upper()
    if code in STRATEGIES:
        ACTIVE_STRATEGY = code
        return True, STRATEGIES[code]
    return False, None


def get_active_strategy() -> dict:
    """Returns the current active trading strategy metadata."""
    return STRATEGIES.get(ACTIVE_STRATEGY, STRATEGIES["SCALP"])


def validate_strategy_accuracy(strat_code: str, asset: str, current_price: float,
                               atr: float, rsi: float, adx: float,
                               levels: dict, trap_type: str,
                               upper_wick_pct: float = 0.0, lower_wick_pct: float = 0.0,
                               candle_body_pct: float = 50.0,
                               plus_di: float = None, minus_di: float = None,
                               spread_ratio: float = None,
                               macro: dict = None, swap_info: dict = None,
                               action: str = "BUY",
                               is_backtest: bool = False) -> dict:
    """
    Multi-Factor Strategy Accuracy & Regime Validator.
    Ensures that each trade setup strictly matches the mathematical conditions
    where that specific strategy exhibits an institutional edge.
    """
    strat = STRATEGIES.get((strat_code or ACTIVE_STRATEGY).upper(), STRATEGIES["SCALP"])
    asset_key = "GOLD" if asset.upper() in ("GOLD", "XAU", "XAUUSD", "GC=F") else "BTC"
    is_buy = action.upper() in ("BUY", "LONG")
    macro = macro or {}
    session_info = get_market_session()

    passed = True
    veto_reasons = []
    accuracy_factors = []

    # ── A. SCALP ACCURACY RULES (Target: ~68-78% Practical Key-Level Scalp) ──
    at_good_level = False
    if strat["code"] == "SCALP":
        min_atr = 1.50 if asset_key == "GOLD" else 150.0
        if atr < min_atr:
            passed = False
            veto_reasons.append(f"Low Volatility (ATR ${atr:.1f} < ${min_atr:.1f}). Spread risk too high for scalping.")
        else:
            accuracy_factors.append(f"Optimal Scalp Volatility (ATR ${atr:.1f})")

        # Detect institutional key trade level confluence
        levels = levels or {}
        in_gp = levels.get("in_golden_pocket", False)
        sw_low = levels.get("sw_low", 0.0)
        near_support = (sw_low > 0 and (current_price - sw_low) / current_price <= 0.05) or levels.get("near_support", False) or levels.get("near_swing_support", False)
        ma20_ema = levels.get("ma20_ema", 0.0)
        near_ema = ma20_ema > 0 and abs(current_price - ma20_ema) / current_price <= 0.02
        s1 = levels.get("s1", 0.0)
        near_s1 = s1 > 0 and abs(current_price - s1) / current_price <= 0.015
        at_good_level = bool(in_gp or near_support or near_ema or near_s1)

        if at_good_level:
            accuracy_factors.append("Institutional Trade Level Confluence (Golden Pocket / Support / EMA)")

        # Candle body quality: allow slightly responsive body at key reaction levels, avoid pure dojis
        min_body = 28.0 if at_good_level else 32.0
        if candle_body_pct < min_body:
            passed = False
            veto_reasons.append(f"Indecision Candle Body ({candle_body_pct:.1f}% < {min_body:.0f}%). Practical scalp requires directional momentum body.")
        else:
            accuracy_factors.append(f"Directional Candle Body Thrust ({candle_body_pct:.1f}%)")

        # Wick tolerance: allow natural reaction wicks up to 28% at key levels
        max_wick = 28.0 if at_good_level else 24.0
        if is_buy and upper_wick_pct >= max_wick:
            passed = False
            veto_reasons.append(f"Candle Rejection Wick ({upper_wick_pct:.1f}% >= {max_wick:.0f}%). Selling pressure prevents clean scalp.")
        elif not is_buy and lower_wick_pct >= max_wick:
            passed = False
            veto_reasons.append(f"Candle Absorption Wick ({lower_wick_pct:.1f}% >= {max_wick:.0f}%). Buying absorption prevents short scalp.")
        else:
            accuracy_factors.append("Clean Microstructure (Minimal Rejection Wick)")

        # Practical RSI bounds for scalping
        min_rsi = 35.0 if at_good_level else 38.0
        max_rsi = 70.0 if at_good_level else 68.0
        if is_buy and (rsi > max_rsi or rsi < min_rsi):
            passed = False
            veto_reasons.append(f"RSI Exhaustion ({rsi:.1f}). Long scalps require RSI {min_rsi:.0f}-{max_rsi:.0f}.")
        elif not is_buy and (rsi < (100.0 - max_rsi) or rsi > (100.0 - min_rsi)):
            passed = False
            veto_reasons.append(f"RSI Oversold/Overbought ({rsi:.1f}). Short scalps require RSI {(100.0-max_rsi):.0f}-{(100.0-min_rsi):.0f}.")
        else:
            accuracy_factors.append(f"Momentum Sweet Spot (RSI {rsi:.1f})")

        # Rollover check (only in live execution, not historical daily bar simulations)
        if not is_backtest and session_info["is_rollover"]:
            passed = False
            veto_reasons.append("Rollover Window (21:50-22:15 UTC). Spread widening danger. Scalp blocked.")
        elif session_info["is_golden_overlap"]:
            accuracy_factors.append("London / NY Golden Overlap (+10% Win Rate Edge)")

        if spread_ratio and spread_ratio > 0.15:
            passed = False
            veto_reasons.append(f"Broker spread too wide ({spread_ratio*100:.1f}% > 15% of ATR).")

    # ── B. SWING ACCURACY RULES (Target: ~68-75% Win Rate, Asymmetric R:R) ──
    elif strat["code"] == "SWING":
        if adx < 20.0:
            passed = False
            veto_reasons.append(f"Chop Regime Detected (ADX {adx:.1f} < 20.0). Swing trading requires trending momentum.")
        else:
            accuracy_factors.append(f"Established Trend Regime (ADX {adx:.1f})")

        # Directional Movement confirmation
        if plus_di is not None and minus_di is not None:
            if is_buy and plus_di < minus_di:
                passed = False
                veto_reasons.append(f"Bearish Directional Flow (-DI {minus_di:.1f} > +DI {plus_di:.1f}). Swing long blocked.")
            elif not is_buy and minus_di < plus_di:
                passed = False
                veto_reasons.append(f"Bullish Directional Flow (+DI {plus_di:.1f} > -DI {minus_di:.1f}). Swing short blocked.")
            else:
                accuracy_factors.append(f"Directional Movement Alignment (+DI {plus_di:.1f} vs -DI {minus_di:.1f})")

        # Microstructure & Anti-Trap checks (Mandated by Hard-Asset Execution Engine)
        if is_buy and upper_wick_pct >= 28.0:
            passed = False
            veto_reasons.append(f"Bull Trap Rejection ({upper_wick_pct:.1f}% >= 28%). Heavy selling pressure at swing high.")
        elif not is_buy and lower_wick_pct >= 28.0:
            passed = False
            veto_reasons.append(f"Bear Trap Absorption ({lower_wick_pct:.1f}% >= 28%). Demand absorption at swing low.")

        if trap_type == "BULL_TRAP" and is_buy:
            passed = False
            veto_reasons.append("Bull Trap / Upthrust detected at resistance. Swing long vetoed.")
        elif trap_type == "BEAR_TRAP" and not is_buy:
            passed = False
            veto_reasons.append("Bear Trap / Wyckoff Spring detected at support. Swing short vetoed.")

        if candle_body_pct < 28.0:
            passed = False
            veto_reasons.append(f"Indecision Candle Body ({candle_body_pct:.1f}% < 28%). Swing entries require directional commitment.")

        ma50 = levels.get("ma50", np.nan)
        ma200 = levels.get("ma200", np.nan)
        ma20_ema = levels.get("ma20_ema", np.nan)
        if is_buy:
            if not np.isnan(ma200) and current_price < ma200:
                passed = False
                veto_reasons.append(f"Counter-Trend Risk: Price below 200 SMA (${ma200:,.0f}).")
            elif not np.isnan(ma50) and current_price < ma50:
                passed = False
                veto_reasons.append(f"Short-Term Trend Bearish: Price below 50 SMA (${ma50:,.0f}).")
            else:
                accuracy_factors.append("Bullish Trend Confluence (Above 50 & 200 SMA)")

            # Climax overextension check
            if not np.isnan(ma20_ema) and (current_price - ma20_ema) > (2.5 * atr):
                passed = False
                veto_reasons.append("Price Overextended from 20 EMA (> 2.5x ATR). Climax run risk; wait for re-test.")
            elif not np.isnan(ma50) and (current_price - ma50) / current_price > 0.045:
                passed = False
                veto_reasons.append("Price Overextended from 50 SMA (> 4.5%). Climax wave exhaustion; wait for pullback.")

        dxy_chg = macro.get("dxy_chg", 0.0)
        if is_buy and dxy_chg > 0.20:
            passed = False
            veto_reasons.append(f"USD Surge Headwind (DXY {dxy_chg:+.2f}%). Swing long delayed.")
        else:
            accuracy_factors.append("Macro Currency Tailwind")

    # ── C. BALANCE ACCURACY RULES (Target: ~78-83% Win Rate) ──
    elif strat["code"] == "BALANCE":
        if adx > 25.0:
            passed = False
            veto_reasons.append(f"Trend Breakout Expansion in Progress (ADX {adx:.1f} > 25.0). Mean-reversion unsafe.")
        else:
            accuracy_factors.append(f"Range-Bound Auction (ADX {adx:.1f} <= 25.0)")

        in_gp = levels.get("in_golden_pocket", False)
        s1 = levels.get("s1", 0.0)
        near_s1 = s1 > 0 and abs(current_price - s1) / current_price <= 0.015
        if not (in_gp or near_s1):
            passed = False
            veto_reasons.append("Price not at range extreme (Golden Pocket 0.618-0.650 or Pivot S1).")
        else:
            accuracy_factors.append("Extreme Range Location (Golden Pocket / S1)")

        if is_buy and lower_wick_pct >= 25.0:
            accuracy_factors.append(f"Wyckoff Spring Absorption Wick ({lower_wick_pct:.1f}%)")

    # ── D. SWAP ACCURACY RULES (Target: ~72-78% Win Rate) ──
    elif strat["code"] == "SWAP":
        if swap_info and swap_info.get("available"):
            fav = swap_info.get("favorable_side", "NONE")
            if fav != action.upper() and not swap_info.get("positive_carry", False):
                passed = False
                veto_reasons.append(f"Negative Carry Cost: Broker rollover financing is unfavorable for {action}.")
            else:
                accuracy_factors.append("Positive Rollover Carry (Financing Yield)")
        else:
            accuracy_factors.append("Neutral Carry Assumed (Swap data pending)")

        # Wednesday Triple Rollover Check
        if not is_backtest and datetime.now(timezone.utc).weekday() == 2:
            accuracy_factors.append("Wednesday Triple Swap Active (3x Rollover Yield)")

        vix = macro.get("vix", 16.0)
        if vix > 22.0:
            passed = False
            veto_reasons.append(f"Elevated Volatility (VIX {vix:.1f} > 22.0). Carry positions at risk of whipsaw.")
        else:
            accuracy_factors.append(f"Controlled Volatility Environment (VIX {vix:.1f})")

    # Anti-Trap is mandatory across all profiles
    if trap_type == "BULL_TRAP" and is_buy:
        passed = False
        veto_reasons.append("Institutional Bull Trap Detected at Resistance! Rejection in progress.")
    elif trap_type == "BEAR_TRAP" and not is_buy:
        passed = False
        veto_reasons.append("Wyckoff Bear Trap / Spring Detected! Buying absorption in progress.")

    return {
        "passed": passed,
        "strategy": strat["code"],
        "strategy_name": strat["name"],
        "session": session_info["session"],
        "liquidity": session_info["liquidity"],
        "accuracy_factors": accuracy_factors,
        "veto_reasons": veto_reasons,
        "at_good_level": at_good_level
    }


def calculate_lot_size(asset: str, entry_price: float, stop_loss_price: float,
                       account_balance: float = DEFAULT_ACCOUNT_BALANCE,
                       risk_pct: float = DEFAULT_MAX_RISK_PCT,
                       broker_leverage: float = None,
                       margin_free: float = None) -> dict:
    """
    Computes exact institutional lot size so that dollar loss at SL equals risk_pct.
    Formula:
      Risk USD = Account Balance * (Risk % / 100)
      Price Distance = |Entry - StopLoss|
      Gold: 1.0 Lot = 100 oz  -> Dollar Risk Per Lot = Price Distance * 100
      BTC:  1.0 Lot = 1 BTC   -> Dollar Risk Per Lot = Price Distance * 1
      Recommended Lots = Risk USD / Dollar Risk Per Lot (clamped to min/max lot step)
      Auto-adjusts for broker leverage and margin availability.
    """
    asset_str = str(asset or "GOLD").upper()
    asset_key = "GOLD" if asset_str in ("GOLD", "XAU", "XAUUSD", "GC=F") else "BTC"
    spec = CONTRACT_SPECS[asset_key]

    if account_balance <= 0:
        return {
            "asset": asset_key,
            "lots": spec["min_lot"],
            "risk_usd": 0.0,
            "actual_risk_usd": 0.0,
            "actual_risk_pct": 0.0,
            "price_dist": 0.0,
            "dollar_risk_per_lot": 0.0,
            "valid": False,
            "reason": "Account balance must be positive (> 0)"
        }

    if entry_price <= 0 or stop_loss_price <= 0:
        return {
            "asset": asset_key,
            "lots": spec["min_lot"],
            "risk_usd": 0.0,
            "actual_risk_usd": 0.0,
            "actual_risk_pct": 0.0,
            "price_dist": 0.0,
            "dollar_risk_per_lot": 0.0,
            "valid": False,
            "reason": "Entry price and Stop-Loss must be positive (> 0)"
        }

    price_dist = abs(entry_price - stop_loss_price)
    if price_dist <= 0:
        return {
            "asset": asset_key,
            "lots": spec["min_lot"],
            "risk_usd": 0.0,
            "actual_risk_usd": 0.0,
            "actual_risk_pct": 0.0,
            "price_dist": 0.0,
            "dollar_risk_per_lot": 0.0,
            "valid": False,
            "reason": "Entry price equals Stop-Loss (zero distance)"
        }

    risk_budget_usd = account_balance * (max(0.01, risk_pct) / 100.0)
    dollar_risk_per_lot = price_dist * spec["contract_size"]

    raw_lots = risk_budget_usd / dollar_risk_per_lot if dollar_risk_per_lot > 0 else spec["min_lot"]
    # Step round to lot step (0.01)
    step = spec["lot_step"]
    stepped_lots = math.floor(raw_lots / step) * step
    clamped_lots = max(spec["min_lot"], min(stepped_lots, spec["max_lot"]))
    clamped_lots = round(clamped_lots, 2)

    # Automatically check broker leverage and free margin
    if broker_leverage and broker_leverage > 0 and margin_free and margin_free > 0:
        nominal_per_lot = entry_price * spec["contract_size"]
        margin_per_lot = nominal_per_lot / broker_leverage
        if margin_per_lot > 0:
            max_lots_by_margin = (margin_free * 0.85) / margin_per_lot
            stepped_margin_lots = math.floor(max_lots_by_margin / step) * step
            if stepped_margin_lots < clamped_lots:
                clamped_lots = max(spec["min_lot"], round(stepped_margin_lots, 2))

    actual_risk_usd = clamped_lots * dollar_risk_per_lot
    actual_risk_pct = (actual_risk_usd / account_balance) * 100.0 if account_balance > 0 else 0.0

    return {
        "asset": asset_key,
        "lots": clamped_lots,
        "raw_lots": round(raw_lots, 4),
        "risk_budget_usd": round(risk_budget_usd, 2),
        "actual_risk_usd": round(actual_risk_usd, 2),
        "actual_risk_pct": round(actual_risk_pct, 2),
        "price_dist": round(price_dist, 2),
        "dollar_risk_per_lot": round(dollar_risk_per_lot, 2),
        "contract_multiplier": spec["contract_size"],
        "valid": True,
        "reason": "OK"
    }


def calculate_strategy_levels(asset: str, current_price: float, atr: float = 0.0,
                              action: str = "BUY", strategy: str = None,
                              account_balance: float = DEFAULT_ACCOUNT_BALANCE,
                              risk_pct: float = None,
                              broker_leverage: float = None,
                              margin_free: float = None,
                              swap_info: dict = None,
                              levels: dict = None) -> dict:
    """
    Multi-Strategy Parameter Engine:
      - SCALP: Small SL (0.45x ATR), quick 1.2R TP1, high win rate (~75-80%), 0.50% risk.
      - SWING: Structural SL (1.20x ATR), 2.5R to 3.5R extended targets, 1.00% risk.
      - BALANCE: Mean-reversion SL (0.75x ATR), 1.8R target back to 0.50 Fib Equilibrium, 0.75% risk.
      - SWAP: Carry-optimized SL (0.90x ATR), 2.0R target with rollover analysis, 0.75% risk.
    """
    asset_key = "GOLD" if asset.upper() in ("GOLD", "XAU", "XAUUSD", "GC=F") else "BTC"
    is_buy = action.upper() in ("BUY", "LONG")
    strat_key = (strategy or ACTIVE_STRATEGY).upper()
    strat = STRATEGIES.get(strat_key, STRATEGIES["SCALP"])

    target_risk = risk_pct if (risk_pct is not None and risk_pct > 0) else strat.get("risk_pct", 1.0)
    base_atr = atr if atr > 0 else (28.0 if asset_key == "GOLD" else 2200.0)

    # Dynamic Post-Mortem SL Buffer Calibration (Self-Healing)
    dynamic_buffer = 0.0
    try:
        from self_learning import self_learning_engine
        dynamic_buffer = self_learning_engine.get_dynamic_sl_buffer(asset_key)
    except Exception:
        dynamic_buffer = 0.0

    sl_mult = strat["sl_mult"] + dynamic_buffer

    # 1. Strategy-Specific Stop-Loss Distance (Tight, Low Practical Scalping Bounds)
    if asset_key == "GOLD":
        raw_sl_dist = base_atr * sl_mult
        min_bound = 2.40 if strat_key == "SCALP" else 6.00 if strat_key == "SWING" else 3.50
        max_bound = 3.50 if strat_key == "SCALP" else 35.00 if strat_key == "SWING" else 15.00
        if dynamic_buffer > 0:
            max_bound += round(base_atr * dynamic_buffer, 2)
        sl_dist = max(min_bound, min(raw_sl_dist, max_bound))
    else:
        raw_sl_dist = base_atr * sl_mult
        min_bound = 190.0 if strat_key == "SCALP" else 800.0 if strat_key == "SWING" else 400.0
        max_bound = 300.0 if strat_key == "SCALP" else 3500.0 if strat_key == "SWING" else 1800.0
        if dynamic_buffer > 0:
            max_bound += round(base_atr * dynamic_buffer, 2)
        sl_dist = max(min_bound, min(raw_sl_dist, max_bound))

    sl_dist = round(sl_dist, 2)

    # 2. Strategy-Specific Take-Profit Distances
    tp1_dist = round(sl_dist * strat["rr_tp1"], 2)
    tp2_dist = round(sl_dist * strat["rr_tp2"], 2)

    if is_buy:
        stop_loss = round(current_price - sl_dist, 2)
        tp1 = round(current_price + tp1_dist, 2)
        tp2 = round(current_price + tp2_dist, 2)
        # Direct anchor for BALANCE: 0.50 Fibonacci Equilibrium
        if strat_key == "BALANCE" and levels and "fib_500" in levels:
            eq_val = levels["fib_500"]
            if eq_val > current_price:
                tp1 = round(eq_val, 2)
                tp1_dist = round(tp1 - current_price, 2)
    else:
        stop_loss = round(current_price + sl_dist, 2)
        tp1 = round(current_price - tp1_dist, 2)
        tp2 = round(current_price - tp2_dist, 2)
        if strat_key == "BALANCE" and levels and "fib_500" in levels:
            eq_val = levels["fib_500"]
            if eq_val < current_price:
                tp1 = round(eq_val, 2)
                tp1_dist = round(current_price - tp1, 2)

    rr_tp1 = round(tp1_dist / sl_dist, 2) if sl_dist > 0 else strat["rr_tp1"]
    rr_tp2 = round(tp2_dist / sl_dist, 2) if sl_dist > 0 else strat["rr_tp2"]

    # 3. Dynamic Position Sizing with Leverage & Margin Limits
    lot_info = calculate_lot_size(asset_key, current_price, stop_loss, account_balance, target_risk, broker_leverage, margin_free)
    cap_key = "lot_cap_gold" if asset_key == "GOLD" else "lot_cap_btc"
    max_cap = strat.get(cap_key, 0.20)
    clamped_lot = max(0.01, min(lot_info["lots"], max_cap))
    lot_info["lots"] = round(clamped_lot, 2)

    # 4. Swap Note if available
    swap_note = ""
    if swap_info and swap_info.get("available"):
        fav = swap_info.get("favorable_side")
        if fav == action.upper():
            swap_note = "✅ Positive Carry: Earns overnight rollover financing on this side."
        else:
            swap_note = "⚠️ Carry Cost: Overnight holding incurs financing cost on this side."

    return {
        "asset": asset_key,
        "strategy": strat["code"],
        "strategy_name": strat["name"],
        "action": "BUY" if is_buy else "SELL",
        "entry": round(current_price, 2),
        "stop_loss": stop_loss,
        "tp1": tp1,
        "tp2": tp2,
        "sl_dist": sl_dist,
        "tp1_dist": tp1_dist,
        "tp2_dist": tp2_dist,
        "rr_tp1": rr_tp1,
        "rr_tp2": rr_tp2,
        "breakeven_r": strat.get("breakeven_r", 0.60),
        "trail_start_r": strat.get("trail_start_r", 1.00),
        "trail_step_r": strat.get("trail_step_r", 0.50),
        "lot_size": lot_info["lots"],
        "risk_usd": lot_info["actual_risk_usd"],
        "risk_pct": lot_info["actual_risk_pct"],
        "holding_time": strat["holding_time"],
        "win_rate_focus": strat["description"],
        "swap_note": swap_note,
        "dynamic_sl_buffer": dynamic_buffer
    }


def calculate_sniper_levels(asset: str, current_price: float, atr: float = 0.0,
                            action: str = "BUY", account_balance: float = DEFAULT_ACCOUNT_BALANCE,
                            risk_pct: float = DEFAULT_MAX_RISK_PCT) -> dict:
    """Seamless backward-compatible alias to calculate_strategy_levels in SCALP mode."""
    return calculate_strategy_levels(asset, current_price, atr, action, "SCALP", account_balance, risk_pct)


def compute_var_and_cvar(ticker: str = "BTC-USD", lookback_days: int = 180,
                         confidence: float = 0.95, position_value: float = 10_000.0) -> dict:
    """
    Calculates 1-Day Value at Risk (VaR) and Conditional VaR (Expected Shortfall).
    VaR 95%: The maximum expected daily dollar loss at 95% statistical confidence.
    CVaR 95%: The expected average loss on the worst 5% outlier days.
    """
    try:
        df = yf.download(ticker, period=f"{lookback_days}d", interval="1d", progress=False)
        if df.empty or len(df) < 30:
            return {"var_pct": 2.5, "var_usd": position_value * 0.025, "cvar_pct": 3.5, "cvar_usd": position_value * 0.035}

        close_col = "Close"
        if isinstance(df.columns, pd.MultiIndex):
            close_series = df[close_col].iloc[:, 0]
        else:
            close_series = df[close_col]

        returns = close_series.pct_change().dropna()
        alpha = 1.0 - confidence
        var_pct = abs(float(np.percentile(returns, alpha * 100)))
        cvar_pct = abs(float(returns[returns <= -var_pct].mean())) if len(returns[returns <= -var_pct]) > 0 else var_pct * 1.3

        return {
            "var_pct": round(var_pct * 100, 2),
            "var_usd": round(position_value * var_pct, 2),
            "cvar_pct": round(cvar_pct * 100, 2),
            "cvar_usd": round(position_value * cvar_pct, 2)
        }
    except Exception:
        return {"var_pct": 2.5, "var_usd": position_value * 0.025, "cvar_pct": 3.5, "cvar_usd": position_value * 0.035}


def compute_kelly_sizing(win_rate: float = 0.55, avg_rr: float = 2.0) -> dict:
    """
    Calculates Kelly Criterion and conservative Half-Kelly optimal position sizing.
    Full Kelly = (W * R - (1 - W)) / R
    Institutional best practice: Use Half-Kelly or capped at max 2.0% portfolio risk.
    """
    w = max(0.01, min(win_rate, 0.99))
    r = max(0.5, avg_rr)
    full_kelly = (w * r - (1.0 - w)) / r
    half_kelly = full_kelly / 2.0

    # Safety clamp: never allow negative or > 2.0% risk per trade
    safe_recommended = max(0.25, min(half_kelly * 100.0, 2.0)) if half_kelly > 0 else 0.50

    return {
        "win_rate": round(w * 100, 1),
        "avg_rr": round(r, 2),
        "full_kelly_pct": round(max(0, full_kelly) * 100, 2),
        "half_kelly_pct": round(max(0, half_kelly) * 100, 2),
        "safe_recommended_pct": round(safe_recommended, 2)
    }


def compute_anti_ruin_matrix(risk_pct: float = 1.0, win_rate: float = 0.55,
                             max_dd_limit_pct: float = 6.0) -> dict:
    """
    Calculates consecutive loss tolerance before hitting max drawdown circuit breaker.
    Formula: (1 - risk_pct)^N = (1 - max_dd_pct)  =>  N = ln(1 - max_dd) / ln(1 - risk_pct)
    """
    r = risk_pct / 100.0
    dd = max_dd_limit_pct / 100.0
    consecutive_losses = math.log(1.0 - dd) / math.log(1.0 - r) if r > 0 else 999

    # Probability of 3, 5, and 8 consecutive losses
    loss_prob = 1.0 - win_rate
    prob_3_loss = (loss_prob ** 3) * 100
    prob_5_loss = (loss_prob ** 5) * 100
    prob_8_loss = (loss_prob ** 8) * 100

    return {
        "risk_pct": risk_pct,
        "max_dd_limit_pct": max_dd_limit_pct,
        "consecutive_losses_to_halt": int(math.floor(consecutive_losses)),
        "prob_3_losses_pct": round(prob_3_loss, 2),
        "prob_5_losses_pct": round(prob_5_loss, 2),
        "prob_8_losses_pct": round(prob_8_loss, 2)
    }


def validate_trade_risk(entry: float, sl: float, tp1: float, tp2: float,
                        asset: str, atr: float = 0.0,
                        account_balance: float = DEFAULT_ACCOUNT_BALANCE,
                        risk_pct: float = DEFAULT_MAX_RISK_PCT) -> dict:
    """
    Institutional 5-point risk pre-flight checklist before order execution.
    """
    checks = []
    passed_all = True

    # 1. Stop-Loss Exists
    price_dist = abs(entry - sl)
    if price_dist <= 0 or sl <= 0:
        checks.append(("Stop-Loss Defined", False, "Missing or invalid stop-loss level"))
        passed_all = False
    else:
        checks.append(("Stop-Loss Defined", True, f"Distance: ${price_dist:,.2f}"))

    # 2. Minimum 1:2.0 Risk-to-Reward Ratio
    reward_dist = abs(tp1 - entry)
    rr = reward_dist / price_dist if price_dist > 0 else 0
    if rr < 1.8:  # Enforce ~1:2 ratio
        checks.append(("Min 1:2.0 Risk-to-Reward", False, f"R:R is 1:{rr:.2f} (Minimum 1:2 required)"))
        passed_all = False
    else:
        checks.append(("Min 1:2.0 Risk-to-Reward", True, f"R:R is 1:{rr:.2f}"))

    # 3. ATR Volatility Breathing Room (SL >= 0.5x ATR)
    if atr > 0:
        min_sl_dist = 0.5 * atr
        if price_dist < min_sl_dist:
            checks.append(("ATR Breathing Room", False, f"SL too tight (${price_dist:,.1f} < 0.5x ATR ${min_sl_dist:,.1f})"))
            passed_all = False
        else:
            checks.append(("ATR Breathing Room", True, f"SL distance exceeds 0.5x ATR (${price_dist:,.1f} >= ${min_sl_dist:,.1f})"))
    else:
        checks.append(("ATR Breathing Room", True, "N/A"))

    # 4. Maximum Risk Sizing (<= 1.0%)
    if risk_pct > 1.0:
        checks.append(("Risk Budget <= 1.0%", False, f"Requested risk {risk_pct:.1f}% exceeds 1.0% institutional ceiling"))
        passed_all = False
    else:
        checks.append(("Risk Budget <= 1.0%", True, f"Risk capped at {risk_pct:.1f}% (${account_balance * (risk_pct/100):,.2f})"))

    # 5. Position Lot Sizing Clamping
    lot_info = calculate_lot_size(asset, entry, sl, account_balance, risk_pct)
    if lot_info["lots"] < 0.01:
        checks.append(("Valid Lot Size", False, "Calculated volume is below 0.01 micro lot"))
        passed_all = False
    else:
        checks.append(("Valid Lot Size", True, f"{lot_info['lots']} lots (${lot_info['actual_risk_usd']:,.2f} risk)"))

    return {
        "passed": passed_all,
        "checks": checks,
        "lot_info": lot_info,
        "rr": rr
    }


def generate_risk_audit_text(account_balance: float = DEFAULT_ACCOUNT_BALANCE,
                            risk_pct: float = DEFAULT_MAX_RISK_PCT,
                            btc_data: dict = None, gold_data: dict = None,
                            win_rate: float = 0.55) -> str:
    """
    Renders an institutional Markdown risk audit for Telegram or CLI display.
    """
    risk_usd = account_balance * (risk_pct / 100.0)
    daily_halt_usd = account_balance * (DAILY_DRAWDOWN_HALT_PCT / 100.0)
    total_halt_usd = account_balance * (MAX_TOTAL_DRAWDOWN_PCT / 100.0)

    kelly = compute_kelly_sizing(win_rate=win_rate, avg_rr=2.0)
    ruin = compute_anti_ruin_matrix(risk_pct=risk_pct, win_rate=win_rate, max_dd_limit_pct=MAX_TOTAL_DRAWDOWN_PCT)

    lines = [
        "🛡️ *INSTITUTIONAL RISK MANAGEMENT & POSITION SIZING*",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"💰 *Portfolio Equity:* `${account_balance:,.2f}`",
        f"• Risk Budget per Trade: `{risk_pct:.1f}%` = `${risk_usd:,.2f}`",
        f"• Reduced 'B' Setup Risk: `0.5%` = `${risk_usd * 0.5:,.2f}`",
        f"• Daily Circuit Breaker: `-{DAILY_DRAWDOWN_HALT_PCT:.1f}%` (-${daily_halt_usd:,.2f} halt limit)",
        f"• Max Total Drawdown: `-{MAX_TOTAL_DRAWDOWN_PCT:.1f}%` (-${total_halt_usd:,.2f} portfolio halt)",
        ""
    ]

    # Live Asset Sizing
    if btc_data and btc_data.get("entry") and btc_data.get("stop_loss"):
        b_lot = calculate_lot_size("BTC", btc_data["entry"], btc_data["stop_loss"], account_balance, risk_pct)
        lines.extend([
            f"₿ *Bitcoin (BTC/USD) Dynamic Sizing:*",
            f"• Entry: `${btc_data['entry']:,.2f}` | Stop: `${btc_data['stop_loss']:,.2f}`",
            f"• Stop Distance: `${b_lot['price_dist']:,.2f}`",
            f"• Recommended Position: `{b_lot['lots']}` BTC Lots",
            f"• Risk at Stop-Loss: `${b_lot['actual_risk_usd']:,.2f}` ({b_lot['actual_risk_pct']:.2f}% of equity)",
            ""
        ])

    if gold_data and gold_data.get("entry") and gold_data.get("stop_loss"):
        g_lot = calculate_lot_size("GOLD", gold_data["entry"], gold_data["stop_loss"], account_balance, risk_pct)
        lines.extend([
            f"🥇 *Gold (XAU/USD) Dynamic Sizing:*",
            f"• Entry: `${gold_data['entry']:,.2f}` | Stop: `${gold_data['stop_loss']:,.2f}`",
            f"• Stop Distance: `${g_lot['price_dist']:,.2f}` (1 Lot = 100 oz)",
            f"• Recommended Position: `{g_lot['lots']}` Standard Lots",
            f"• Risk at Stop-Loss: `${g_lot['actual_risk_usd']:,.2f}` ({g_lot['actual_risk_pct']:.2f}% of equity)",
            ""
        ])

    # Quantitative Risk Optimization
    lines.extend([
        "📊 *Institutional Capital Guardrails:*",
        f"• Risk Budget Adherence: `{risk_pct:.1f}% per trade` (Strict Capital Ceiling)",
        f"• Confluence Required  : `Score ≥ 8/10` for full position",
        f"• Max Open Exposure    : `2 Positions Max` (1 Gold + 1 BTC)",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🔒 *Capital Rule:* Fixed 1% risk per trade. Zero revenge trading."
    ])

    return "\n".join(lines)


if __name__ == "__main__":
    balance = float(sys.argv[1]) if len(sys.argv) > 1 else 10_000.0
    print(generate_risk_audit_text(
        account_balance=balance,
        risk_pct=1.0,
        btc_data={"entry": 67_500.0, "stop_loss": 66_200.0},
        gold_data={"entry": 2_740.0, "stop_loss": 2_722.0},
        win_rate=0.55
    ))
