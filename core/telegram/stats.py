"""
Telegram Bot Stats Module — performance dashboard computation and formatting.

Extracted from telegram_bot.py god object to improve modularity and testability.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

try:
    from utils.logger import get_logger
    logger = get_logger("telegram_stats")
except Exception:
    import logging
    logger = logging.getLogger("telegram_stats")

STATS_CACHE: Dict[str, Any] = {
    "last_mtime": 0.0,
    "last_calc_time": 0.0,
    "cached_data": None,
}

# Optional globals injected from the main telegram_bot module at import time
safety_manager = None
live_broker = None
MT5_EXECUTOR_AVAILABLE = False


def inject_dependencies(sm=None, broker=None, mt5_available: bool = False) -> None:
    """Inject shared singletons for stats computation (avoids circular imports)."""
    global safety_manager, live_broker, MT5_EXECUTOR_AVAILABLE
    safety_manager = sm
    live_broker = broker
    MT5_EXECUTOR_AVAILABLE = mt5_available


def compute_live_stats(audit_file: str = "trade_audit.jsonl") -> dict:
    """
    Computes institutional performance metrics from trade_audit.jsonl with 15s caching.
    """
    now = time.time()
    mtime = os.path.getmtime(audit_file) if os.path.exists(audit_file) else 0.0
    if STATS_CACHE["cached_data"] and (now - STATS_CACHE["last_calc_time"] < 15.0) and (mtime == STATS_CACHE["last_mtime"]):
        return STATS_CACHE["cached_data"]

    total_trades = 0
    wins = 0
    losses = 0
    be_trades = 0
    gross_profit = 0.0
    gross_loss = 0.0
    total_pnl = 0.0
    r_multiples = []

    today_utc_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    week_ago_utc = datetime.now(timezone.utc) - timedelta(days=7)
    daily_pnl = 0.0
    weekly_pnl = 0.0

    cumulative_pnl = 0.0
    peak_pnl = 0.0
    max_drawdown_usd = 0.0

    if os.path.exists(audit_file):
        try:
            with open(audit_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    event = row.get("event")
                    if event in ("POSITION_CLOSED", "PARTIAL_CLOSE_PAPER", "PARTIAL_CLOSE_MT5"):
                        total_trades += 1
                        pnl = float(row.get("pnl_usd", 0.0))
                        total_pnl += pnl
                        r_val = float(row.get("r_multiple", 0.0))
                        r_multiples.append(r_val)

                        if pnl > 0.001:
                            wins += 1
                            gross_profit += pnl
                        elif pnl < -0.001:
                            losses += 1
                            gross_loss += abs(pnl)
                        else:
                            be_trades += 1

                        ts_str = row.get("timestamp", "")
                        if ts_str:
                            try:
                                clean_ts = ts_str.replace("Z", "+00:00")
                                dt = datetime.fromisoformat(clean_ts)
                                if dt.strftime("%Y-%m-%d") == today_utc_str:
                                    daily_pnl += pnl
                                if dt >= week_ago_utc:
                                    weekly_pnl += pnl
                            except Exception:
                                pass

                        cumulative_pnl += pnl
                        if cumulative_pnl > peak_pnl:
                            peak_pnl = cumulative_pnl
                        dd = peak_pnl - cumulative_pnl
                        if dd > max_drawdown_usd:
                            max_drawdown_usd = dd
        except Exception as e:
            logger.warning(f"Error parsing trade_audit.jsonl for stats: {e}")

    winrate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 1.0)
    expectancy_r = (sum(r_multiples) / len(r_multiples)) if r_multiples else 0.0

    mode = safety_manager.get_trading_mode() if safety_manager else "PAPER"
    if mode == "PAPER" and safety_manager:
        paper_acc = safety_manager.state.get("paper_account", {})
        balance = paper_acc.get("balance", 10000.0)
        equity = balance + safety_manager.state.get("realized_daily_pnl", 0.0)
        open_pos = safety_manager.get_paper_positions()
    else:
        acc_data = live_broker.get_live_account_data() if (MT5_EXECUTOR_AVAILABLE and live_broker) else {}
        balance = acc_data.get("balance", 10000.0)
        equity = acc_data.get("equity", balance)
        open_pos = live_broker.get_open_positions() if (MT5_EXECUTOR_AVAILABLE and live_broker) else []

    open_count = len(open_pos) if isinstance(open_pos, list) else 0
    max_dd_pct = (max_drawdown_usd / (balance if balance > 0 else 10000.0)) * 100.0

    open_risk_pct = 0.0
    if isinstance(open_pos, list) and equity > 0:
        for p in open_pos:
            r_pct = float(p.get("risk_pct", 0.50))
            open_risk_pct += r_pct

    data = {
        "mode": mode,
        "balance": balance,
        "equity": equity,
        "open_positions": open_count,
        "open_risk_pct": open_risk_pct,
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "breakeven": be_trades,
        "winrate": winrate,
        "profit_factor": profit_factor,
        "expectancy_r": expectancy_r,
        "net_pnl": total_pnl,
        "daily_pnl": daily_pnl,
        "weekly_pnl": weekly_pnl,
        "max_drawdown_usd": max_drawdown_usd,
        "max_drawdown_pct": max_dd_pct,
    }
    STATS_CACHE["last_mtime"] = mtime
    STATS_CACHE["last_calc_time"] = now
    STATS_CACHE["cached_data"] = data
    return data


def format_stats_dashboard(stats: dict) -> str:
    """Formats performance stats cleanly for mobile Telegram."""
    pnl_sign = "+" if stats["net_pnl"] >= 0 else ""
    daily_sign = "+" if stats["daily_pnl"] >= 0 else ""
    weekly_sign = "+" if stats["weekly_pnl"] >= 0 else ""
    pf_str = f"{stats['profit_factor']:.2f}" if stats['profit_factor'] < 100.0 else "∞ (Clean)"

    lines_out = [
        "📊 *INSTITUTIONAL PERFORMANCE STATS*",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"• *Account:* Equity `${stats['equity']:,.2f}` | Bal `${stats['balance']:,.2f}`",
        f"• *Mode:* `{stats['mode']}` | *Open Positions:* `{stats['open_positions']}` (Risk: `{stats['open_risk_pct']:.2f}%`)",
        "",
        "📈 *Trade Execution Metrics:*",
        f"• Total Closed Trades: `{stats['total_trades']}`",
        f"• Wins / Losses: `🟢 {stats['wins']}W - 🔴 {stats['losses']}L` (BE: `{stats['breakeven']}`)",
        f"• Winrate: *{stats['winrate']:.1f}%*",
        f"• Profit Factor: *{pf_str}*",
        f"• Expectancy: *{stats['expectancy_r']:+.2f}R* per trade",
        "",
        "💰 *PnL Breakdown:*",
        f"• Today's PnL: `{daily_sign}${stats['daily_pnl']:,.2f}`",
        f"• 7-Day PnL: `{weekly_sign}${stats['weekly_pnl']:,.2f}`",
        f"• All-Time Net PnL: *`{pnl_sign}${stats['net_pnl']:,.2f}`*",
        f"• Max Drawdown: `-${stats['max_drawdown_usd']:,.2f}` ({stats['max_drawdown_pct']:.2f}%)",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    ]
    return "\n".join(lines_out)
