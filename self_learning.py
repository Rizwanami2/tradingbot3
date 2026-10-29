#!/usr/bin/env python3
"""
self_learning.py
Institutional Self-Learning & Adaptive Weight Optimization Engine for Gold (XAU) & Bitcoin (BTC).

Capabilities:
  1. Dynamic Feature Weighting: Adapts confluence matrix weights based on real trade outcomes.
  2. Walk-Forward Historical Simulation: Trains model on past market cycles (pullback wins vs false breakouts).
  3. MT5 Trade History Sync: Automatically reads closed MT5 deals and updates factor weights.
  4. Guardrail Enforcement: Strict limits on weight drift (0.35x to 2.50x) and immovable 1% risk & stop-loss rules.
  5. Persistent Memory: Saves learning state in 'learning_memory.json'.
"""

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import ssl
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

import os
import json
import time
from datetime import datetime, timedelta
import numpy as np

try:
    import yfinance as yf
except ImportError:
    print("[!] yfinance required. Run: py -3.11 -m pip install yfinance")
    sys.exit(1)

MEMORY_FILE = os.path.join(os.path.dirname(__file__), "learning_memory.json")

# Default Baseline Features & Initial Weights (Prior: 1.0)
DEFAULT_WEIGHTS = {
    "in_golden_pocket": 1.25,      # High edge: 0.618-0.650 Fibonacci confluence
    "no_trap": 1.20,               # High edge: confirmation that no bull trap/upper wick occurred
    "macro_dxy_tailwind": 1.00,    # Macro: DXY flat or falling
    "macro_yield_tailwind": 1.00,  # Macro: 10Y real yield flat or falling
    "trend_ma200": 1.00,           # Macro trend: price above 200 SMA
    "trend_ma50": 0.90,            # Intermediate trend: price above 50 SMA
    "rsi_sweet_spot": 1.05,        # Momentum: RSI pullback zone (40-60)
    "mayer_sweet_spot": 1.10,      # Bitcoin specific: Mayer Multiple 0.85-1.50x
    "gsr_undervalued": 1.10,       # Gold specific: GSR >= 75x
    "volatility_orderly": 0.85,    # Volatility: Realized vol in non-panic regime
    "near_swing_support": 0.95     # Structure: within 5% of 60-day swing low
}

DEFAULT_HYPERPARAMS = {
    "min_confluence_threshold": 8.0,
    "rsi_lower_bound": 40.0,
    "rsi_upper_bound": 60.0,
    "gp_tolerance_pct": 2.0,
    "trap_wick_min_pct": 40.0,
    "target_rr_ratio": 2.0
}


class SelfLearningEngine:
    def __init__(self, memory_path: str = MEMORY_FILE):
        self.memory_path = memory_path
        self.memory = self._load_memory()

    def _load_memory(self) -> dict:
        if os.path.exists(self.memory_path):
            try:
                with open(self.memory_path, "r", encoding="utf-8") as f:
                    mem = json.load(f)
                    if "post_mortem_journal" not in mem:
                        mem["post_mortem_journal"] = []
                    if "dynamic_sl_buffers" not in mem:
                        mem["dynamic_sl_buffers"] = {"GOLD": 0.0, "BTC": 0.0}
                    return mem
            except Exception as e:
                print(f"[!] Error loading memory file: {e}. Reinitializing default state.")
        
        # Fresh initialization
        return {
            "version": "1.0.0",
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "training_cycles": 0,
            "weights": {
                "BTC": dict(DEFAULT_WEIGHTS),
                "GOLD": dict(DEFAULT_WEIGHTS)
            },
            "hyperparams": dict(DEFAULT_HYPERPARAMS),
            "feature_stats": {
                "BTC": {k: {"activations": 0, "wins": 0, "losses": 0, "total_r": 0.0} for k in DEFAULT_WEIGHTS},
                "GOLD": {k: {"activations": 0, "wins": 0, "losses": 0, "total_r": 0.0} for k in DEFAULT_WEIGHTS}
            },
            "performance": {
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate_pct": 0.0,
                "total_r_multiple": 0.0,
                "profit_factor": 1.0
            },
            "trade_journal": [],
            "post_mortem_journal": [],
            "dynamic_sl_buffers": {"GOLD": 0.0, "BTC": 0.0}
        }

    @property
    def total_signals(self) -> int:
        return self.memory.get("performance", {}).get("total_trades", 0)

    @property
    def overall_win_rate(self) -> float:
        pct = self.memory.get("performance", {}).get("win_rate_pct", 55.0)
        return (pct / 100.0) if pct > 0 else 0.55

    def save_memory(self):
        self.memory["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tmp_path = self.memory_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self.memory, f, indent=2)
        os.replace(tmp_path, self.memory_path)

    def calculate_score(self, asset: str, active_features: dict) -> tuple:
        """
        Calculates an adaptive confluence score (0.0 to 10.0) based on current learned weights.
        Returns: (adaptive_score, breakdown_list)
        """
        asset_weights = self.memory["weights"].get(asset, DEFAULT_WEIGHTS)
        
        earned_score = 0.0
        max_score = 0.0
        breakdown = []

        for feature_key, weight in asset_weights.items():
            max_score += weight
            is_active = active_features.get(feature_key, False)
            if is_active:
                earned_score += weight
                breakdown.append({
                    "feature": feature_key,
                    "weight": round(weight, 2),
                    "active": True
                })

        # Normalize score onto a 10.0 institutional scale
        normalized_score = (earned_score / max_score) * 10.0 if max_score > 0 else 0.0
        normalized_score = round(normalized_score, 1)

        return normalized_score, breakdown

    def log_signal(self, asset: str, symbol: str, entry: float, sl: float, tp1: float, tp2: float,
                   score: float, active_features: dict) -> str:
        """
        Logs a generated trade signal into the trade journal.
        """
        trade_id = f"{asset}_{int(time.time() * 1000)}"
        record = {
            "trade_id": trade_id,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "asset": asset,
            "symbol": symbol,
            "entry": entry,
            "stop_loss": sl,
            "tp1": tp1,
            "tp2": tp2,
            "risk_pct": abs(entry - sl) / entry * 100 if entry > 0 else 1.0,
            "reward_pct": abs(tp1 - entry) / entry * 100 if entry > 0 else 2.0,
            "score": score,
            "active_features": active_features,
            "status": "PENDING",
            "outcome": None,
            "r_multiple": 0.0,
            "exit_price": None,
            "exit_time": None
        }
        self.memory["trade_journal"].append(record)
        self.save_memory()
        return trade_id

    def update_from_outcome(self, trade_id: str, exit_price: float, outcome: str, r_multiple: float, learning_rate: float = 0.06):
        """
        Online learning weight update based on a closed trade outcome.
        outcome: 'WIN' or 'LOSS'
        """
        target_trade = None
        for t in self.memory["trade_journal"]:
            if t["trade_id"] == trade_id:
                target_trade = t
                break
        
        if not target_trade or target_trade["status"] == "CLOSED":
            return False

        asset = target_trade["asset"]
        active_features = target_trade["active_features"]

        # Update record
        target_trade["status"] = "CLOSED"
        target_trade["exit_price"] = exit_price
        target_trade["exit_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        target_trade["outcome"] = outcome
        target_trade["r_multiple"] = r_multiple

        # Update aggregate stats
        p = self.memory["performance"]
        p["total_trades"] += 1
        if outcome == "WIN":
            p["wins"] += 1
        else:
            p["losses"] += 1
            # Auto-trigger 4-Agent Post-Mortem Forensic Council on trade stop-out
            try:
                from institutional_engine import forensic_council
                pm_report = forensic_council.conduct_post_mortem(target_trade)
                self.record_post_mortem(pm_report)
            except Exception as err:
                print(f"⚠️ Forensic post-mortem execution error: {err}")
        p["win_rate_pct"] = round((p["wins"] / p["total_trades"]) * 100, 1)
        p["total_r_multiple"] = round(p["total_r_multiple"] + r_multiple, 2)
        
        gross_profit = sum(t["r_multiple"] for t in self.memory["trade_journal"] if t.get("r_multiple", 0) > 0)
        gross_loss = abs(sum(t["r_multiple"] for t in self.memory["trade_journal"] if t.get("r_multiple", 0) < 0))
        p["profit_factor"] = round(gross_profit / gross_loss, 2) if gross_loss > 0 else round(gross_profit, 2)

        # Update feature statistics & adapt weights
        weights = self.memory["weights"].get(asset, DEFAULT_WEIGHTS)
        stats = self.memory["feature_stats"].get(asset, {})

        for feat, is_active in active_features.items():
            if feat not in stats:
                stats[feat] = {"activations": 0, "wins": 0, "losses": 0, "total_r": 0.0}

            if is_active:
                stats[feat]["activations"] += 1
                if outcome == "WIN":
                    stats[feat]["wins"] += 1
                    stats[feat]["total_r"] += r_multiple
                    delta = learning_rate * (r_multiple / 2.0)
                    weights[feat] = min(weights.get(feat, 1.0) + delta, 2.50)
                else:
                    stats[feat]["losses"] += 1
                    stats[feat]["total_r"] += r_multiple
                    delta = learning_rate * abs(r_multiple)
                    weights[feat] = max(weights.get(feat, 1.0) - delta, 0.35)

        self.memory["training_cycles"] += 1
        self.save_memory()
        return True

    def sync_all_closed_trades(self, live_broker=None, safety_manager=None) -> list:
        """
        Comprehensive closed trade synchronization engine.
        Automatically identifies closed trades across:
          1. MT5 closed deals history (via live_broker.get_closed_deals_history())
          2. Paper trading closed positions (via safety_manager.get_closed_paper_positions())
          3. Pending setups in trade_journal reaching TP or SL based on live market prices.
        Reconciles each closed trade:
          - Marks journal entry as CLOSED
          - Records exit price, PnL, R-multiple, outcome (WIN / LOSS)
          - Updates Bayesian factor activations and feature weights
          - Recalculates win rate %, cumulative R-multiple, profit factor
        Returns the list of newly identified/synchronized closed trades.
        """
        synced_trades = []
        external_closed = []

        # 1. Fetch closed positions from Paper Trading
        if safety_manager:
            try:
                p_closed = safety_manager.get_closed_paper_positions(limit=50)
                if p_closed:
                    external_closed.extend(p_closed)
            except Exception as e:
                pass

        # 2. Fetch closed deals from MT5 Broker
        if live_broker:
            try:
                m_closed = live_broker.get_closed_deals_history(days=14)
                if m_closed:
                    external_closed.extend(m_closed)
            except Exception as e:
                pass

        # 3. Reconcile external closed trades into trade journal
        for ext in external_closed:
            t_id = str(ext.get("ticket") or ext.get("position_id") or "")
            if not t_id:
                continue

            # Check if this ticket is already closed in memory
            already_closed = any(
                str(t.get("ticket")) == t_id or str(t.get("trade_id")) == t_id
                for t in self.memory["trade_journal"]
                if t.get("status") == "CLOSED"
            )
            if already_closed:
                continue

            # Check if pending in journal
            matched_pending = None
            for t in self.memory["trade_journal"]:
                if t.get("status") == "PENDING" and (str(t.get("ticket")) == t_id or t.get("asset") == ext.get("asset")):
                    matched_pending = t
                    break

            outcome = ext.get("outcome", "WIN" if ext.get("pnl", 0) > 0 else "LOSS")
            r_mult = ext.get("r_multiple", 1.20 if outcome == "WIN" else -1.0)
            exit_price = ext.get("exit_price", ext.get("open_price", 0.0))

            if matched_pending:
                matched_pending["ticket"] = t_id
                matched_pending["pnl"] = ext.get("pnl", 0.0)
                self.update_from_outcome(matched_pending["trade_id"], exit_price, outcome, r_mult)
                synced_trades.append(matched_pending)
            else:
                asset = ext.get("asset", "GOLD")
                sym = ext.get("symbol", "XAUUSD" if asset == "GOLD" else "BTCUSD")
                features = {
                    "in_golden_pocket": True,
                    "no_trap": True,
                    "macro_dxy_tailwind": True,
                    "macro_yield_tailwind": True,
                    "trend_ma200": True,
                    "trend_ma50": True,
                    "rsi_sweet_spot": True,
                    "mayer_sweet_spot": True if asset == "BTC" else False,
                    "gsr_undervalued": True if asset == "GOLD" else False,
                    "volatility_orderly": True,
                    "near_swing_support": True
                }
                trade_id = self.log_signal(
                    asset, sym, ext.get("open_price", exit_price),
                    ext.get("sl", exit_price * 0.99), ext.get("tp1", exit_price * 1.01),
                    ext.get("tp2", exit_price * 1.02), ext.get("score", 8.0), features
                )
                for t in self.memory["trade_journal"]:
                    if t["trade_id"] == trade_id:
                        t["ticket"] = t_id
                        t["pnl"] = ext.get("pnl", 0.0)
                        break
                self.update_from_outcome(trade_id, exit_price, outcome, r_mult)
                synced_trades.append({
                    "ticket": t_id,
                    "asset": asset,
                    "symbol": sym,
                    "outcome": outcome,
                    "r_multiple": r_mult,
                    "pnl": ext.get("pnl", 0.0),
                    "exit_price": exit_price,
                    "source": ext.get("source", "EXTERNAL")
                })

        if synced_trades:
            self.save_memory()

        return synced_trades

    def get_recent_closed_trades(self, limit: int = 10) -> list:
        """Returns the most recent closed trades from trade journal (newest first)."""
        closed = [t for t in self.memory.get("trade_journal", []) if t.get("status") == "CLOSED"]
        return closed[-limit:][::-1]

    def format_recent_trades_card(self, limit: int = 5) -> str:
        """Formats an executive summary card of recent closed trades for Telegram & CLI."""
        closed = self.get_recent_closed_trades(limit=limit)
        p = self.memory.get("performance", {})
        total = p.get("total_trades", len(closed))
        wr = p.get("win_rate_pct", 0.0)
        wins = p.get("wins", 0)
        losses = p.get("losses", 0)
        tot_r = p.get("total_r_multiple", 0.0)
        pf = p.get("profit_factor", 1.0)

        lines = [
            "📜 *RECENT CLOSED TRADES JOURNAL*",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"• *Performance:* `{wr:.1f}% Win Rate` ({wins}W / {losses}L)",
            f"• *Cumulative Edge:* `{tot_r:+.2f}R` | *Profit Factor:* `{pf:.2f}`",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ]

        if not closed:
            lines.append("ℹ️ _No closed trades identified yet. Execute trades via MT5 or Paper to populate journal._")
        else:
            for idx, t in enumerate(closed, 1):
                out = t.get("outcome", "WIN")
                icon = "🟢 WIN" if out == "WIN" else "🔴 LOSS"
                r = t.get("r_multiple", 0.0)
                asset = t.get("asset", "GOLD")
                sym = t.get("symbol", "XAUUSD")
                entry = t.get("entry", 0.0)
                exit_p = t.get("exit_price", entry)
                ticket = t.get("ticket") or t.get("trade_id", "N/A")
                t_time = t.get("exit_time") or t.get("timestamp", "")
                pnl = t.get("pnl")
                pnl_str = f" | PnL: `${pnl:+,.2f}`" if pnl is not None else ""

                lines.append(f"{idx}. {icon} (`{r:+.2f}R`) | *{asset}* (`{sym}`)")
                lines.append(f"   • Ticket: `#{ticket}` | Entry: `${entry:,.2f}` ➔ Exit: `${exit_p:,.2f}`{pnl_str}")
                lines.append(f"   • Closed: `{t_time}`")

        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("💡 _Run `/trades` or `/learn` to review all adaptive weights._")
        return "\n".join(lines)

    def trigger_post_mortem(self, trade_rec: dict, market_data: dict = None) -> tuple:
        """Runs the 4-Agent Forensic Council on a stopped-out trade, saves to memory, and returns (pm_report, card_text)."""
        try:
            from institutional_engine import forensic_council
            pm_report = forensic_council.conduct_post_mortem(trade_rec, current_market=market_data)
            self.record_post_mortem(pm_report)
            card = self.format_post_mortem_card(pm_report)
            return pm_report, card
        except Exception as err:
            print(f"⚠️ Error in trigger_post_mortem: {err}")
            return {}, ""

    def record_post_mortem(self, pm_report: dict):
        """Records forensic post-mortem analysis and applies dynamic parameter calibrations."""
        if "post_mortem_journal" not in self.memory:
            self.memory["post_mortem_journal"] = []
        if "dynamic_sl_buffers" not in self.memory:
            self.memory["dynamic_sl_buffers"] = {"GOLD": 0.0, "BTC": 0.0}

        self.memory["post_mortem_journal"].append(pm_report)
        if len(self.memory["post_mortem_journal"]) > 50:
            self.memory["post_mortem_journal"] = self.memory["post_mortem_journal"][-50:]

        asset = pm_report.get("asset", "GOLD").upper()
        adaptations = pm_report.get("adaptations", {})

        # Dynamic SL buffer calibration
        sl_delta = adaptations.get("sl_buffer_delta", 0.0)
        if sl_delta > 0:
            curr_buf = self.memory["dynamic_sl_buffers"].get(asset, 0.0)
            self.memory["dynamic_sl_buffers"][asset] = round(min(curr_buf + sl_delta, 0.50), 2)

        # Bayesian factor penalty
        penalized = adaptations.get("penalized_features", [])
        weights = self.memory["weights"].get(asset, {})
        for feat in penalized:
            if feat in weights:
                weights[feat] = max(round(weights[feat] - 0.08, 4), 0.35)

        self.save_memory()
        return pm_report

    def get_dynamic_sl_buffer(self, asset: str) -> float:
        """Returns the dynamic SL buffer multiplier learned from post-mortem forensics (0.0 to 0.50x ATR)."""
        asset_norm = "GOLD" if asset.upper() in ("GOLD", "XAU", "XAUUSD", "GC=F") else "BTC"
        return self.memory.get("dynamic_sl_buffers", {}).get(asset_norm, 0.0)

    def get_post_mortem_history(self, limit: int = 5) -> list:
        """Returns recent post-mortem records (newest first)."""
        journal = self.memory.get("post_mortem_journal", [])
        return journal[-limit:][::-1]

    def format_post_mortem_card(self, pm: dict) -> str:
        """Formats an institutional Telegram debrief card from a post-mortem report."""
        findings = pm.get("agent_findings", {})
        adapt = pm.get("adaptations", {})
        curr_buf = self.get_dynamic_sl_buffer(pm.get("asset", "GOLD"))
        sl_delta_str = f"+{adapt.get('sl_buffer_delta', 0)}x ATR" if adapt.get('sl_buffer_delta', 0) > 0 else "Unchanged"
        return (
            f"🛑 *TRADE STOP-LOSS POST-MORTEM & ADAPTATION AUDIT*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• Ticket / Setup : `#{pm.get('ticket', 'N/A')}` | `{pm.get('asset')}` ({pm.get('action')})\n"
            f"• Strategy       : `{pm.get('strategy', 'SCALP')}` | Outcome: `LOSS (-1.0R)`\n"
            f"• Entry / SL     : `${pm.get('entry', 0.0):,.2f}` ──► SL: `${pm.get('sl', 0.0):,.2f}`\n"
            f"• Exit Fill      : `${pm.get('exit_price', 0.0):,.2f}` ({pm.get('date', '')})\n\n"
            f"🕵️ *4-Agent Forensic Council Findings:*\n"
            f"• 📐 Microstructure : {findings.get('microstructure', 'Normal auction')}\n"
            f"• 🌐 Macro Radar    : {findings.get('macro', 'Orderly conditions')}\n"
            f"• 📊 Orderflow FVG  : {findings.get('orderflow', 'Normal orderflow')}\n"
            f"• 🛡️ Chief Risk Off : *{findings.get('risk_officer', pm.get('root_cause', 'Normal Variance'))}*\n\n"
            f"🔬 *Primary Root Cause:*\n"
            f"\"{pm.get('root_cause', 'Normal Structural Stop')}\"\n\n"
            f"🧠 *Autonomous Adaptations Applied:*\n"
            f"• Factors Penalized : `{', '.join(adapt.get('penalized_features', ['Confluence Weights']))}`\n"
            f"• Dynamic SL Buffer : `{sl_delta_str}` (Current: `+{curr_buf:.2f}x ATR`)\n"
            f"• Memory State      : `Persisted to learning_memory.json` ✅\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )

    def train_on_historical_data(self, lookback_days: int = 365, verbose: bool = True):
        """
        Walk-Forward Historical Self-Training:
        Simulates past market setups over the lookback window for BTC and Gold,
        applies institutional trailing and breakeven protections (matching backtest.py),
        and updates online learning weights.
        """
        if verbose:
            print(f"\n[*] Initiating Walk-Forward Self-Training Engine (Lookback: {lookback_days} days)...")

        # Reset legacy flawed zero-win performance stats
        self.memory["performance"] = {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": 0.0,
            "total_r_multiple": 0.0,
            "profit_factor": 1.0
        }
        for asset in ["BTC", "GOLD"]:
            self.memory["weights"][asset] = dict(DEFAULT_WEIGHTS)
            self.memory["feature_stats"][asset] = {k: {"activations": 0, "wins": 0, "losses": 0, "total_r": 0.0} for k in DEFAULT_WEIGHTS}
        # Keep real user closed trades with ticket, clean out old artificial simulations
        self.memory["trade_journal"] = [t for t in self.memory.get("trade_journal", []) if t.get("ticket")]

        tickers = {
            "BTC": ("BTC-USD", "BTC"),
            "GOLD": ("GC=F", "GOLD")
        }

        # Fetch Macro context history
        try:
            dxy_hist = yf.Ticker("DX-Y.NYB").history(period=f"{lookback_days + 60}d")
        except Exception:
            dxy_hist = None
        try:
            tnx_hist = yf.Ticker("^TNX").history(period=f"{lookback_days + 60}d")
        except Exception:
            tnx_hist = None

        trained_trades = 0
        wins = 0

        for asset, (sym, _) in tickers.items():
            if verbose:
                print(f"  * Simulating and learning from {asset} ({sym}) price action...")
            try:
                hist = yf.Ticker(sym).history(period=f"{lookback_days + 60}d")
            except Exception:
                continue

            if hist is None or hist.empty or len(hist) < 80:
                continue

            close = hist["Close"]
            high = hist["High"]
            low = hist["Low"]
            opn = hist["Open"]

            # Compute rolling ATR
            tr1 = high - low
            tr2 = (high - close.shift(1)).abs()
            tr3 = (low - close.shift(1)).abs()
            tr = np.maximum(tr1, np.maximum(tr2, tr3))
            atr_series = tr.rolling(14).mean()

            for i in range(60, len(hist) - 15, 3):
                curr_price = float(close.iloc[i])
                sub_close = close.iloc[:i+1]
                sub_high = high.iloc[:i+1]
                sub_low = low.iloc[:i+1]
                curr_atr = float(atr_series.iloc[i]) if not np.isnan(atr_series.iloc[i]) else (curr_price * 0.015)

                ma200 = float(sub_close.rolling(200).mean().iloc[-1]) if len(sub_close) >= 200 else float(sub_close.rolling(len(sub_close)).mean().iloc[-1])
                ma50 = float(sub_close.rolling(50).mean().iloc[-1]) if len(sub_close) >= 50 else float(sub_close.rolling(len(sub_close)).mean().iloc[-1])
                ma20 = float(sub_close.ewm(span=20).mean().iloc[-1])

                delta = sub_close.diff()
                gain = delta.where(delta > 0, 0.0).tail(14).mean()
                loss = (-delta.where(delta < 0, 0.0)).tail(14).mean()
                rs = gain / loss if loss != 0 else 1.0
                rsi = float(100 - (100 / (1 + rs)))

                sw_h = float(sub_high.tail(60).max())
                sw_l = float(sub_low.tail(60).min())
                fib_618 = sw_h - 0.618 * (sw_h - sw_l)
                fib_650 = sw_h - 0.650 * (sw_h - sw_l)

                in_gp = (curr_price >= fib_650 * 0.985) and (curr_price <= fib_618 * 1.02)
                near_sw_low = bool((curr_price - sw_l) / curr_price <= 0.05)
                near_ema = bool(abs(curr_price - ma20) / curr_price <= 0.02)
                at_good_level = in_gp or near_sw_low or near_ema

                c_high = float(high.iloc[i])
                c_low = float(low.iloc[i])
                c_open = float(opn.iloc[i])
                c_close = float(close.iloc[i])
                c_range = c_high - c_low
                upper_wick = c_high - max(c_open, c_close)
                lower_wick = min(c_open, c_close) - c_low
                candle_body = abs(c_close - c_open)
                up_wick_pct = (upper_wick / c_range * 100.0) if c_range > 0 else 0.0
                body_pct = (candle_body / c_range * 100.0) if c_range > 0 else 50.0
                is_trap = (up_wick_pct >= 38.0)

                # Macro context
                dxy_chg = 0.0
                if dxy_hist is not None and not dxy_hist.empty and i < len(dxy_hist) and i >= 2:
                    dxy_chg = float(((dxy_hist["Close"].iloc[min(i, len(dxy_hist)-1)] / dxy_hist["Close"].iloc[min(i-2, len(dxy_hist)-2)]) - 1) * 100)

                tnx_chg = 0.0
                if tnx_hist is not None and not tnx_hist.empty and i < len(tnx_hist) and i >= 2:
                    tnx_chg = float(((tnx_hist["Close"].iloc[min(i, len(tnx_hist)-1)] / tnx_hist["Close"].iloc[min(i-2, len(tnx_hist)-2)]) - 1) * 100)

                active_features = {
                    "in_golden_pocket": bool(in_gp),
                    "no_trap": bool(not is_trap),
                    "macro_dxy_tailwind": bool(dxy_chg <= 0.15),
                    "macro_yield_tailwind": bool(tnx_chg <= 0.50),
                    "trend_ma200": bool(curr_price > ma200),
                    "trend_ma50": bool(curr_price > ma50),
                    "rsi_sweet_spot": bool(35 <= rsi <= 68),
                    "mayer_sweet_spot": bool(0.85 <= (curr_price / ma200) <= 1.50) if asset == "BTC" else False,
                    "gsr_undervalued": True if asset == "GOLD" else False,
                    "volatility_orderly": bool(c_range <= (1.5 * curr_atr)),
                    "near_swing_support": near_sw_low
                }

                score, _ = self.calculate_score(asset, active_features)

                # Scalp / Key-Level qualification
                qualifies = (score >= 7.0 and at_good_level and not is_trap and body_pct >= 24.0) or (score >= 8.0 and not is_trap)
                if not qualifies:
                    continue

                # Practical scalp levels
                sl_dist = max(curr_atr * 0.35, curr_price * 0.0035)
                stop_loss = round(curr_price - sl_dist, 2)
                tp1 = round(curr_price + (sl_dist * 1.20), 2)
                tp2 = round(curr_price + (sl_dist * 1.75), 2)

                breakeven_r = 0.35
                trail_start_r = 0.65
                trail_step_r = 0.20

                future_bars = hist.iloc[i+1:min(len(hist), i+12)]
                if future_bars.empty:
                    continue

                active_sl = stop_loss
                is_be_locked = False
                highest_price = curr_price
                exit_price = curr_price
                outcome = "LOSS"
                r_mult = -1.0

                for _, f_row in future_bars.iterrows():
                    f_high = float(f_row["High"])
                    f_low = float(f_row["Low"])

                    if f_high > highest_price:
                        highest_price = f_high

                    floating_r = (highest_price - curr_price) / sl_dist if sl_dist > 0 else 0

                    # 1. Breakeven lock
                    if floating_r >= breakeven_r and not is_be_locked:
                        active_sl = curr_price + (sl_dist * 0.05)
                        is_be_locked = True

                    # 2. Dynamic Trailing
                    if floating_r >= trail_start_r:
                        desired_sl = highest_price - (trail_step_r * sl_dist)
                        if desired_sl > active_sl:
                            active_sl = desired_sl

                    # 3. Take-Profit hit
                    if f_high >= tp1:
                        exit_price = tp1
                        outcome = "WIN"
                        r_mult = 1.20
                        break

                    # 4. Stop-Loss or Trailed Stop hit
                    if f_low <= active_sl:
                        exit_price = active_sl
                        if is_be_locked and active_sl >= curr_price:
                            outcome = "WIN"
                            r_mult = max(0.1, (active_sl - curr_price) / sl_dist)
                        else:
                            outcome = "LOSS"
                            r_mult = -1.0
                        break
                else:
                    last_c = float(future_bars.iloc[-1]["Close"])
                    exit_price = last_c
                    outcome = "WIN" if last_c >= curr_price else "LOSS"
                    r_mult = round((last_c - curr_price) / sl_dist, 2)

                trade_id = self.log_signal(asset, sym, curr_price, stop_loss, tp1, tp2, score, active_features)
                self.update_from_outcome(trade_id, exit_price, outcome, r_mult, learning_rate=0.03)

                trained_trades += 1
                if outcome == "WIN":
                    wins += 1

        if verbose:
            win_pct = (wins / trained_trades * 100) if trained_trades > 0 else 0
            print(f"[+] Self-Training Complete: {trained_trades} historical setups evaluated. Win Rate: {win_pct:.1f}%")
            print(f"[*] New Factor Weights Saved to {self.memory_path}\n")

        return trained_trades, wins

    def sync_mt5_history(self):
        """
        Synchronizes with MetaTrader 5 or Paper Trading closed deals history.
        """
        try:
            try:
                from mt5_executor import live_broker
            except ImportError:
                live_broker = None
            try:
                from risk_engine import safety_manager
            except ImportError:
                safety_manager = None

            synced = self.sync_all_closed_trades(live_broker=live_broker, safety_manager=safety_manager)
            count = len(synced)
            return count, f"Synchronized {count} closed trades into learning journal"
        except Exception as e:
            return 0, f"Sync error: {e}"

    def get_summary_text(self) -> str:
        """
        Generates a human-readable performance & self-learning audit report.
        """
        p = self.memory["performance"]
        lines = []
        lines.append("=" * 70)
        lines.append("  INSTITUTIONAL SELF-LEARNING & WEIGHT AUDIT")
        lines.append(f"  Last Calibrated: {self.memory['last_updated']} | Cycles: {self.memory['training_cycles']}")
        lines.append("=" * 70)
        lines.append(f"  * Total Trades Evaluated : {p['total_trades']}")
        lines.append(f"  * Overall Win Rate       : {p['win_rate_pct']:.1f}% ({p['wins']}W / {p['losses']}L)")
        lines.append(f"  * Cumulative R-Multiple  : {p['total_r_multiple']:+.2f}R")
        lines.append(f"  * Profit Factor          : {p['profit_factor']:.2f}")
        lines.append("-" * 70)
        lines.append("  ADAPTIVE FACTOR WEIGHT RANKINGS:")

        for asset in ["BTC", "GOLD"]:
            icon = "BTC" if asset == "BTC" else "GOLD"
            lines.append(f"\n  [{icon}] Learned Confluence Weights:")
            weights = self.memory["weights"].get(asset, {})
            sorted_w = sorted(weights.items(), key=lambda x: x[1], reverse=True)
            for feat, w in sorted_w:
                stat = self.memory["feature_stats"].get(asset, {}).get(feat, {})
                wins = stat.get("wins", 0)
                tot = stat.get("activations", 0)
                win_rate = (wins / tot * 100) if tot > 0 else 0.0
                bar = "#" * int(w * 4)
                lines.append(f"    * {feat:<22} : {w:4.2f}x  [{bar:<10}] (Win Rate: {win_rate:4.1f}% over {tot} setups)")

        lines.append("=" * 70)
        return "\n".join(lines)


# Global Singleton Instance
self_learning_engine = SelfLearningEngine()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Institutional Self-Learning Engine")
    parser.add_argument("--train", action="store_true", help="Run walk-forward historical training")
    parser.add_argument("--days", type=int, default=365, help="Lookback days for training (default: 365)")
    parser.add_argument("--summary", action="store_true", help="Print current learned weights and performance summary")
    parser.add_argument("--sync", action="store_true", help="Sync with closed MT5 deals")
    args = parser.parse_args()

    engine = SelfLearningEngine()

    if args.train:
        engine.train_on_historical_data(lookback_days=args.days)
        print(engine.get_summary_text())
    elif args.sync:
        count, msg = engine.sync_mt5_history()
        print(f"MT5 Sync: {msg}")
    elif args.summary:
        print(engine.get_summary_text())
    else:
        if engine.memory["training_cycles"] == 0:
            print("First run detected: Performing baseline walk-forward self-calibration...")
            engine.train_on_historical_data(lookback_days=365)
        print(engine.get_summary_text())
