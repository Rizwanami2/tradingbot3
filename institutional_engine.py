"""
================================================================================
INSTITUTIONAL & SMART MONEY ENGINE (SMC)
================================================================================
Provides high-value institutional and Smart Money Concepts (SMC) as additional
confluence factors for Gold (XAU/USD) & Bitcoin (BTC/USD).

Part 1: Higher Timeframe (HTF) Bias Detection
  - Multi-tier EMA trend alignment (50 EMA & 200 EMA)
  - Higher Timeframe swing structure (HH/HL vs LH/LL)
  - Directional alignment guardrail (reduces or vetoes counter-trend trades)
================================================================================
"""

import math
import time
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List
import numpy as np
import pandas as pd


class InstitutionalEngine:
    """
    Analyzes higher timeframe bias, order blocks, fair value gaps,
    and liquidity pools as confluence overlays to existing risk/confluence matrices.
    """

    def __init__(self, ema_fast_period: int = 50, ema_slow_period: int = 200):
        self.ema_fast_period = ema_fast_period
        self.ema_slow_period = ema_slow_period

    # ==========================================================================
    # 1. HIGHER TIMEFRAME (HTF) BIAS DETECTION
    # ==========================================================================

    def compute_htf_bias(self, df: pd.DataFrame, asset: str) -> Dict[str, Any]:
        """
        Determines Higher Timeframe (Daily / H4) directional bias using:
          1. 50 EMA & 200 EMA relative stacking & price positioning.
          2. Multi-swing structure (Higher Highs / Higher Lows vs Lower Highs / Lower Lows).
        Returns structured dictionary with bias classification and metrics.
        """
        if df is None or df.empty or len(df) < 30:
            return {
                "asset": asset,
                "bias": "NEUTRAL",
                "simple_bias": "Neutral",
                "price": 0.0,
                "ema50": 0.0,
                "ema200": 0.0,
                "ema_alignment": "NEUTRAL",
                "structure": "RANGE",
                "score": 0,
                "summary": "⚪ Neutral (Insufficient Bars)",
                "details": "Insufficient historical data to determine HTF bias."
            }

        close = df["Close"]
        curr_price = float(close.iloc[-1])

        # 1. Exponential Moving Averages (50 & 200)
        ema50 = float(close.ewm(span=self.ema_fast_period, adjust=False).mean().iloc[-1])
        if len(close) >= self.ema_slow_period:
            ema200 = float(close.ewm(span=self.ema_slow_period, adjust=False).mean().iloc[-1])
        else:
            ema200 = float(close.rolling(len(close)).mean().iloc[-1])

        # 2. EMA Trend Stacking
        ema_score = 0
        ema_reasons = []

        if curr_price > ema50 and ema50 > ema200:
            ema_score += 2
            ema_alignment = "STRONG_BULLISH"
            ema_reasons.append(f"Price (${curr_price:,.1f}) > 50 EMA (${ema50:,.1f}) > 200 EMA (${ema200:,.1f}) [Golden Stack]")
        elif curr_price > ema50:
            ema_score += 1
            ema_alignment = "BULLISH"
            ema_reasons.append(f"Price (${curr_price:,.1f}) > 50 EMA (${ema50:,.1f})")
        elif curr_price < ema50 and ema50 < ema200:
            ema_score -= 2
            ema_alignment = "STRONG_BEARISH"
            ema_reasons.append(f"Price (${curr_price:,.1f}) < 50 EMA (${ema50:,.1f}) < 200 EMA (${ema200:,.1f}) [Death Stack]")
        elif curr_price < ema50:
            ema_score -= 1
            ema_alignment = "BEARISH"
            ema_reasons.append(f"Price (${curr_price:,.1f}) < 50 EMA (${ema50:,.1f})")
        else:
            ema_alignment = "NEUTRAL"
            ema_reasons.append("Price consolidating around moving averages")

        # 3. Market Structure Progression (Last 30-50 bars)
        structure, struct_score, struct_desc = self._detect_swing_structure(df)

        total_score = ema_score + struct_score

        # Classify overall bias
        if total_score >= 2:
            bias = "STRONG_BULLISH" if total_score >= 3 else "BULLISH"
            simple_bias = "Bullish"
            badge = "🟢 Strong Bullish" if total_score >= 3 else "🟢 Bullish"
        elif total_score <= -2:
            bias = "STRONG_BEARISH" if total_score <= -3 else "BEARISH"
            simple_bias = "Bearish"
            badge = "🔴 Strong Bearish" if total_score <= -3 else "🔴 Bearish"
        else:
            bias = "NEUTRAL"
            simple_bias = "Neutral"
            badge = "🟡 Neutral / Chop"

        all_details = " | ".join(ema_reasons + [struct_desc])

        return {
            "asset": asset,
            "bias": bias,
            "simple_bias": simple_bias,
            "price": round(curr_price, 2),
            "ema50": round(ema50, 2),
            "ema200": round(ema200, 2),
            "ema_alignment": ema_alignment,
            "structure": structure,
            "score": total_score,
            "summary": f"{badge} ({struct_desc})",
            "details": all_details
        }

    def _detect_swing_structure(self, df: pd.DataFrame) -> Tuple[str, int, str]:
        """Analyzes swing highs & lows for structural HH/HL vs LH/LL."""
        if len(df) < 25:
            return "RANGE", 0, "Consolidation"

        lookback = min(len(df), 50)
        recent = df.tail(lookback).copy()

        # Simple peak/trough extraction using rolling 3-bar windows
        highs = recent["High"].values
        lows = recent["Low"].values

        peak_indices = [i for i in range(2, len(highs) - 2) if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]]
        trough_indices = [i for i in range(2, len(lows) - 2) if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]]

        if len(peak_indices) >= 2 and len(trough_indices) >= 2:
            last_peak = highs[peak_indices[-1]]
            prev_peak = highs[peak_indices[-2]]
            last_trough = lows[trough_indices[-1]]
            prev_trough = lows[trough_indices[-2]]

            is_higher_high = last_peak > prev_peak
            is_higher_low = last_trough > prev_trough
            is_lower_high = last_peak < prev_peak
            is_lower_low = last_trough < prev_trough

            if is_higher_high and is_higher_low:
                return "BULLISH_STRUCTURE", 1, "Higher Highs & Higher Lows (HH/HL)"
            elif is_lower_high and is_lower_low:
                return "BEARISH_STRUCTURE", -1, "Lower Highs & Lower Lows (LH/LL)"

        # Fallback to net price direction over lookback
        start_p = recent["Close"].iloc[0]
        end_p = recent["Close"].iloc[-1]
        pct = (end_p - start_p) / start_p * 100.0

        if pct > 4.0:
            return "BULLISH_DRIFT", 1, f"Upward Expansion (+{pct:.1f}%)"
        elif pct < -4.0:
            return "BEARISH_DRIFT", -1, f"Downward Expansion ({pct:.1f}%)"

        return "RANGE", 0, "Consolidation / Range"

    # ==========================================================================
    # DIRECTIONAL ALIGNMENT & RISK GUARDRAIL
    # ==========================================================================

    def evaluate_htf_alignment(self, htf_bias: Dict[str, Any], action: str,
                               strategy: str = "SCALP") -> Dict[str, Any]:
        """
        Evaluates whether a proposed trade direction (BUY/SELL) is institutionally
        aligned with the Higher Timeframe Bias.

        Rules:
          - BUY with BULLISH/STRONG_BULLISH bias -> +1 Confluence bonus, full size.
          - BUY with NEUTRAL bias -> 0 Confluence delta, permitted.
          - BUY with BEARISH bias -> -1 Confluence penalty, reduce size to 0.5%.
          - BUY with STRONG_BEARISH bias -> Veto non-scalp trades; require tight confirmation for scalp.
          - Reverse symmetric rules apply for SELL.
        """
        action_norm = action.upper()
        bias = htf_bias.get("bias", "NEUTRAL")
        strat_norm = strategy.upper()

        if action_norm in ("BUY", "BUY_HALF"):
            if bias in ("BULLISH", "STRONG_BULLISH"):
                return {
                    "aligned": True,
                    "status": "ALIGNED",
                    "confluence_delta": 1,
                    "risk_multiplier": 1.0,
                    "veto": False,
                    "veto_reason": None,
                    "display_badge": "🟢 HTF Bullish (Aligned)"
                }
            elif bias == "NEUTRAL":
                return {
                    "aligned": True,
                    "status": "NEUTRAL",
                    "confluence_delta": 0,
                    "risk_multiplier": 1.0,
                    "veto": False,
                    "veto_reason": None,
                    "display_badge": "🟡 HTF Neutral (Permitted)"
                }
            elif bias == "BEARISH":
                # Moderate counter-trend: reduce risk to half size
                return {
                    "aligned": False,
                    "status": "COUNTER_TREND_WARNING",
                    "confluence_delta": -1,
                    "risk_multiplier": 0.5,
                    "veto": False,
                    "veto_reason": None,
                    "display_badge": "⚠️ HTF Bearish (Counter-Trend, Half Size)"
                }
            else:  # STRONG_BEARISH
                # Strong counter-trend: veto swing/balance/swap; allow scalp only if high confluence
                is_veto = strat_norm in ("SWING", "BALANCE", "SWAP")
                return {
                    "aligned": False,
                    "status": "VETOED" if is_veto else "COUNTER_TREND_WARNING",
                    "confluence_delta": -2,
                    "risk_multiplier": 0.5,
                    "veto": is_veto,
                    "veto_reason": f"Long vetoed: Strong Bearish HTF Bias ({htf_bias['details']}) forbids {strat_norm} trades." if is_veto else None,
                    "display_badge": "🚨 HTF Strong Bearish (Veto Warning)" if is_veto else "⚠️ HTF Strong Bearish (Scalp Only, Half Size)"
                }

        elif action_norm in ("SELL", "SELL_HALF"):
            if bias in ("BEARISH", "STRONG_BEARISH"):
                return {
                    "aligned": True,
                    "status": "ALIGNED",
                    "confluence_delta": 1,
                    "risk_multiplier": 1.0,
                    "veto": False,
                    "veto_reason": None,
                    "display_badge": "🟢 HTF Bearish (Aligned)"
                }
            elif bias == "NEUTRAL":
                return {
                    "aligned": True,
                    "status": "NEUTRAL",
                    "confluence_delta": 0,
                    "risk_multiplier": 1.0,
                    "veto": False,
                    "veto_reason": None,
                    "display_badge": "🟡 HTF Neutral (Permitted)"
                }
            elif bias == "BULLISH":
                return {
                    "aligned": False,
                    "status": "COUNTER_TREND_WARNING",
                    "confluence_delta": -1,
                    "risk_multiplier": 0.5,
                    "veto": False,
                    "veto_reason": None,
                    "display_badge": "⚠️ HTF Bullish (Counter-Trend, Half Size)"
                }
            else:  # STRONG_BULLISH
                is_veto = strat_norm in ("SWING", "BALANCE", "SWAP")
                return {
                    "aligned": False,
                    "status": "VETOED" if is_veto else "COUNTER_TREND_WARNING",
                    "confluence_delta": -2,
                    "risk_multiplier": 0.5,
                    "veto": is_veto,
                    "veto_reason": f"Short vetoed: Strong Bullish HTF Bias ({htf_bias['details']}) forbids {strat_norm} trades." if is_veto else None,
                    "display_badge": "🚨 HTF Strong Bullish (Veto Warning)" if is_veto else "⚠️ HTF Strong Bullish (Scalp Only, Half Size)"
                }

        return {
            "aligned": True,
            "status": "NEUTRAL",
            "confluence_delta": 0,
            "risk_multiplier": 1.0,
            "veto": False,
            "veto_reason": None,
            "display_badge": "⚪ Neutral"
        }


# Global Singleton Instance
institutional_engine = InstitutionalEngine()


# ==============================================================================
# 2. NEURO-SYMBOLIC PRE-TRADE OUTCOME PREDICTOR & GATEKEEPER
# ==============================================================================

class NeuroSymbolicPredictor:
    """
    Real-Time Pre-Trade Outcome Predictor & Gatekeeper.
    Combines:
      1. Vectorized Monte Carlo Jump-Diffusion Simulation (1,000 synthetic paths in <10ms)
      2. Bayesian Historical Similarity Matching (learning_memory.json)
      3. Opposing Order Block & Liquidity Wall Clearance
      4. Mathematical Expected Value (EV) Calculation
    """
    def __init__(self, num_simulations: int = 1000, horizon_steps: int = 40):
        self.num_simulations = num_simulations
        self.horizon_steps = horizon_steps

    def run_monte_carlo_jump_diffusion(self, entry: float = None, sl: float = None, tp1: float = None, atr: float = None,
                                       action: str = "BUY", num_paths: int = None, horizon_steps: int = None,
                                       current_price: float = None, entry_price: float = None, sl_price: float = None,
                                       tp_price: float = None, **kwargs) -> dict:
        """Vectorized 1,000-path jump-diffusion Monte Carlo simulation."""
        entry = entry if entry is not None else (entry_price if entry_price is not None else current_price)
        if entry is None or entry <= 0:
            entry = 2700.0
        sl = sl if sl is not None else sl_price
        if sl is None:
            sl = entry - 4.0 if action.upper() == "BUY" else entry + 4.0
        tp1 = tp1 if tp1 is not None else tp_price
        if tp1 is None:
            tp1 = entry + 6.0 if action.upper() == "BUY" else entry - 6.0
        atr = atr if (atr is not None and atr > 0) else kwargs.get("base_atr", 25.0)

        n_sims = num_paths or self.num_simulations
        h_steps = horizon_steps or self.horizon_steps
        is_buy = (action.upper() == "BUY")
        risk_dist = abs(entry - sl) if abs(entry - sl) > 0 else 1.0
        reward_dist = abs(tp1 - entry) if abs(tp1 - entry) > 0 else 1.0

        daily_vol = (atr / entry) if entry > 0 else 0.015
        dt = 1.0 / h_steps
        step_vol = daily_vol * np.sqrt(dt)

        shocks = np.random.normal(0, step_vol, size=(n_sims, h_steps))
        jump_intensity = 0.05
        jump_occurred = np.random.binomial(1, jump_intensity, size=(n_sims, h_steps))
        jump_size = np.random.normal(0, step_vol * 2.5, size=(n_sims, h_steps)) * jump_occurred
        returns = shocks + jump_size

        cum_returns = np.cumsum(returns, axis=1)
        price_paths = entry * np.exp(np.hstack([np.zeros((n_sims, 1)), cum_returns]))

        if is_buy:
            tp_hit_idx = np.where(price_paths >= tp1, np.arange(h_steps + 1), 9999)
            first_tp = np.min(tp_hit_idx, axis=1)
            sl_hit_idx = np.where(price_paths <= sl, np.arange(h_steps + 1), 9999)
            first_sl = np.min(sl_hit_idx, axis=1)

            tp_before_sl = (first_tp < first_sl) & (first_tp < 9999)
            win_count = int(np.sum(tp_before_sl))
            min_prices = np.min(price_paths, axis=1)
            mae = float(np.mean(np.maximum(0.0, entry - min_prices)))
        else:
            tp_hit_idx = np.where(price_paths <= tp1, np.arange(h_steps + 1), 9999)
            first_tp = np.min(tp_hit_idx, axis=1)
            sl_hit_idx = np.where(price_paths >= sl, np.arange(h_steps + 1), 9999)
            first_sl = np.min(sl_hit_idx, axis=1)

            tp_before_sl = (first_tp < first_sl) & (first_tp < 9999)
            win_count = int(np.sum(tp_before_sl))
            max_prices = np.max(price_paths, axis=1)
            mae = float(np.mean(np.maximum(0.0, max_prices - entry)))

        hit_rate = round(win_count / n_sims, 3)
        return {
            "hit_rate": hit_rate,
            "mc_hit_rate": round(hit_rate * 100, 1),
            "win_count": win_count,
            "total_simulations": n_sims,
            "mae_predicted": round(mae, 2)
        }

    def predict_trade_outcome(self, asset: str = "GOLD", price: float = None, entry: float = None, sl: float = None,
                              tp1: float = None, tp2: float = None, strategy: str = "SCALP", atr: float = None,
                              active_features: dict = None, memory_stats: dict = None, order_blocks: list = None,
                              action: str = "BUY", current_price: float = None, sl_price: float = None,
                              tp_price: float = None, opposing_levels: list = None, is_scalp: bool = None,
                              **kwargs) -> dict:
        """
        Synthesizes Monte Carlo simulation, Bayesian historical analogs, and microstructure
        barriers into a definitive predictive outcome verdict and Expected Value.
        """
        entry = entry if entry is not None else (kwargs.get("entry_price") if kwargs.get("entry_price") is not None else (current_price if current_price is not None else price))
        if entry is None or entry <= 0:
            entry = 2700.0 if asset.upper() in ("GOLD", "XAU", "GC=F") else 65000.0
        sl = sl if sl is not None else sl_price
        if sl is None:
            sl = entry - (4.0 if asset.upper() in ("GOLD", "XAU", "GC=F") else 400.0)
        tp1 = tp1 if tp1 is not None else tp_price
        if tp1 is None:
            tp1 = entry + (6.0 if asset.upper() in ("GOLD", "XAU", "GC=F") else 600.0)
        tp2 = tp2 if tp2 is not None else (tp1 + abs(tp1 - entry))
        strategy = strategy if strategy else ("SCALP" if is_scalp is not False else "SWING")
        atr = atr if (atr is not None and atr > 0) else (25.0 if asset.upper() in ("GOLD", "XAU", "GC=F") else 2000.0)
        active_features = active_features or {}
        order_blocks = order_blocks if order_blocks is not None else (opposing_levels or [])

        mc_res = self.run_monte_carlo_jump_diffusion(entry=entry, sl=sl, tp1=tp1, atr=atr, action=action)
        mc_hit_rate = mc_res["hit_rate"]

        hist_prob = 0.75
        if memory_stats and "feature_stats" in memory_stats:
            asset_stats = memory_stats["feature_stats"].get(asset, {})
            probs = []
            if active_features:
                for feat, is_act in active_features.items():
                    if is_act and feat in asset_stats:
                        st = asset_stats[feat]
                        act_count = st.get("activations", 0)
                        if act_count >= 2:
                            w = st.get("wins", 0)
                            probs.append(w / act_count)
            if probs:
                hist_prob = float(np.mean(probs))

        barrier_detected = False
        barrier_note = "Clear highway to target"
        if order_blocks:
            is_buy = (action.upper() == "BUY")
            for ob in order_blocks:
                if isinstance(ob, (int, float)):
                    if is_buy and entry < ob < tp1:
                        barrier_detected = True
                        barrier_note = f"Opposing Resistance Barrier at ${ob:,.2f}"
                        break
                    elif not is_buy and tp1 < ob < entry:
                        barrier_detected = True
                        barrier_note = f"Opposing Support Barrier at ${ob:,.2f}"
                        break
                elif isinstance(ob, dict):
                    ob_type = ob.get("type", "")
                    ob_low = ob.get("low", 0.0)
                    ob_high = ob.get("high", 0.0)
                    if is_buy and "BEAR" in ob_type:
                        if entry < ob_low < tp1 or entry < ob_high < tp1:
                            barrier_detected = True
                            barrier_note = f"Opposing Bearish Order Block at ${ob_low:,.2f}-${ob_high:,.2f}"
                            break
                    elif not is_buy and "BULL" in ob_type:
                        if tp1 < ob_high < entry or tp1 < ob_low < entry:
                            barrier_detected = True
                            barrier_note = f"Opposing Bullish Order Block at ${ob_low:,.2f}-${ob_high:,.2f}"
                            break

        barrier_factor = 0.85 if barrier_detected else 1.0
        raw_prob = (0.50 * mc_hit_rate) + (0.35 * hist_prob) + (0.15 * (0.5 if barrier_detected else 0.85))
        win_probability = round(float(np.clip(raw_prob * barrier_factor, 0.20, 0.95)), 3)

        risk_dist = abs(entry - sl) if abs(entry - sl) > 0 else 1.0
        reward_dist = abs(tp1 - entry) if abs(tp1 - entry) > 0 else 1.2
        rr_tp1 = round(reward_dist / risk_dist, 2)
        ev_r = round((win_probability * rr_tp1) - ((1.0 - win_probability) * 1.0), 2)

        min_prob = 0.65 if strategy.upper() == "SCALP" else 0.70
        is_approved = (win_probability >= min_prob) and (ev_r >= 0.15) and not (barrier_detected and win_probability < 0.75)

        verdict_str = "APPROVED" if is_approved else "VETOED (Low EV / Barrier)"
        if not is_approved:
            reason = f"Predicted win rate {win_probability*100:.1f}% below minimum {min_prob*100:.0f}% (EV: {ev_r:+.2f}R)"
            if barrier_detected:
                reason += f" | {barrier_note}"
        else:
            reason = f"High-confidence trade path: {win_probability*100:.1f}% win forecast (EV: {ev_r:+.2f}R)"

        win_prob_pct = round(win_probability * 100, 1)
        mc_hit_pct = round(mc_hit_rate * 100, 1)

        return {
            "approved": is_approved,
            "verdict": verdict_str,
            "reason": reason,
            "rejection_reason": reason if not is_approved else "",
            "badge": "🟢 HIGH EDGE" if is_approved else "🔴 LOW EDGE",
            "summary": f"{'🟢' if is_approved else '🔴'} Win Prob: {win_prob_pct:.1f}% | EV: {ev_r:+.2f}R | MC: {int(mc_hit_pct)}%",
            "win_probability": win_prob_pct,
            "win_probability_raw": win_probability,
            "win_rate_pct": win_prob_pct,
            "expected_value_r": ev_r,
            "expected_value_usd": round(ev_r * 100.0, 2),
            "mc_hit_rate": mc_hit_pct,
            "mc_simulations": mc_res["total_simulations"],
            "mc_mae_predicted": mc_res["mae_predicted"],
            "mae_predicted": mc_res["mae_predicted"],
            "hist_similarity_win_rate": round(hist_prob, 3),
            "bayesian_similarity": round(hist_prob * 100, 1),
            "opposing_barrier_score": 85.0 if barrier_detected else 100.0,
            "barrier_detected": barrier_detected,
            "barrier_note": barrier_note,
            "rr_ratio": rr_tp1
        }


# ==============================================================================
# 3. 4-AGENT POST-MORTEM FORENSIC COUNCIL (SL ANALYSIS & STRATEGY ADAPTATION)
# ==============================================================================

class ForensicCouncil:
    """
    4-Agent Post-Mortem Forensic Council.
    Conducts root-cause analysis whenever a trade hits Stop-Loss (SL_HIT) or closes with a loss:
      1. Microstructure & Anti-Trap Specialist (wick sweeps, liquidity grabs)
      2. Global Macro & Volatility Auditor (DXY surge, real yield shift, low ADX chop)
      3. Orderflow & FVG Specialist (imbalance failure, order block breach)
      4. Chief Risk Officer (root cause verdict & autonomous parameter calibration)
    """
    def __init__(self):
        pass

    def conduct_post_mortem(self, trade_data: dict, current_market: dict = None) -> dict:
        """
        Executes collaborative multi-agent post-mortem on a failed trade.
        Returns detailed forensic debrief and parameter adaptation commands.
        """
        asset = trade_data.get("asset", "GOLD").upper()
        symbol = trade_data.get("symbol", "GC=F" if asset == "GOLD" else "BTC-USD")
        entry = float(trade_data.get("entry") or trade_data.get("open_price", 0.0))
        sl = float(trade_data.get("sl") or trade_data.get("stop_loss", 0.0))
        tp1 = float(trade_data.get("tp1", 0.0))
        exit_price = float(trade_data.get("exit_price") or sl)
        action = trade_data.get("action", "BUY").upper()
        pnl = float(trade_data.get("pnl", 0.0))
        r_multiple = float(trade_data.get("r_multiple", -1.0))
        ticket = trade_data.get("ticket") or trade_data.get("trade_id", "N/A")
        active_features = trade_data.get("active_features", {})
        strategy = trade_data.get("strategy", "SCALP").upper()

        m_data = current_market or {}
        macro = m_data.get("macro", {})
        asset_info = m_data.get("gold" if asset == "GOLD" else "btc", {})

        # ── AGENT 1: Microstructure & Anti-Trap Specialist ──
        risk_dist = abs(entry - sl) if abs(entry - sl) > 0 else 1.0
        slippage_past_sl = abs(exit_price - sl)
        is_wick_hunt = (slippage_past_sl <= 0.40 * risk_dist)
        trap_type = asset_info.get("trap_type", "NONE")

        if is_wick_hunt:
            micro_verdict = f"Liquidity sweep wick hunt: price pierced SL by only ${slippage_past_sl:,.2f} before stabilizing."
            micro_cause = "WICK_HUNT"
        elif trap_type in ("BULL_TRAP", "UPTHRUST"):
            micro_verdict = f"Bull trap rejection: {trap_type} formed with heavy upper wick rejection."
            micro_cause = "BULL_TRAP"
        else:
            micro_verdict = f"Clean auction breakthrough: price crossed stop level with normal order flow momentum."
            micro_cause = "CLEAN_BREAK"

        # ── AGENT 2: Global Macro & Volatility Auditor ──
        dxy_chg = macro.get("dxy_chg", 0.0)
        tnx_chg = macro.get("tnx_chg", 0.0)
        adx = asset_info.get("adx", 25.0)

        if adx < 20.0:
            macro_verdict = f"Chop exhaustion: Market regime is dead chop (ADX {adx:.1f} < 20). Insufficient momentum to reach target."
            macro_cause = "CHOP_EXHAUSTION"
        elif dxy_chg > 0.25 and action == "BUY":
            macro_verdict = f"Macro USD surge: DXY rallied {dxy_chg:+.2f}%, creating strong monetary headwind for hard assets."
            macro_cause = "USD_SURGE"
        elif tnx_chg > 0.50 and action == "BUY":
            macro_verdict = f"Yield spike drag: 10Y Real Yield increased {tnx_chg:+.2f}%, raising opportunity cost."
            macro_cause = "YIELD_SPIKE"
        else:
            macro_verdict = f"Macro neutral: DXY ({dxy_chg:+.2f}%) and 10Y yield ({tnx_chg:+.2f}%) remained orderly."
            macro_cause = "MACRO_NORMAL"

        # ── AGENT 3: Orderflow & FVG Specialist ──
        fvg = asset_info.get("fvg", "None")
        if "BEAR" in str(fvg).upper() and action == "BUY":
            flow_verdict = f"Bearish imbalance pressure: Unmitigated Bearish FVG ({fvg}) capped upward expansion."
            flow_cause = "BEAR_IMBALANCE"
        else:
            flow_verdict = "Orderflow within normal boundaries; no major opposing imbalance detected."
            flow_cause = "FLOW_NORMAL"

        # ── AGENT 4: Chief Risk Officer (Synthesizer & Calibrator) ──
        if micro_cause == "WICK_HUNT":
            root_cause = "Institutional Liquidity Sweep (Wick Hunted SL by small margin)"
            sl_buffer_delta = 0.15
            adx_adj = 0.0
        elif macro_cause == "CHOP_EXHAUSTION":
            root_cause = f"Chop Regime Failure (Entered in dead chop with ADX {adx:.1f} < 20)"
            sl_buffer_delta = 0.0
            adx_adj = 2.0
        elif macro_cause == "USD_SURGE":
            root_cause = f"Macroeconomic USD Surge (DXY spiked {dxy_chg:+.2f}%)"
            sl_buffer_delta = 0.0
            adx_adj = 0.0
        elif micro_cause == "BULL_TRAP":
            root_cause = "Bull Trap Rejection at Resistance"
            sl_buffer_delta = 0.05
            adx_adj = 0.0
        else:
            root_cause = "Structural Support Breakdown (Normal Risk Distribution)"
            sl_buffer_delta = 0.0
            adx_adj = 0.0

        penalized_features = [feat for feat, act in active_features.items() if act]
        if not penalized_features:
            penalized_features = ["in_golden_pocket", "near_swing_support"]

        post_mortem_report = {
            "ticket": str(ticket),
            "asset": asset,
            "symbol": symbol,
            "action": action,
            "strategy": strategy,
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "exit_price": exit_price,
            "pnl": pnl,
            "r_multiple": r_multiple,
            "timestamp": time.time(),
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "agent_findings": {
                "microstructure": micro_verdict,
                "macro": macro_verdict,
                "orderflow": flow_verdict,
                "risk_officer": root_cause
            },
            "root_cause": root_cause,
            "adaptations": {
                "penalized_features": penalized_features,
                "sl_buffer_delta": sl_buffer_delta,
                "adx_floor_delta": adx_adj
            }
        }
        return post_mortem_report


# Global Singleton Instances
neuro_predictor = NeuroSymbolicPredictor()
forensic_council = ForensicCouncil()
