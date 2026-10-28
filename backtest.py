#!/usr/bin/env python3
"""
backtest.py
Institutional Hard-Asset Quantitative Backtest Engine.
Exclusively for Gold (XAU/USD, GC=F) and Bitcoin (BTC/USD, BTC-USD).

Evaluates:
  1. Multi-Strategy Performance (SCALP, SWING, BALANCE, SWAP).
  2. Hard 8/10 Confluence Veto Guardrail (Score >= 8 required).
  3. Wyckoff Anti-Trap & Microstructure Wick Filtering.
  4. Profile-Calibrated Breakeven & Trailing Stops.
  5. Realistic Broker Spread & Slippage Deduction.
  6. Comprehensive Institutional Risk & Return Metrics:
     Win Rate, Profit Factor, Sharpe Ratio, Sortino Ratio, Calmar Ratio,
     Max Drawdown, Expectancy, and Trade Resolution Breakdown.
"""

import warnings
warnings.filterwarnings("ignore")
import os
os.environ["PYTHONWARNINGS"] = "ignore"
import logging
logging.captureWarnings(True)

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import math
import argparse
from datetime import datetime
import numpy as np
import pandas as pd
import yfinance as yf

# Institutional Risk & Execution Engines
from risk_engine import (
    STRATEGIES, calculate_lot_size, calculate_strategy_levels,
    validate_strategy_accuracy, get_market_session
)

# Realistic Transaction Costs (Spread + Slippage per round-trip)
COST_MODELS = {
    "GOLD": {"spread_pts": 0.35, "slippage_pts": 0.05, "total_pts": 0.40},  # $0.40/oz round trip
    "BTC":  {"spread_pts": 15.0, "slippage_pts": 5.0,  "total_pts": 20.0}   # $20.00/BTC round trip
}


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Computes technical indicators, moving averages, and ATR."""
    data = df.copy()
    close = data["Close"]
    high = data["High"]
    low = data["Low"]

    # Moving Averages
    data["SMA50"] = close.rolling(window=50, min_periods=20).mean()
    data["SMA200"] = close.rolling(window=200, min_periods=50).mean()
    data["EMA20"] = close.ewm(span=20, adjust=False).mean()

    # RSI (14)
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=14, min_periods=14).mean()
    avg_loss = loss.rolling(window=14, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    data["RSI"] = 100 - (100 / (1 + rs))
    data["RSI"] = data["RSI"].fillna(50.0)

    # ATR (14)
    h_l = high - low
    h_pc = (high - close.shift(1)).abs()
    l_pc = (low - close.shift(1)).abs()
    tr = np.maximum(h_l, np.maximum(h_pc, l_pc))
    data["ATR"] = tr.rolling(window=14, min_periods=14).mean()

    # ADX and Directional Indicators (+DI, -DI)
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_dm_s = pd.Series(plus_dm, index=data.index)
    minus_dm_s = pd.Series(minus_dm, index=data.index)
    tr_smooth = tr.rolling(14, min_periods=14).mean()
    plus_di = 100 * (plus_dm_s.rolling(14, min_periods=14).mean() / tr_smooth.replace(0, np.nan))
    minus_di = 100 * (minus_dm_s.rolling(14, min_periods=14).mean() / tr_smooth.replace(0, np.nan))
    dx = 100 * (np.abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan))
    data["ADX"] = dx.rolling(14, min_periods=14).mean().fillna(20.0)
    data["PLUS_DI"] = plus_di.fillna(20.0)
    data["MINUS_DI"] = minus_di.fillna(20.0)

    return data


def run_historical_backtest(asset: str = "GOLD",
                            strategy_code: str = "SCALP",
                            lookback_days: int = 365,
                            initial_capital: float = 10000.0,
                            min_score_filter: int = 8,
                            allow_b_setups: bool = False) -> dict:
    """
    Rigorously simulates strategy performance on historical data without look-ahead bias.
    """
    asset_key = "GOLD" if asset.upper() in ("GOLD", "XAU", "XAUUSD", "GC=F") else "BTC"
    symbol = "GC=F" if asset_key == "GOLD" else "BTC-USD"
    strat_code = strategy_code.upper()
    strat = STRATEGIES.get(strat_code, STRATEGIES["SCALP"])
    cost_model = COST_MODELS[asset_key]

    # Fetch Price Data
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period=f"{lookback_days + 150}d")
    if hist.empty or len(hist) < 80:
        return {"error": f"Insufficient historical data fetched for {symbol}"}

    # Fetch Macro Context
    dxy_hist = yf.Ticker("DX-Y.NYB").history(period=f"{lookback_days + 150}d")
    tnx_hist = yf.Ticker("^TNX").history(period=f"{lookback_days + 150}d")
    vix_hist = yf.Ticker("^VIX").history(period=f"{lookback_days + 150}d")

    # Compute Indicators
    df = compute_indicators(hist)

    capital = initial_capital
    peak_capital = initial_capital
    trades = []
    equity_curve = [initial_capital]

    # Simulation loop (from bar 60 to len(df) - 10)
    # Using bar t close for evaluation, entering on next bar open/close
    start_idx = 60
    end_idx = len(df) - 5
    in_trade_until = 0  # Prevents overlapping trade distortion for the same asset

    for i in range(start_idx, end_idx):
        if i < in_trade_until:
            continue

        row = df.iloc[i]
        curr_price = row["Close"]
        atr = row["ATR"]
        rsi = row["RSI"]
        adx = row["ADX"]
        plus_di = row["PLUS_DI"]
        minus_di = row["MINUS_DI"]
        ma50 = row["SMA50"]
        ma200 = row["SMA200"]
        ma20_ema = row["EMA20"]

        if pd.isna(atr) or atr <= 0:
            continue

        # Structural levels from rolling 60 bars (strictly past data)
        sub_high = df["High"].iloc[max(0, i-60):i+1]
        sub_low = df["Low"].iloc[max(0, i-60):i+1]
        sw_high = sub_high.max()
        sw_low = sub_low.min()
        sw_range = sw_high - sw_low
        if sw_range <= 0:
            continue

        fib_500 = sw_high - 0.500 * sw_range
        fib_618 = sw_high - 0.618 * sw_range
        fib_650 = sw_high - 0.650 * sw_range
        in_golden_pocket = (curr_price >= fib_650 * 0.985) and (curr_price <= fib_618 * 1.02)

        # Microstructure & Candle Geometry
        c_open, c_high, c_low, c_close = row["Open"], row["High"], row["Low"], row["Close"]
        c_range = c_high - c_low
        up_wick_pct = ((c_high - max(c_open, c_close)) / c_range * 100) if c_range > 0 else 0.0
        low_wick_pct = ((min(c_open, c_close) - c_low) / c_range * 100) if c_range > 0 else 0.0
        candle_body_pct = (abs(c_close - c_open) / c_range * 100) if c_range > 0 else 50.0

        is_bull_trap = (up_wick_pct >= 40.0) and (curr_price >= sw_high * 0.98)
        trap_type = "BULL_TRAP" if is_bull_trap else "CLEAN"

        # Macro Context
        dxy_chg = 0.0
        if not dxy_hist.empty and i < len(dxy_hist) and i >= 2:
            dxy_chg = ((dxy_hist["Close"].iloc[min(i, len(dxy_hist)-1)] / dxy_hist["Close"].iloc[min(i-2, len(dxy_hist)-2)]) - 1) * 100

        tnx_chg = 0.0
        if not tnx_hist.empty and i < len(tnx_hist) and i >= 2:
            tnx_chg = ((tnx_hist["Close"].iloc[min(i, len(tnx_hist)-1)] / tnx_hist["Close"].iloc[min(i-2, len(tnx_hist)-2)]) - 1) * 100

        vix_val = 18.0
        if not vix_hist.empty and i < len(vix_hist):
            vix_val = float(vix_hist["Close"].iloc[min(i, len(vix_hist)-1)])

        macro_data = {
            "dxy_chg": dxy_chg,
            "tnx_chg": tnx_chg,
            "vix": vix_val,
            "gsr": 82.0
        }

        # 10-Point Hard Asset Confluence Matrix Evaluation
        score = 0
        if in_golden_pocket: score += 1
        if trap_type != "BULL_TRAP": score += 1
        if not np.isnan(ma200) and curr_price > ma200: score += 1
        if not np.isnan(ma50) and curr_price > ma50: score += 1
        if 40.0 <= rsi <= 65.0: score += 1
        if dxy_chg <= 0.15: score += 1
        if tnx_chg <= 0.50: score += 1
        if asset_key == "BTC":
            mayer = (curr_price / ma200) if not np.isnan(ma200) and ma200 > 0 else 1.0
            if 0.85 <= mayer <= 1.50: score += 1
        else:
            score += 1  # GSR undervaluation point for Gold
        if vix_val <= 25.0: score += 1
        if (curr_price - sw_low) / curr_price <= 0.05: score += 1

        # Strict Confluence Filter
        if score < min_score_filter:
            if not (allow_b_setups and score >= 7):
                continue

        # Strategy Accuracy Verification
        levels_mock = {
            "curr": curr_price, "sw_high": sw_high, "sw_low": sw_low,
            "fib_500": fib_500, "fib_618": fib_618, "fib_650": fib_650,
            "in_golden_pocket": in_golden_pocket, "ma50": ma50, "ma200": ma200,
            "ma20_ema": ma20_ema
        }

        accuracy = validate_strategy_accuracy(
            strat_code=strat_code,
            asset=asset_key,
            current_price=curr_price,
            atr=atr,
            rsi=rsi,
            adx=adx,
            levels=levels_mock,
            trap_type=trap_type,
            upper_wick_pct=up_wick_pct,
            lower_wick_pct=low_wick_pct,
            candle_body_pct=candle_body_pct,
            plus_di=plus_di,
            minus_di=minus_di,
            macro=macro_data,
            action="BUY"
        )

        if not accuracy["passed"]:
            continue

        # Calculate Entry, SL, TP & Position Sizing
        risk_pct = strat["risk_pct"] if score >= 8 else (strat["risk_pct"] * 0.5)
        strat_calc = calculate_strategy_levels(
            asset=asset_key,
            current_price=curr_price,
            atr=atr,
            action="BUY",
            strategy=strat_code,
            account_balance=capital,
            risk_pct=risk_pct,
            levels=levels_mock
        )

        entry_price = curr_price
        initial_sl = strat_calc["stop_loss"]
        tp1 = strat_calc["tp1"]
        tp2 = strat_calc["tp2"]
        sl_dist = strat_calc["sl_dist"]
        lot_size = strat_calc["lot_size"]
        breakeven_r = strat["breakeven_r"]
        trail_start_r = strat["trail_start_r"]
        trail_step_r = strat["trail_step_r"]

        # Track Forward Price Action (Next 1 to 25 bars)
        active_sl = initial_sl
        is_breakeven_locked = False
        highest_price = entry_price
        trade_resolved = False
        exit_price = entry_price
        exit_bar = i + 1
        exit_reason = "STOP_LOSS"
        r_mult = -1.0

        max_forward_bars = 10 if strat_code == "SCALP" else 25
        forward_slice = df.iloc[i+1 : min(len(df), i + 1 + max_forward_bars)]

        for f_idx, (_, f_bar) in enumerate(forward_slice.iterrows()):
            f_high = f_bar["High"]
            f_low = f_bar["Low"]
            f_close = f_bar["Close"]
            exit_bar = i + 1 + f_idx

            if f_high > highest_price:
                highest_price = f_high

            floating_r = (highest_price - entry_price) / sl_dist if sl_dist > 0 else 0

            # 1. Breakeven Lock
            if floating_r >= breakeven_r and not is_breakeven_locked:
                active_sl = entry_price
                is_breakeven_locked = True

            # 2. Dynamic Trailing Stop
            if floating_r >= trail_start_r:
                desired_sl = highest_price - (trail_step_r * sl_dist)
                if desired_sl > active_sl:
                    active_sl = desired_sl

            # 3. Check for SL / Trailing Stop Trigger
            if f_low <= active_sl:
                exit_price = active_sl
                trade_resolved = True
                if is_breakeven_locked and active_sl >= entry_price:
                    exit_reason = "BREAKEVEN" if active_sl == entry_price else "TRAILED_STOP"
                    r_mult = max(0.0, (exit_price - entry_price) / sl_dist)
                else:
                    exit_reason = "STOP_LOSS"
                    r_mult = -1.0
                break

            # 4. Check for Take-Profit 2 (Extended Target)
            if f_high >= tp2:
                exit_price = tp2
                exit_reason = "TP2_EXTENDED"
                trade_resolved = True
                r_mult = strat["rr_tp2"]
                break

            # 5. Check for Take-Profit 1 (Primary Target)
            if f_high >= tp1:
                # Lock BE and trail remainder, or secure TP1
                exit_price = tp1
                exit_reason = "TP1_TARGET"
                trade_resolved = True
                r_mult = strat["rr_tp1"]
                break

        # If trade reached end of horizon without hitting SL/TP, close at market
        if not trade_resolved and not forward_slice.empty:
            last_bar = forward_slice.iloc[-1]
            exit_price = last_bar["Close"]
            r_mult = (exit_price - entry_price) / sl_dist if sl_dist > 0 else 0
            exit_reason = "HORIZON_EXPIRY"

        # Apply Realistic Costs & Slippage
        cost_pts = cost_model["total_pts"]
        realized_pts = (exit_price - entry_price) - cost_pts

        # Calculate Dollar PnL
        contract_mult = 100.0 if asset_key == "GOLD" else 1.0
        gross_pnl_usd = (exit_price - entry_price) * lot_size * contract_mult
        net_cost_usd = cost_pts * lot_size * contract_mult
        net_pnl_usd = gross_pnl_usd - net_cost_usd

        capital += net_pnl_usd
        if capital > peak_capital:
            peak_capital = capital
        drawdown_pct = ((peak_capital - capital) / peak_capital) * 100 if peak_capital > 0 else 0
        equity_curve.append(capital)

        is_win = net_pnl_usd > 0
        trades.append({
            "trade_num": len(trades) + 1,
            "entry_date": df.index[i].strftime("%Y-%m-%d"),
            "exit_date": df.index[min(len(df)-1, exit_bar)].strftime("%Y-%m-%d"),
            "holding_bars": exit_bar - i,
            "asset": asset_key,
            "strategy": strat_code,
            "score": score,
            "entry": round(entry_price, 2),
            "exit": round(exit_price, 2),
            "sl": round(initial_sl, 2),
            "tp1": round(tp1, 2),
            "lot_size": lot_size,
            "r_mult": round(r_mult, 2),
            "net_pnl_usd": round(net_pnl_usd, 2),
            "capital_after": round(capital, 2),
            "drawdown_pct": round(drawdown_pct, 2),
            "exit_reason": exit_reason,
            "outcome": "WIN" if is_win else ("BE" if exit_reason == "BREAKEVEN" else "LOSS")
        })

        in_trade_until = exit_bar

    # Compute Statistical Ratios
    return compute_performance_metrics(trades, initial_capital, capital, peak_capital, asset_key, strat_code, lookback_days)


def compute_performance_metrics(trades: list, initial_capital: float, final_capital: float,
                                peak_capital: float, asset: str, strategy: str, lookback_days: int) -> dict:
    """Computes comprehensive institutional performance, risk, and return ratios."""
    if not trades:
        return {
            "asset": asset, "strategy": strategy, "lookback_days": lookback_days,
            "initial_capital": initial_capital,
            "final_capital": round(final_capital, 2),
            "net_profit_usd": 0.0, "net_return_pct": 0.0, "max_drawdown_pct": 0.0,
            "total_trades": 0, "wins": 0, "losses": 0, "breakevens": 0,
            "win_rate_pct": 0.0, "profit_factor": 0.0,
            "sharpe_ratio": 0.0, "sortino_ratio": 0.0, "calmar_ratio": 0.0,
            "avg_trade_r": 0.0, "expectancy_usd": 0.0,
            "avg_win_usd": 0.0, "avg_loss_usd": 0.0, "win_loss_ratio": 0.0,
            "max_win_streak": 0, "max_loss_streak": 0,
            "exit_breakdown": {},
            "trades": []
        }

    total_trades = len(trades)
    wins = [t for t in trades if t["net_pnl_usd"] > 0]
    losses = [t for t in trades if t["net_pnl_usd"] < 0]
    breakevens = [t for t in trades if t["net_pnl_usd"] == 0 or t["exit_reason"] == "BREAKEVEN"]

    win_count = len(wins)
    loss_count = len(losses)
    win_rate = (win_count / total_trades) * 100.0 if total_trades > 0 else 0.0

    gross_profit = sum(t["net_pnl_usd"] for t in wins)
    gross_loss = abs(sum(t["net_pnl_usd"] for t in losses))
    net_profit = final_capital - initial_capital
    net_return_pct = (net_profit / initial_capital) * 100.0

    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)

    # Max Drawdown
    max_dd = max(t["drawdown_pct"] for t in trades) if trades else 0.0

    # R-Multiple & Expectancy
    r_multiples = [t["r_mult"] for t in trades]
    avg_r = float(np.mean(r_multiples)) if r_multiples else 0.0
    avg_win_usd = (gross_profit / win_count) if win_count > 0 else 0.0
    avg_loss_usd = (gross_loss / loss_count) if loss_count > 0 else 0.0
    win_loss_ratio = (avg_win_usd / avg_loss_usd) if avg_loss_usd > 0 else 0.0

    p_w = win_count / total_trades if total_trades > 0 else 0
    p_l = loss_count / total_trades if total_trades > 0 else 0
    expectancy_usd = (p_w * avg_win_usd) - (p_l * avg_loss_usd)

    # Sharpe & Sortino Ratios (Annualized)
    pnl_series = pd.Series([t["net_pnl_usd"] for t in trades])
    pnl_returns = pnl_series / initial_capital
    mean_ret = float(pnl_returns.mean()) if not pnl_returns.empty else 0.0
    std_ret = float(pnl_returns.std()) if len(pnl_returns) > 1 else 1e-4

    rf_daily = 0.04 / 252  # 4% risk-free rate
    sharpe = float(((mean_ret - rf_daily) / std_ret) * math.sqrt(252)) if std_ret > 0 else 0.0

    downside_returns = pnl_returns[pnl_returns < 0]
    downside_std = float(downside_returns.std()) if len(downside_returns) > 1 else std_ret
    sortino = float(((mean_ret - rf_daily) / downside_std) * math.sqrt(252)) if downside_std > 0 else 0.0

    # Calmar Ratio
    calmar = round((net_return_pct / max_dd), 2) if max_dd > 0 else 0.0

    # Consecutive Streaks
    max_win_streak = 0
    max_loss_streak = 0
    curr_w = 0
    curr_l = 0
    for t in trades:
        if t["net_pnl_usd"] > 0:
            curr_w += 1
            curr_l = 0
            if curr_w > max_win_streak: max_win_streak = curr_w
        elif t["net_pnl_usd"] < 0:
            curr_l += 1
            curr_w = 0
            if curr_l > max_loss_streak: max_loss_streak = curr_l
        else:
            curr_w = 0
            curr_l = 0

    # Exit Breakdown
    exit_counts = {}
    for t in trades:
        reason = t["exit_reason"]
        exit_counts[reason] = exit_counts.get(reason, 0) + 1

    return {
        "asset": asset,
        "strategy": strategy,
        "lookback_days": lookback_days,
        "initial_capital": initial_capital,
        "final_capital": round(final_capital, 2),
        "net_profit_usd": round(net_profit, 2),
        "net_return_pct": round(net_return_pct, 2),
        "total_trades": total_trades,
        "wins": win_count,
        "losses": loss_count,
        "breakevens": len(breakevens),
        "win_rate_pct": round(win_rate, 1),
        "profit_factor": profit_factor,
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe_ratio": round(sharpe, 2),
        "sortino_ratio": round(sortino, 2),
        "calmar_ratio": calmar,
        "avg_trade_r": round(avg_r, 2),
        "expectancy_usd": round(expectancy_usd, 2),
        "avg_win_usd": round(avg_win_usd, 2),
        "avg_loss_usd": round(avg_loss_usd, 2),
        "win_loss_ratio": round(win_loss_ratio, 2),
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "exit_breakdown": exit_counts,
        "trades": trades
    }


def format_backtest_cli_table(results: list) -> str:
    """Formats an institutional comparison table across multiple profiles."""
    lines = [
        "═" * 86,
        "  🏛️ INSTITUTIONAL MULTI-STRATEGY BACKTEST AUDIT (GOLD & BITCOIN)",
        "═" * 86,
        f"{'ASSET':<7} | {'STRATEGY':<8} | {'TRADES':<6} | {'WIN RATE':<9} | {'PF':<5} | {'NET PNL':<11} | {'MAX DD':<7} | {'SHARPE':<6}",
        "─" * 86
    ]

    for r in results:
        if "error" in r:
            lines.append(f"{r.get('asset', 'N/A'):<7} | ERROR: {r['error']}")
            continue
        pnl_str = f"${r['net_profit_usd']:+,.1f} ({r['net_return_pct']:+.1f}%)"
        wr_str = f"{r['win_rate_pct']:.1f}%"
        pf_str = f"{r['profit_factor']:.2f}"
        dd_str = f"{r['max_drawdown_pct']:.1f}%"
        sh_str = f"{r['sharpe_ratio']:.2f}"
        lines.append(
            f"{r['asset']:<7} | {r['strategy']:<8} | {r['total_trades']:<6} | {wr_str:<9} | {pf_str:<5} | {pnl_str:<11} | {dd_str:<7} | {sh_str:<6}"
        )

    lines.append("═" * 86)
    return "\n".join(lines)


def format_backtest_telegram_card(res: dict) -> str:
    """Formats a rich Markdown summary card for Telegram display."""
    if "error" in res:
        return f"❌ *Backtest Error:* {res['error']}"

    strat_info = STRATEGIES.get(res["strategy"], {})
    target_wr = strat_info.get("target_win_rate", "N/A")

    exits = res.get("exit_breakdown", {})
    tp1_hits = exits.get("TP1_TARGET", 0)
    tp2_hits = exits.get("TP2_EXTENDED", 0)
    be_hits = exits.get("BREAKEVEN", 0)
    trail_hits = exits.get("TRAILED_STOP", 0)
    sl_hits = exits.get("STOP_LOSS", 0)

    card = (
        f"📊 *INSTITUTIONAL BACKTEST REPORT: {res['asset']} ({res['strategy']})*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• Historical Period : `{res['lookback_days']} Days` (Daily Bars)\n"
        f"• Initial Capital   : `${res['initial_capital']:,.2f}`\n"
        f"• Final Equity      : `${res['final_capital']:,.2f}`\n"
        f"• Net Profit        : `${res['net_profit_usd']:+,.2f}` (`{res['net_return_pct']:+.2f}%`)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 *ACCURACY & EDGE:*\n"
        f"• Total Trades      : `{res['total_trades']}` (Wins: `{res['wins']}` | Losses: `{res['losses']}`)\n"
        f"• Win Rate          : *{res['win_rate_pct']}%* (Benchmark Target: `{target_wr}`)\n"
        f"• Profit Factor     : *{res['profit_factor']}x* (Institutional Edge > 1.80)\n"
        f"• Max Drawdown      : `{res['max_drawdown_pct']}%` (Circuit Breaker: 6.0%)\n"
        f"• Sharpe Ratio      : `{res['sharpe_ratio']}` | Sortino: `{res['sortino_ratio']}`\n"
        f"• Calmar Ratio      : `{res['calmar_ratio']}`\n"
        f"• Trade Expectancy  : `+{res['avg_trade_r']:.2f}R` (${res['expectancy_usd']:+,.2f} / trade)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛡️ *TRADE RESOLUTION BREAKDOWN:*\n"
        f"• Target 1 (TP1)    : `{tp1_hits}` trades\n"
        f"• Target 2 (TP2)    : `{tp2_hits}` trades\n"
        f"• Trailed Stop Locks: `{trail_hits}` trades\n"
        f"• Breakeven Exits   : `{be_hits}` trades (Zero Loss)\n"
        f"• Stop-Losses Hit   : `{sl_hits}` trades\n"
        f"• Max Win / Loss Run: `{res['max_win_streak']}W` / `{res['max_loss_streak']}L`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔒 *Execution Guardrail:* Only Score $\ge 8/10$ A+ setups permitted."
    )
    return card


def run_full_suite(lookback_days: int = 365, initial_capital: float = 10000.0) -> list:
    """Runs a full matrix backtest across all assets and strategies."""
    results = []
    print(f"\n[*] Launching Full Institutional Backtest Matrix ({lookback_days} Days Lookback)...")
    for asset in ("GOLD", "BTC"):
        for strat in ("SCALP", "SWING", "BALANCE", "SWAP"):
            print(f"  • Simulating {asset} - {strat} profile...")
            res = run_historical_backtest(asset=asset, strategy_code=strat, lookback_days=lookback_days, initial_capital=initial_capital)
            results.append(res)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Institutional Gold & BTC Backtest Engine")
    parser.add_argument("--asset", choices=["GOLD", "BTC", "BOTH"], default="BOTH", help="Target Asset")
    parser.add_argument("--strategy", choices=["SCALP", "SWING", "BALANCE", "SWAP", "ALL"], default="ALL", help="Strategy Profile")
    parser.add_argument("--days", type=int, default=365, help="Lookback Days")
    parser.add_argument("--capital", type=float, default=10000.0, help="Initial Capital USD")
    args = parser.parse_args()

    assets = ["GOLD", "BTC"] if args.asset == "BOTH" else [args.asset]
    strategies = ["SCALP", "SWING", "BALANCE", "SWAP"] if args.strategy == "ALL" else [args.strategy]

    matrix_results = []
    for a in assets:
        for s in strategies:
            print(f"[*] Running Backtest: {a} [{s}] ({args.days} days)...")
            r = run_historical_backtest(asset=a, strategy_code=s, lookback_days=args.days, initial_capital=args.capital)
            matrix_results.append(r)

    print("\n" + format_backtest_cli_table(matrix_results))
