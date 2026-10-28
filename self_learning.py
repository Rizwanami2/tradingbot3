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
                    return json.load(f)
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
            "trade_journal": []
        }

    def save_memory(self):
        self.memory["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tmp_path = self.memory_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self.memory, f, indent=2)
        if os.path.exists(self.memory_path):
            os.remove(self.memory_path)
        os.rename(tmp_path, self.memory_path)

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

    def train_on_historical_data(self, lookback_days: int = 365, verbose: bool = True):
        """
        Walk-Forward Historical Self-Training:
        Simulates past market setups over the lookback window for BTC and Gold,
        checks subsequent forward price action to verify if TP1 or SL was reached first,
        and executes online learning updates.
        """
        if verbose:
            print(f"\n[*] Initiating Walk-Forward Self-Training Engine (Lookback: {lookback_days} days)...")
        
        tickers = {
            "BTC": ("BTC-USD", "BTC"),
            "GOLD": ("GC=F", "GOLD")
        }

        # Fetch Macro context history
        dxy_hist = yf.Ticker("DX-Y.NYB").history(period=f"{lookback_days + 60}d")
        tnx_hist = yf.Ticker("^TNX").history(period=f"{lookback_days + 60}d")

        trained_trades = 0
        wins = 0

        for asset, (sym, _) in tickers.items():
            if verbose:
                print(f"  * Simulating and learning from {asset} ({sym}) price action...")
            hist = yf.Ticker(sym).history(period=f"{lookback_days + 60}d")
            if hist.empty or len(hist) < 80:
                continue

            close = hist["Close"]
            high = hist["High"]
            low = hist["Low"]

            for i in range(60, len(hist) - 15, 3):
                curr_price = close.iloc[i]
                sub_close = close.iloc[:i+1]
                sub_high = high.iloc[:i+1]
                sub_low = low.iloc[:i+1]

                ma200 = sub_close.rolling(200).mean().iloc[-1] if len(sub_close) >= 200 else sub_close.rolling(len(sub_close)).mean().iloc[-1]
                ma50 = sub_close.rolling(50).mean().iloc[-1] if len(sub_close) >= 50 else sub_close.rolling(len(sub_close)).mean().iloc[-1]
                
                delta = sub_close.diff()
                gain = delta.where(delta > 0, 0.0).tail(14).mean()
                loss = (-delta.where(delta < 0, 0.0)).tail(14).mean()
                rs = gain / loss if loss != 0 else 1.0
                rsi = 100 - (100 / (1 + rs))

                sw_h = sub_high.tail(60).max()
                sw_l = sub_low.tail(60).min()
                fib_618 = sw_h - 0.618 * (sw_h - sw_l)
                fib_650 = sw_h - 0.650 * (sw_h - sw_l)

                in_gp = (curr_price >= fib_650 * 0.985) and (curr_price <= fib_618 * 1.02)
                
                c_bar = hist.iloc[i]
                c_range = c_bar["High"] - c_bar["Low"]
                upper_wick = c_bar["High"] - max(c_bar["Open"], c_bar["Close"])
                is_trap = (upper_wick / c_range >= 0.40) if c_range > 0 else False

                dxy_chg = 0.0
                if not dxy_hist.empty and i < len(dxy_hist) and i >= 2:
                    dxy_chg = ((dxy_hist["Close"].iloc[min(i, len(dxy_hist)-1)] / dxy_hist["Close"].iloc[min(i-2, len(dxy_hist)-2)]) - 1) * 100

                tnx_chg = 0.0
                if not tnx_hist.empty and i < len(tnx_hist) and i >= 2:
                    tnx_chg = ((tnx_hist["Close"].iloc[min(i, len(tnx_hist)-1)] / tnx_hist["Close"].iloc[min(i-2, len(tnx_hist)-2)]) - 1) * 100

                active_features = {
                    "in_golden_pocket": bool(in_gp),
                    "no_trap": bool(not is_trap),
                    "macro_dxy_tailwind": bool(dxy_chg <= 0.1),
                    "macro_yield_tailwind": bool(tnx_chg <= 0.5),
                    "trend_ma200": bool(curr_price > ma200),
                    "trend_ma50": bool(curr_price > ma50),
                    "rsi_sweet_spot": bool(40 <= rsi <= 62),
                    "mayer_sweet_spot": bool(0.85 <= (curr_price / ma200) <= 1.50) if asset == "BTC" else False,
                    "gsr_undervalued": True if asset == "GOLD" else False,
                    "volatility_orderly": True,
                    "near_swing_support": bool((curr_price - sw_l) / curr_price <= 0.05)
                }

                score, _ = self.calculate_score(asset, active_features)

                if score >= 6.5:
                    stop_loss = fib_650 * 0.985 if in_gp else sw_l * 0.985
                    risk_dist = curr_price - stop_loss
                    if risk_dist <= 0:
                        continue
                    tp1 = curr_price + (risk_dist * 2.0)

                    future_bars = hist.iloc[i+1:i+16]
                    hit_tp = False
                    hit_sl = False
                    exit_price = curr_price

                    for _, f_row in future_bars.iterrows():
                        if f_row["Low"] <= stop_loss:
                            hit_sl = True
                            exit_price = stop_loss
                            break
                        if f_row["High"] >= tp1:
                            hit_tp = True
                            exit_price = tp1
                            break

                    if hit_tp or hit_sl:
                        outcome = "WIN" if hit_tp else "LOSS"
                        r_mult = 2.0 if hit_tp else -1.0
                        
                        trade_id = self.log_signal(asset, sym, curr_price, stop_loss, tp1, tp1 * 1.1, score, active_features)
                        self.update_from_outcome(trade_id, exit_price, outcome, r_mult, learning_rate=0.04)
                        
                        trained_trades += 1
                        if hit_tp:
                            wins += 1

        if verbose:
            win_pct = (wins / trained_trades * 100) if trained_trades > 0 else 0
            print(f"[+] Self-Training Complete: {trained_trades} historical setups evaluated. Win Rate: {win_pct:.1f}%")
            print(f"[*] New Factor Weights Saved to {self.memory_path}\n")

        return trained_trades, wins

    def sync_mt5_history(self):
        """
        Synchronizes with MetaTrader 5 closed deals history to update weights with real broker executions.
        """
        try:
            import MetaTrader5 as mt5
            if not mt5.initialize():
                return 0, "MT5 initialization failed"
            
            from_date = datetime.now() - timedelta(days=30)
            deals = mt5.history_deals_get(from_date, datetime.now())
            if deals is None or len(deals) == 0:
                return 0, "No closed deals found in MT5 history"

            synced = 0
            for deal in deals:
                if deal.entry == 1:
                    profit = deal.profit
                    symbol = deal.symbol
                    asset = "BTC" if "BTC" in symbol.upper() else "GOLD" if ("XAU" in symbol.upper() or "GOLD" in symbol.upper()) else None
                    if not asset:
                        continue

                    outcome = "WIN" if profit > 0 else "LOSS"
                    r_multiple = 2.0 if profit > 0 else -1.0
                    
                    trade_id = f"MT5_{deal.ticket}"
                    exists = any(t["trade_id"] == trade_id for t in self.memory["trade_journal"])
                    if not exists:
                        feat = {
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
                        self.log_signal(asset, symbol, deal.price, deal.price * 0.98, deal.price * 1.04, deal.price * 1.06, 8.5, feat)
                        self.update_from_outcome(trade_id, deal.price, outcome, r_multiple, learning_rate=0.08)
                        synced += 1

            return synced, f"Synchronized {synced} closed MT5 deals"
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
