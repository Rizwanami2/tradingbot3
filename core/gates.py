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
        current_open_risk += float(p.get("risk_pct", 1.0))
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
    import mt5
    if trade_mode is None:
        return True, "Symbol tradability assumed (no MT5 info)"
    if trade_mode == mt5.SYMBOL_TRADE_MODE_DISABLED:
        return False, f"Symbol {symbol} trading DISABLED by broker"
    if is_buy and trade_mode == mt5.SYMBOL_TRADE_MODE_SHORTONLY:
        return False, f"Symbol {symbol} in SHORT-ONLY mode"
    if not is_buy and trade_mode == mt5.SYMBOL_TRADE_MODE_LONGONLY:
        return False, f"Symbol {symbol} in LONG-ONLY mode"
    return True, f"Symbol {symbol} tradable"
