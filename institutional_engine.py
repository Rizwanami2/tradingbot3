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
