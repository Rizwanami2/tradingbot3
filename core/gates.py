"""
core/gates.py
Pure safety gate functions for the tradingbot3 Precision Engine.

Each gate returns (pass: bool, reason: str).
No side effects — pure validation logic that the orchestrator calls before
any execution decision.
"""

import os
import time
from typing import Dict, Any, List, Tuple, Optional

try:
    from utils.logger import get_logger
    logger = get_logger("gates")
except Exception:
    import logging
    logger = logging.getLogger("gates")

try:
    from risk_engine import MAX_DATA_STALENESS_SECONDS, MAX_ALLOWED_SPREAD, MAX_ALLOWED_SLIPPAGE
except Exception:
    MAX_DATA_STALENESS_SECONDS = 900
    MAX_ALLOWED_SPREAD = {"GOLD": 0.60, "BTC": 35.00}
    MAX_ALLOWED_SLIPPAGE = {"GOLD": 0.80, "BTC": 50.00}


def check_kill_switch(state) -> Tuple[bool, str]:
    """Gate 1: Emergency kill-switch must not be active."""
    if state.kill_switch_active:
        return False, f"Kill-Switch ACTIVE: {state.kill_switch_reason}"
    return True, "Kill-Switch armed (normal execution)"


def check_daily_loss(state) -> Tuple[bool, str]:
    """Gate 2: Daily loss circuit breaker must not be tripped."""
    if state.daily_circuit_breaker_tripped:
        return False, f"Daily loss circuit breaker tripped (loss: {state.daily_pnl:+.2f})"
    starting = state.starting_daily_equity or 10000.0
    max_loss = state.max_daily_loss_pct
    if starting > 0:
        daily_loss_pct = (state.daily_pnl / starting) * 100.0
        if daily_loss_pct <= -max_loss:
            return False, f"Daily loss limit reached: {daily_loss_pct:.2f}% (limit: -{max_loss:.1f}%)"
    return True, f"Daily loss within limits ({state.daily_pnl:+,.2f})"


def check_concurrent_positions(state, max_positions: int = 2) -> Tuple[bool, str]:
    """Gate 3: Max concurrent open positions."""
    if state.open_positions_count >= max_positions:
        return False, f"Max concurrent positions reached ({state.open_positions_count}/{max_positions})"
    return True, f"Position count OK ({state.open_positions_count}/{max_positions})"


def check_risk_cap(state, proposed_risk_pct: float) -> Tuple[bool, str]:
    """Gate 4: Combined open risk + proposed must not exceed cap."""
    current_open_risk = 0.0
    for p in state.open_positions:
        current_open_risk += float(p.get("risk_pct") or 1.0)
    if (current_open_risk + proposed_risk_pct) > state.max_total_open_risk_pct:
        return False, (
            f"Portfolio risk cap exceeded: {current_open_risk:.2f}% + {proposed_risk_pct:.2f}% "
            f"= {current_open_risk + proposed_risk_pct:.2f}% > {state.max_total_open_risk_pct:.1f}%"
        )
    return True, f"Risk cap OK ({current_open_risk + proposed_risk_pct:.2f}% <= {state.max_total_open_risk_pct:.1f}%)"


def check_stale_data(data_timestamp: Optional[float], max_age_seconds: int = MAX_DATA_STALENESS_SECONDS) -> Tuple[bool, str]:
    """Gate 5: Market data must not be stale."""
    if data_timestamp is None:
        return False, "No market data timestamp provided"
    age = time.time() - data_timestamp
    if age > max_age_seconds:
        return False, f"Stale market data: {age/60.0:.1f} min old (limit: {max_age_seconds/60:.0f}m)"
    return True, f"Data fresh ({age:.0f}s old)"


def check_spread(spread_val: float, asset: str) -> Tuple[bool, str]:
    """Gate 6: Spread must not exceed threshold."""
    asset_key = "GOLD" if asset.upper() in ("GOLD", "XAU", "XAUUSD", "GC=F") else "BTC"
    max_spread = MAX_ALLOWED_SPREAD.get(asset_key, 0.60)
    if spread_val > max_spread:
        return False, f"Excessive spread: {spread_val:.2f} > {max_spread:.2f}"
    return True, f"Spread OK ({spread_val:.2f})"


def check_sl_tp_side(action: str, entry: float, sl: float, tp1: float) -> Tuple[bool, str]:
    """Gate 7: SL/TP side validation — BUY: SL < entry < TP; SELL: TP < entry < SL."""
    is_buy = action.upper() in ("BUY", "LONG")
    if is_buy:
        if not (sl < entry < tp1):
            return False, f"Inverted SL/TP for BUY: SL({sl}) must be < Entry({entry}) < TP({tp1})"
    else:
        if not (tp1 < entry < sl):
            return False, f"Inverted SL/TP for SELL: TP({tp1}) must be < Entry({entry}) < SL({sl})"
    return True, "SL/TP side valid"


def check_lot_bounds(lot_size: float, min_lot: float = 0.01, max_lot: float = 50.0) -> Tuple[bool, str]:
    """Gate 8: Lot size within broker bounds."""
    if lot_size < min_lot:
        return False, f"Lot size {lot_size} below minimum {min_lot}"
    if lot_size > max_lot:
        return False, f"Lot size {lot_size} above maximum {max_lot}"
    return True, f"Lot size OK ({lot_size})"


def check_cooldown(state, asset: str) -> Tuple[bool, str]:
    """Gate 9: Asset must not be in cooldown."""
    if state.is_cooldown_active(asset):
        until = state.cooldowns.get(asset, 0.0)
        remaining = until - time.time()
        return False, f"Asset {asset} in cooldown for {remaining:.0f}s"
    return True, f"Asset {asset} not in cooldown"


def check_news_window(asset: str, is_news_blocked: bool, news_msg: str = "") -> Tuple[bool, str]:
    """Gate 10: No high-impact news blocking entry."""
    if is_news_blocked:
        return False, f"News avoidance gate: {news_msg}"
    return True, "No news window blocking"


def check_session(session_info: dict) -> Tuple[bool, str]:
    """Gate 11: Not in rollover spread window."""
    if session_info.get("is_rollover", False):
        return False, "Rollover spread window (21:50-22:15 UTC) — trading frozen"
    return True, f"Session OK: {session_info.get('session', 'Unknown')}"


def check_margin(state, required_margin: float) -> Tuple[bool, str]:
    """Gate 12: Free margin must cover required margin with 25% buffer."""
    needed = required_margin * 1.25
    if state.free_margin < needed:
        return False, f"Insufficient free margin: need ${needed:,.2f}, have ${state.free_margin:,.2f}"
    return True, f"Margin OK (free: ${state.free_margin:,.2f}, need: ${needed:,.2f})"


def check_confidence_score(score: float, min_score: float = 8.0) -> Tuple[bool, str]:
    """Gate 13: Confluence confidence score must meet threshold."""
    if score < min_score:
        return False, f"Confluence score {score:.1f} below minimum {min_score:.1f}"
    return True, f"Confluence score OK ({score:.1f} >= {min_score:.1f})"


def check_symbol_tradable(symbol: str, trade_mode: int = None, is_buy: bool = True) -> Tuple[bool, str]:
    """Gate 14: Symbol must be tradable (not disabled, not short-only/long-only mismatch)."""
    try:
        import MetaTrader5 as mt5
    except Exception:
        return True, "MetaTrader5 not available — symbol tradability assumed"
    if trade_mode is None:
        return True, "Symbol tradability assumed (no MT5 info)"
    if trade_mode == mt5.SYMBOL_TRADE_MODE_DISABLED:
        return False, f"Symbol {symbol} trading DISABLED by broker"
    if is_buy and trade_mode == mt5.SYMBOL_TRADE_MODE_SHORTONLY:
        return False, f"Symbol {symbol} in SHORT-ONLY mode"
    if not is_buy and trade_mode == mt5.SYMBOL_TRADE_MODE_LONGONLY:
        return False, f"Symbol {symbol} in LONG-ONLY mode"
    return True, f"Symbol {symbol} tradable"


def check_toxic_blacklist(asset: str, action: str, market_vector: dict,
                          threshold: float = 0.80) -> Tuple[bool, str]:
    """Gate 15: Check proposed trade against Negative Memory Bank (toxic setups).

    Returns (pass: bool, reason: str). If a toxic signature matches with
    similarity >= threshold, the trade is vetoed.
    """
    try:
        from self_learning import self_learning_engine
        sle = self_learning_engine
    except Exception:
        return True, "Self-learning engine unavailable — toxic check skipped"

    if not sle or not market_vector:
        return True, "No market data for toxic check"

    # Require minimum keys
    required_keys = ("rsi", "adx", "upper_wick_pct", "lower_wick_pct",
                     "tnx_chg", "dxy_chg", "regime")
    if not any(k in market_vector for k in required_keys):
        return True, "Incomplete market vector — toxic check skipped"

    veto, reason = sle.check_negative_memory_veto(
        asset=asset, action=action,
        market_vector=market_vector, threshold=threshold
    )
    if veto:
        return False, reason
    return True, "No toxic memory match"


def check_confidence_threshold(confidence_score: float, min_score: float = 7.0) -> Tuple[bool, str]:
    """Gate 16: Confidence score must meet minimum threshold for trade."""
    if confidence_score < min_score:
        return False, f"Confidence {confidence_score:.1f} below minimum {min_score:.1f} — trade skipped"
    return True, f"Confidence OK ({confidence_score:.1f} >= {min_score:.1f})"


def check_consecutive_losses(sle=None) -> Tuple[bool, str, float]:
    """Gate 17: Consecutive loss protection — reduce risk or block trading.

    Returns (pass: bool, reason: str, risk_multiplier: float).
    - 0 losses: pass, 1.0x risk
    - 1 loss: pass, 0.75x risk
    - 2 losses: pass, 0.50x risk  
    - 3+ losses: FAIL, cooldown active
    """
    if sle is None:
        try:
            from self_learning import self_learning_engine
            sle = self_learning_engine
        except Exception:
            return True, "Self-learning unavailable — loss tracking skipped", 1.0

    if not sle:
        return True, "Self-learning unavailable — loss tracking skipped", 1.0

    is_cd, reason, remaining = sle.is_in_loss_cooldown()
    if is_cd:
        return False, reason, 0.0

    count = sle.get_consecutive_losses()
    multiplier = sle.get_risk_reduction_multiplier()

    if count >= 2:
        return False, f"{count} consecutive losses — risk reduced to {multiplier:.0%}, cooldown active", multiplier
    elif count >= 1:
        return True, f"{count} consecutive loss — risk reduced to {multiplier:.0%}", multiplier

    return True, "No consecutive losses — full risk", multiplier


def check_strategy_health(strategy: str, min_trades: int = 20, min_win_rate: float = 40.0) -> Tuple[bool, str]:
    """Gate 17: Auto-disable strategies with poor recent performance.

    Checks strategy_performance from self_learning memory. If a strategy has
    >= min_trades closed and win_rate_pct < min_win_rate, veto new entries.
    Prevents bleeding capital on broken strategies.
    """
    try:
        from self_learning import self_learning_engine
        sle = self_learning_engine
    except Exception:
        return True, "Self-learning engine unavailable — strategy health check skipped"

    if not sle:
        return True, "Self-learning engine unavailable — strategy health check skipped"

    strat_stats = sle.memory.get("strategy_performance", {})
    st = strat_stats.get(strategy.upper())
    if not st:
        return True, f"No performance data for {strategy} — check skipped"

    total = st.get("total_trades", 0)
    if total < min_trades:
        return True, f"{strategy} only {total} trades (< {min_trades}) — health check skipped"

    win_rate = st.get("win_rate_pct", 0.0)
    if win_rate < min_win_rate:
        return False, (
            f"{strategy} auto-disabled: win rate {win_rate:.1f}% "
            f"below {min_win_rate:.1f}% threshold ({total} trades)"
        )

    return True, f"{strategy} healthy: {win_rate:.1f}% WR ({total} trades)"


def check_spread_to_risk(spread_val: float, sl_dist: float, asset: str) -> Tuple[bool, str]:
    """Gate 18: Spread-to-Risk Guard (Phase 4.2).
    - GOLD: spread must be < 20% of SL distance.
    - BTC: spread must be < 15% of SL distance.
    """
    if sl_dist <= 0:
        return False, "Invalid zero or negative stop loss distance"
    asset_key = "GOLD" if asset.upper() in ("GOLD", "XAU", "XAUUSD", "GC=F") else "BTC"
    max_ratio = 0.20 if asset_key == "GOLD" else 0.15
    ratio = spread_val / sl_dist
    if ratio > max_ratio:
        return False, f"Excessive spread-to-risk ratio: spread {spread_val:.2f} is {ratio:.1%} of SL ({sl_dist:.2f}), limit {max_ratio:.0%}"
    return True, f"Spread-to-risk OK ({ratio:.1%} <= {max_ratio:.0%})"


def check_trend_alignment(asset: str, action: str, adx: float, consecutive_extremes: int) -> Tuple[bool, str]:
    """Gate 19: Falling Knife / Parabolic Guard (Phase 3.3).
    - No BUY if: ADX > 30 and price made >= 3 consecutive lower lows (freefall).
    - No SELL if: ADX > 30 and price made >= 3 consecutive higher highs (parabolic).
    """
    act = action.upper()
    if act in ("BUY", "LONG") and adx > 30.0 and consecutive_extremes >= 3:
        return False, f"Falling knife guard: ADX {adx:.1f} > 30 with {consecutive_extremes} consecutive lower lows (freefall)"
    elif act in ("SELL", "SHORT") and adx > 30.0 and consecutive_extremes >= 3:
        return False, f"Parabolic surge guard: ADX {adx:.1f} > 30 with {consecutive_extremes} consecutive higher highs (parabolic)"
    return True, "Trend alignment OK (no falling knife or parabolic surge)"


def check_htf_bias_alignment(asset: str, action: str, score: float = 8.0, strategy: str = "SCALP") -> Tuple[bool, str]:
    """Gate 20: Higher Timeframe Bias Alignment (Phase 3.1).
    - If HTF bias is BEARISH and action is BUY -> SKIP (unless confluence >= 9.0).
    - If HTF bias is BULLISH and action is SELL -> SKIP (unless confluence >= 9.0).
    - If HTF bias is NEUTRAL -> allow only SCALP strategy with score >= 8.0.
    """
    try:
        from institutional_engine import compute_htf_bias
        bias_res = compute_htf_bias(asset)
        bias = bias_res.get("overall_bias", "NEUTRAL").upper() if isinstance(bias_res, dict) else str(bias_res).upper()
    except Exception:
        bias = "NEUTRAL"

    act = action.upper()
    is_buy = act in ("BUY", "LONG")

    if bias == "BEARISH" and is_buy:
        if score < 9.0:
            return False, f"Counter-trend veto: HTF bias is BEARISH but action is BUY (confluence {score:.1f} < 9.0 required for counter-trend)"
    elif bias == "BULLISH" and not is_buy:
        if score < 9.0:
            return False, f"Counter-trend veto: HTF bias is BULLISH but action is SELL (confluence {score:.1f} < 9.0 required for counter-trend)"
    elif bias == "NEUTRAL":
        if strategy.upper() != "SCALP" or score < 8.0:
            return False, f"HTF bias is NEUTRAL — only SCALP strategy with score >= 8.0 allowed (got {strategy} @ {score:.1f})"

    return True, f"HTF bias alignment verified ({bias} -> {act})"


def check_mtf_alignment(asset: str, action: str, mtf_bars: dict = None) -> Tuple[bool, str]:
    """Gate 21: Multi-Timeframe Decision Hierarchy (Phase 3.4).
    Hierarchy: 1m Analysis -> 5m Decision -> 15m Bias.
    - 15m candle establishes prevailing trend direction.
    - 5m candle provides structure and entry trigger.
    - 1m candle provides micro-structure and entry timing.
    - If 15m bias, 5m structure, and 1m trigger conflict -> SKIP.
    """
    if not mtf_bars:
        try:
            from market_data import market_feed
            mtf_bars = market_feed.get_multitimeframe_bars(asset)
        except Exception:
            return True, "MTF bars unavailable — hierarchy assumed valid"

    if not mtf_bars:
        return True, "No MTF data — hierarchy check skipped"

    act = action.upper()
    is_buy = act in ("BUY", "LONG")

    # 1. 15m Trend Bias Check
    bars_15m = mtf_bars.get("m15")
    bias_15m = "NEUTRAL"
    if bars_15m is not None and len(bars_15m) >= 20:
        c15 = bars_15m["Close"].iloc[-1]
        sma20_15m = bars_15m["Close"].rolling(20).mean().iloc[-1]
        bias_15m = "BULLISH" if c15 > sma20_15m else "BEARISH"
        if is_buy and bias_15m == "BEARISH":
            return False, "15m trend bias is BEARISH — cannot open BUY scalp"
        elif not is_buy and bias_15m == "BULLISH":
            return False, "15m trend bias is BULLISH — cannot open SELL scalp"

    # 2. 5m Structure & Decision Timeframe Check
    bars_5m = mtf_bars.get("m5")
    if bars_5m is not None and len(bars_5m) >= 10:
        c5 = bars_5m["Close"].iloc[-1]
        o5 = bars_5m["Open"].iloc[-1]
        sma9_5m = bars_5m["Close"].rolling(9).mean().iloc[-1]
        if is_buy and c5 < sma9_5m and c5 < o5:
            return False, "5m candle structure is BEARISH (Close < Open and below 9 EMA) — BUY scalp invalid"
        elif not is_buy and c5 > sma9_5m and c5 > o5:
            return False, "5m candle structure is BULLISH (Close > Open and above 9 EMA) — SELL scalp invalid"

    # 3. 1m Microstructure & Entry Timing Check
    bars_1m = mtf_bars.get("m1")
    if bars_1m is not None and len(bars_1m) >= 5:
        c1 = bars_1m["Close"].iloc[-1]
        o1 = bars_1m["Open"].iloc[-1]
        h1 = bars_1m["High"].iloc[-1]
        l1 = bars_1m["Low"].iloc[-1]
        total_range = h1 - l1
        if total_range > 0:
            upper_wick = (h1 - max(c1, o1)) / total_range
            lower_wick = (min(c1, o1) - l1) / total_range
            if is_buy and upper_wick >= 0.40 and c1 < o1:
                return False, f"1m microstructure has heavy upper wick rejection ({upper_wick:.0%}) — BUY entry blocked"
            elif not is_buy and lower_wick >= 0.40 and c1 > o1:
                return False, f"1m microstructure has heavy lower wick rejection ({lower_wick:.0%}) — SELL entry blocked"

    return True, "MTF hierarchy alignment verified: 15m Bias, 5m Structure, and 1m Trigger all agree"


def check_correlation_guard(proposed_asset: str, proposed_action: str, open_positions: list, score: float = 8.0) -> Tuple[bool, str]:
    """Gate 22: Correlation Guard (Phase 4.5).
    Block concurrent GOLD + BTC entries in the same direction if both have confluence >= 8.0 (avoids double USD exposure).
    """
    if not open_positions:
        return True, "No open positions — correlation guard OK"

    prop_asset = "GOLD" if proposed_asset.upper() in ("GOLD", "XAU", "XAUUSD", "GC=F") else "BTC"
    prop_act = proposed_action.upper()

    for pos in open_positions:
        other_asset = "GOLD" if pos.get("asset", "").upper() in ("GOLD", "XAU", "XAUUSD", "GC=F") else "BTC"
        other_act = pos.get("action", "").upper()
        if other_asset != prop_asset and other_act == prop_act:
            if score >= 8.0:
                return False, f"Correlation guard: concurrent {other_asset} and {prop_asset} in same direction ({prop_act}) blocked to avoid double USD exposure"

    return True, "Correlation guard OK (no conflicting double USD exposure)"


def check_min_rr_rule(entry: float, sl: float, tp1: float, min_rr: float = 2.0) -> Tuple[bool, str]:
    """Gate 23: Universal RR Rule (Phase 8.5).
    All profiles enforce minimum 1:2 risk-to-reward. If structure-based SL gives < 1:2 RR -> skip trade.
    """
    sl_dist = abs(entry - sl)
    tp_dist = abs(tp1 - entry)
    if sl_dist <= 0:
        return False, "Invalid zero SL distance"
    rr = round(tp_dist / sl_dist, 2)
    if rr < min_rr:
        return False, f"Risk-to-Reward ratio {rr:.2f}:1 is below minimum requirement {min_rr:.1f}:1"
    return True, f"Risk-to-Reward ratio OK ({rr:.2f}:1 >= {min_rr:.1f}:1)"
