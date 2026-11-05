"""
core/orchestrator.py
ONE BRAIN — Single decision point for tradingbot3 Precision Engine.

All trade decisions flow through here. Other modules are dumb services:
- autotrader_pipeline.py -> returns candidate setups only (no execution)
- mt5_executor.py -> executes commands only (no decisions)
- risk_engine.py -> calculates risk/lot sizes on request
- self_learning.py -> provides regime, confidence, learning on request
- institutional_engine.py -> provides HTF bias on request
- market_data.py -> provides market data on request

Decision flow:
  1. Pull fresh state from MT5 + SafetyManager
  2. Run all safety gates
  3. Get candidate setups from pipeline
  4. Apply regime + confidence scoring
  5. Decide: TRADE / SKIP / WAIT / MANAGE
  6. Execute via mt5_executor commands only
"""

import os
import sys
import time
import asyncio
import threading
from typing import Dict, Any, List, Optional, Tuple

try:
    from utils.logger import get_logger
    logger = get_logger("orchestrator")
except Exception:
    import logging
    logger = logging.getLogger("orchestrator")

from core.bot_state import bot_state
from core import gates
from core.lock import single_instance_lock

# Import existing service modules
try:
    from mt5_executor import MT5LiveBroker
except Exception:
    MT5LiveBroker = None

try:
    from autotrader_pipeline import analyze_asset_pipeline
except Exception:
    analyze_asset_pipeline = None

try:
    from risk_engine import (
        calculate_strategy_levels, calculate_lot_size,
        get_regime_risk_pct, safety_manager,
        calculate_structure_based_sl, calculate_smart_lot_by_confidence,
    )
except Exception:
    safety_manager = None
    calculate_strategy_levels = None
    calculate_lot_size = None
    get_regime_risk_pct = None
    calculate_structure_based_sl = None
    calculate_smart_lot_by_confidence = None

try:
    from self_learning import self_learning_engine
except Exception:
    self_learning_engine = None

try:
    from institutional_engine import compute_htf_bias, evaluate_htf_alignment
except Exception:
    compute_htf_bias = None
    evaluate_htf_alignment = None

try:
    from market_data import market_data_feed, MARKET_DATA_AVAILABLE
except Exception:
    market_data_feed = None
    MARKET_DATA_AVAILABLE = False

try:
    from config_validator import validate_config
except Exception:
    def validate_config(*args, **kwargs):
        return True, []

# Crash alerts + heartbeat wiring
try:
    from telegram_bot import send_crash_alert, heartbeat_monitor_worker, get_credentials
    TELEGRAM_AVAILABLE = True
except Exception:
    TELEGRAM_AVAILABLE = False
    def send_crash_alert(*args, **kwargs): pass
    def heartbeat_monitor_worker(*args, **kwargs): pass
    def get_credentials(*args, **kwargs): return "", ""


class Orchestrator:
    """
    Single decision engine for the tradingbot3 Precision Engine.

    State:
        IDLE - Not currently evaluating
        EVALUATING - Running decision cycle
        MANAGING - Managing existing positions (trailing, BE, partial TP)
        STOPPED - Kill switch active or fatal error
    """

    IDLE = "IDLE"
    EVALUATING = "EVALUATING"
    MANAGING = "MANAGING"
    STOPPED = "STOPPED"

    def __init__(self):
        self._lock = threading.RLock()
        self.state = self.IDLE
        self.broker: Optional[MT5LiveBroker] = None
        self.learning_engine = self_learning_engine
        self.running = False
        self.cycle_count = 0
        self.last_decision: Optional[Dict[str, Any]] = None
        self.trade_decisions: List[Dict[str, Any]] = []

        # Config from env with safe defaults
        self.trading_mode = os.environ.get("TRADING_MODE", "PAPER").upper()
        self.max_daily_loss_pct = float(os.environ.get("MAX_DAILY_LOSS_PCT", "1.5"))
        self.max_total_open_risk_pct = float(os.environ.get("MAX_TOTAL_OPEN_RISK_PCT", "2.5"))
        self.min_confluence_score = float(os.environ.get("MIN_CONFLUENCE_SCORE", "7.0"))
        self.limit_orders_enabled = os.environ.get("LIMIT_ORDERS_ENABLED", "true").lower() in ("true", "1", "yes")
        self.limit_order_offset_pips = float(os.environ.get("LIMIT_ORDER_OFFSET_PIPS", "2"))
        self.limit_order_expiry_min = int(os.environ.get("LIMIT_ORDER_EXPIRY_MIN", "35"))
        self.partial_tp_pct = float(os.environ.get("PARTIAL_TP_PCT", "50.0"))
        self.be_trigger_r = float(os.environ.get("BE_TRIGGER_R", "0.6"))
        self.trail_trigger_r = float(os.environ.get("TRAIL_TRIGGER_R", "1.0"))
        self.atr_trail_mult = float(os.environ.get("ATR_TRAIL_MULT", "1.0"))
        self.max_spread_pips = float(os.environ.get("MAX_SPREAD_PIPS", "30.0"))
        self.max_slippage_pips = float(os.environ.get("MAX_SLIPPAGE_PIPS", "3.0"))

    def initialize(self) -> Tuple[bool, str]:
        """Initialize the orchestrator and all service connections."""
        logger.info("Initializing One-Brain Precision Orchestrator...")

        # Single instance lock — prevent duplicate bot instances
        if not single_instance_lock.acquire(block=False):
            err_msg = "Another tradingbot3 instance is already running. Single-instance lock failed."
            logger.critical(err_msg)
            return False, err_msg

        # Validate config
        is_valid, errors = validate_config(fail_fast=False)
        if not is_valid:
            err_msg = "Config validation failed: " + "; ".join(errors)
            logger.error(err_msg)
            single_instance_lock.release()
            return False, err_msg

        # Initialize MT5 broker
        if MT5LiveBroker is not None:
            try:
                self.broker = MT5LiveBroker()
                ok, msg = self.broker.connect()
                if ok:
                    logger.info(f"MT5 broker connected: {msg[:80]}...")
                else:
                    logger.warning(f"MT5 broker connect failed: {msg}. Running in data-only mode.")
                    self.broker = None
            except Exception as e:
                logger.warning(f"MT5 broker init error: {e}. Running in data-only mode.")
                self.broker = None
        else:
            logger.warning("MetaTrader5 module not available. Data-only mode.")

        # Crash alert global excepthook
        if TELEGRAM_AVAILABLE:
            sys.excepthook = _bot_global_excepthook
            logger.info("Crash alert global excepthook installed.")

        # Start heartbeat worker thread
        if TELEGRAM_AVAILABLE:
            try:
                tok, cid = get_credentials()
                if tok and cid:
                    hb_thread = threading.Thread(
                        target=heartbeat_monitor_worker,
                        args=(tok, lambda: cid),
                        daemon=True,
                        name="heartbeat-monitor"
                    )
                    hb_thread.start()
                    logger.info("Heartbeat monitor worker started.")
            except Exception as e:
                logger.warning(f"Heartbeat worker start failed: {e}")

        # Sync initial state
        bot_state.refresh_from_mt5(self.broker)
        bot_state.refresh_from_safety_manager()

        # Force full position reconciliation on startup to prevent state drift
        if self.broker and self.broker.is_connected:
            try:
                mt5_positions = self.broker.get_open_positions()
                recon = bot_state.reconcile_positions(mt5_positions)
                if recon.get("drift_detected"):
                    logger.warning(
                        f"Startup position drift detected: MT5={recon['total_mt5']} vs Internal={recon['total_internal']}, "
                        f"missing_in_internal={len(recon['missing_in_internal'])}, missing_in_mt5={len(recon['missing_in_mt5'])}"
                    )
                else:
                    logger.info(f"Startup position reconciliation complete: {recon['matched_count']} positions matched.")
            except Exception as e:
                logger.warning(f"Startup position reconciliation error: {e}")

        self.state = self.IDLE
        self.running = True
        logger.info("Orchestrator initialized successfully.")
        return True, "Orchestrator initialized"

    def run_cycle(self) -> Dict[str, Any]:
        """
        Single decision cycle. Returns a dict with the full decision record.
        This is the main entry point — all trade decisions flow through here.
        """
        with self._lock:
            if not self.running:
                return {"decision": "STOPPED", "reason": "Orchestrator not running"}
            if self.state != self.IDLE:
                return {"decision": "BUSY", "reason": f"Orchestrator in {self.state} state"}

            self.state = self.EVALUATING
            self.cycle_count += 1
            cycle_record: Dict[str, Any] = {
                "cycle": self.cycle_count,
                "timestamp": time.time(),
                "datetime": time.strftime("%Y-%m-%d %H:%M:%S"),
                "decisions": [],
            }

            try:
                # Step 0: Manage existing positions (partial TP, breakeven, trailing)
                try:
                    mgmt_events = self.manage_positions()
                    mgmt_events = mgmt_events or []
                    cycle_record["position_management"] = mgmt_events
                    for ev in mgmt_events:
                        logger.info(f"MGMT: {ev.get('action')} #{ev.get('ticket')} {ev.get('symbol')} {ev.get('msg', '')[:80]}")
                except Exception as me:
                    logger.warning(f"Position management error: {me}")

                # Step 1: Pull fresh state
                bot_state.refresh_from_mt5(self.broker)
                bot_state.refresh_from_safety_manager()
                snapshot = bot_state.get_snapshot()
                cycle_record["state_snapshot"] = snapshot

                # Step 1b: Position reconciliation — sync MT5 positions with internal state
                try:
                    mt5_positions = self.broker.get_open_positions() if self.broker else []
                    recon_report = bot_state.reconcile_positions(mt5_positions)
                    cycle_record["position_reconciliation"] = recon_report
                    if not recon_report["reconciled"]:
                        logger.warning(
                            f"Position drift: MT5={recon_report['total_mt5']} vs Internal={recon_report['total_internal']}, "
                            f"missing_in_mt5={len(recon_report['missing_in_mt5'])}, "
                            f"missing_in_internal={len(recon_report['missing_in_internal'])}"
                        )
                        if recon_report["missing_in_internal"]:
                            # New positions on MT5 not tracked internally — flag for awareness
                            for p in recon_report["missing_in_internal"]:
                                logger.warning(f"Untracked MT5 position: #{p.get('ticket')} {p.get('symbol')} {p.get('type')}")
                except Exception as re:
                    logger.warning(f"Position reconciliation error: {re}")

                # Phase 7.3: Auto-sync closed MT5 trades to learning journal
                try:
                    if self_learning_engine and (self.broker or safety_manager):
                        synced = self_learning_engine.sync_all_closed_trades(
                            live_broker=self.broker,
                            safety_manager=safety_manager
                        )
                        if synced:
                            cycle_record["synced_closed_trades"] = len(synced)
                            logger.info(f"Synced {len(synced)} closed trades to learning journal")
                except Exception as se:
                    logger.warning(f"Closed-trade sync error: {se}")

                # Step 2: Check kill switch / daily loss / circuit breaker
                gates_results = self._run_safety_gates()
                cycle_record["gates"] = gates_results
                if not all(r["pass"] for r in gates_results):
                    failed = [r for r in gates_results if not r["pass"]]
                    reasons = "; ".join(r["reason"] for r in failed)
                    logger.warning(f"Cycle {self.cycle_count}: Gates blocked — {reasons}")
                    self.state = self.IDLE
                    cycle_record["decision"] = "BLOCKED"
                    cycle_record["block_reason"] = reasons
                    return cycle_record

                # Step 3: Get candidate setups from pipeline
                candidates = self._get_candidates()
                # Phase 4.5: Correlation guard — filter same-direction cross-asset duplicates
                candidates = self._filter_correlation_duplicates(candidates)
                cycle_record["candidates"] = candidates
                if not candidates:
                    logger.info(f"Cycle {self.cycle_count}: No actionable candidates")
                    self.state = self.IDLE
                    cycle_record["decision"] = "SKIP"
                    cycle_record["skip_reason"] = "No candidates"
                    return cycle_record

                # Step 4: Evaluate each candidate and decide
                for candidate in candidates:
                    decision = self._evaluate_candidate(candidate, snapshot)
                    cycle_record["decisions"].append(decision)

                    if decision["action"] in ("BUY", "SELL"):
                        # Execute through mt5_executor only
                        exec_result = self._execute_decision(decision)
                        decision["execution"] = exec_result
                        if exec_result.get("success"):
                            logger.info(f"EXECUTED: {decision['side']} {decision['asset']} @ ${decision['entry']:,.2f}")
                        else:
                            logger.warning(f"Execution rejected: {exec_result.get('error')}")

                self.last_decision = cycle_record["decisions"][-1] if cycle_record["decisions"] else None
                self.state = self.IDLE
                cycle_record["decision"] = "COMPLETED"
                return cycle_record

            except Exception as exc:
                logger.critical(f"Orchestrator cycle error: {exc}", exc_info=True)
                self.state = self.IDLE
                cycle_record["decision"] = "ERROR"
                cycle_record["error"] = str(exc)
                return cycle_record

    async def async_run_cycle(self) -> Dict[str, Any]:
        """
        Async decision cycle — runs safety gates and candidate gathering
        concurrently for reduced latency on scalping timeframes.
        """
        with self._lock:
            if not self.running:
                return {"decision": "STOPPED", "reason": "Orchestrator not running"}
            if self.state != self.IDLE:
                return {"decision": "BUSY", "reason": f"Orchestrator in {self.state} state"}

            self.state = self.EVALUATING
            self.cycle_count += 1
            cycle_record: Dict[str, Any] = {
                "cycle": self.cycle_count,
                "timestamp": time.time(),
                "datetime": time.strftime("%Y-%m-%d %H:%M:%S"),
                "decisions": [],
            }

        try:
            # Step 0: Manage existing positions (can run concurrently with gates)
            mgmt_events = await asyncio.to_thread(self.manage_positions)
            mgmt_events = mgmt_events or []
            cycle_record["position_management"] = mgmt_events

            # Step 1: Pull fresh state + run safety gates concurrently
            async def _refresh_and_gates():
                bot_state.refresh_from_mt5(self.broker)
                bot_state.refresh_from_safety_manager()
                snapshot = bot_state.get_snapshot()
                gates_results = self._run_safety_gates()
                return snapshot, gates_results

            # Step 2: Get candidates concurrently with state/gates
            async def _get_candidates_async():
                return self._get_candidates()

            # Run state refresh + gates AND candidate gathering in parallel
            (snapshot, gates_results), candidates = await asyncio.gather(
                _refresh_and_gates(),
                _get_candidates_async()
            )

            # Phase 4.5: Correlation guard — filter same-direction cross-asset duplicates
            candidates = self._filter_correlation_duplicates(candidates)

            # Phase 7.3: Auto-sync closed MT5 trades to learning journal
            try:
                if self_learning_engine and (self.broker or safety_manager):
                    synced = self_learning_engine.sync_all_closed_trades(
                        live_broker=self.broker,
                        safety_manager=safety_manager
                    )
                    if synced:
                        cycle_record["synced_closed_trades"] = len(synced)
                        logger.info(f"Synced {len(synced)} closed trades to learning journal")
            except Exception as se:
                logger.warning(f"Closed-trade sync error: {se}")

            cycle_record["state_snapshot"] = snapshot
            cycle_record["gates"] = gates_results
            cycle_record["candidates"] = candidates

            if not all(r["pass"] for r in gates_results):
                failed = [r for r in gates_results if not r["pass"]]
                reasons = "; ".join(r["reason"] for r in failed)
                logger.warning(f"Cycle {self.cycle_count}: Gates blocked — {reasons}")
                self.state = self.IDLE
                cycle_record["decision"] = "BLOCKED"
                cycle_record["block_reason"] = reasons
                return cycle_record

            if not candidates:
                logger.info(f"Cycle {self.cycle_count}: No actionable candidates")
                self.state = self.IDLE
                cycle_record["decision"] = "SKIP"
                cycle_record["skip_reason"] = "No candidates"
                return cycle_record

            # Step 4: Evaluate each candidate sequentially (evaluation is CPU-bound)
            for candidate in candidates:
                decision = await asyncio.to_thread(self._evaluate_candidate, candidate, snapshot)
                cycle_record["decisions"].append(decision)

                if decision["action"] in ("BUY", "SELL"):
                    exec_result = await asyncio.to_thread(self._execute_decision, decision)
                    decision["execution"] = exec_result
                    if exec_result.get("success"):
                        logger.info(f"EXECUTED: {decision['side']} {decision['asset']} @ ${decision['entry']:,.2f}")
                    else:
                        logger.warning(f"Execution rejected: {exec_result.get('error')}")

            self.last_decision = cycle_record["decisions"][-1] if cycle_record["decisions"] else None
            self.state = self.IDLE
            cycle_record["decision"] = "COMPLETED"
            return cycle_record

        except Exception as exc:
            logger.critical(f"Orchestrator async cycle error: {exc}", exc_info=True)
            self.state = self.IDLE
            cycle_record["decision"] = "ERROR"
            cycle_record["error"] = str(exc)
            return cycle_record

    def _run_safety_gates(self) -> List[Dict[str, Any]]:
        """Run all safety gates and return results."""
        results = []

        # Gate 1: Kill switch
        pass_k, reason_k = gates.check_kill_switch(bot_state)
        results.append({"gate": "kill_switch", "pass": pass_k, "reason": reason_k})

        # Gate 2: Daily loss
        pass_d, reason_d = gates.check_daily_loss(bot_state)
        results.append({"gate": "daily_loss", "pass": pass_d, "reason": reason_d})

        # Gate 3: Concurrent positions
        pass_c, reason_c = gates.check_concurrent_positions(bot_state)
        results.append({"gate": "concurrent_positions", "pass": pass_c, "reason": reason_c})

        return results

    def _run_candidate_gates(self, candidate: Dict[str, Any], snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Run per-candidate gates (toxic blacklist, confidence, SL/TP side, etc.)."""
        results = []
        asset = candidate.get("asset", "UNKNOWN")
        side = candidate.get("action", "STAND_ASIDE")
        score = float(candidate.get("score", 0))
        adaptive_score = float(candidate.get("adaptive_score", 0))
        confidence = max(score, adaptive_score)

        # Gate: Toxic blacklist (negative memory bank)
        market_vector = {
            "rsi": candidate.get("rsi", 50.0),
            "adx": candidate.get("adx", 25.0),
            "upper_wick_pct": candidate.get("upper_wick_pct", 0.0),
            "lower_wick_pct": candidate.get("lower_wick_pct", 0.0),
            "tnx_chg": candidate.get("tnx_chg", 0.0),
            "dxy_chg": candidate.get("dxy_chg", 0.0),
            "regime": candidate.get("regime", "TREND_EXPANSION"),
        }
        pass_t, reason_t = gates.check_toxic_blacklist(asset, side, market_vector)
        results.append({"gate": "toxic_blacklist", "pass": pass_t, "reason": reason_t})

        # Gate: Confidence threshold
        pass_cf, reason_cf = gates.check_confidence_threshold(confidence, self.min_confluence_score)
        results.append({"gate": "confidence_threshold", "pass": pass_cf, "reason": reason_cf})

        # Gate: SL/TP side
        entry = float(candidate.get("order_ticket", {}).get("entry", 0))
        sl = float(candidate.get("order_ticket", {}).get("stop_loss", 0))
        tp1 = float(candidate.get("order_ticket", {}).get("tp1", 0))
        pass_stp, reason_stp = gates.check_sl_tp_side(side, entry, sl, tp1)
        results.append({"gate": "sl_tp_side", "pass": pass_stp, "reason": reason_stp})

        # Gate: Risk cap
        proposed_risk = float(candidate.get("order_ticket", {}).get("risk_pct", 0.5))
        pass_r, reason_r = gates.check_risk_cap(bot_state, proposed_risk)
        results.append({"gate": "risk_cap", "pass": pass_r, "reason": reason_r})

        # Gate: Lot bounds
        lot_size = float(candidate.get("order_ticket", {}).get("lot_size", 0.01))
        pass_lb, reason_lb = gates.check_lot_bounds(lot_size)
        results.append({"gate": "lot_bounds", "pass": pass_lb, "reason": reason_lb})

        # Gate: Cooldown
        pass_co, reason_co = gates.check_cooldown(bot_state, asset)
        results.append({"gate": "cooldown", "pass": pass_co, "reason": reason_co})

        # Gate: Strategy Health Auto-Disable
        strategy = candidate.get("strategy", "SCALP")
        pass_sh, reason_sh = gates.check_strategy_health(strategy)
        results.append({"gate": "strategy_health", "pass": pass_sh, "reason": reason_sh})

        # Gate: Consecutive Loss Protection
        pass_cl, reason_cl, risk_mult = gates.check_consecutive_losses()
        results.append({"gate": "consecutive_losses", "pass": pass_cl, "reason": reason_cl})
        # Apply risk reduction multiplier to candidate's risk_pct
        if risk_mult < 1.0 and risk_mult > 0:
            current_risk = candidate.get("order_ticket", {}).get("risk_pct", 0.5)
            candidate["order_ticket"]["risk_pct"] = round(current_risk * risk_mult, 2)
            candidate["risk_reduction_applied"] = risk_mult

        # Gate: News window
        is_news_blocked = candidate.get("vetoed_by_news", False)
        news_msg = candidate.get("news_block_msg", "")
        pass_n, reason_n = gates.check_news_window(asset, is_news_blocked, news_msg)
        results.append({"gate": "news_window", "pass": pass_n, "reason": reason_n})

        # Gate: HTF Bias Alignment (No-Trade-on-Reversal)
        htf_bias = candidate.get("htf_bias", {"bias": "NEUTRAL", "asset": asset})
        confluence = max(score, adaptive_score)
        pass_h, reason_h = gates.check_htf_bias_alignment(htf_bias, side, confluence_score=confluence)
        results.append({"gate": "htf_bias_alignment", "pass": pass_h, "reason": reason_h})

        # Gate: Multi-Timeframe Alignment (1m analysis -> 5m decision -> 15m bias)
        pass_m, reason_m = gates.check_mtf_alignment(
            asset=asset, action=side, htf_bias=htf_bias,
            tf5_bias=candidate.get("tf5_bias", "NEUTRAL"),
            tf15_bias=candidate.get("tf15_bias", "NEUTRAL"),
            confluence_score=confluence
        )
        results.append({"gate": "mtf_alignment", "pass": pass_m, "reason": reason_m})

        # Gate: Spread-to-Risk Guard
        spread_val = float(candidate.get("spread", 0.0))
        sl_dist_val = float(candidate.get("order_ticket", {}).get("sl_dist", 0) or 0)
        if sl_dist_val <= 0:
            entry = float(candidate.get("order_ticket", {}).get("entry", 0))
            sl = float(candidate.get("order_ticket", {}).get("stop_loss", 0))
            if entry > 0 and sl > 0:
                sl_dist_val = abs(entry - sl)
        pass_sp, reason_sp = gates.check_spread(spread_val, asset, sl_dist=sl_dist_val)
        results.append({"gate": "spread_to_risk", "pass": pass_sp, "reason": reason_sp})

        # Gate: Per-Strategy Risk Decay
        strategy = candidate.get("strategy", "SCALP")
        pass_sr, reason_sr, sr_mult = gates.check_strategy_risk_decay(
            strategy, asset, sle=self_learning_engine, safety_manager=safety_manager
        )
        results.append({"gate": "strategy_risk_decay", "pass": pass_sr, "reason": reason_sr})
        if sr_mult < 1.0 and sr_mult > 0:
            current_risk = candidate.get("order_ticket", {}).get("risk_pct", 0.5)
            candidate["order_ticket"]["risk_pct"] = round(current_risk * sr_mult, 2)
            candidate["strategy_risk_reduction"] = sr_mult

        # Gate: Equity-Based Risk Decay (Daily Drawdown)
        pass_eq, reason_eq, eq_mult = gates.check_equity_risk_decay(safety_manager=safety_manager)
        results.append({"gate": "equity_risk_decay", "pass": pass_eq, "reason": reason_eq})
        if eq_mult < 1.0 and eq_mult > 0:
            current_risk = candidate.get("order_ticket", {}).get("risk_pct", 0.5)
            candidate["order_ticket"]["risk_pct"] = round(current_risk * eq_mult, 2)
            candidate["equity_risk_reduction"] = eq_mult

        return results

    def _get_candidates(self) -> List[Dict[str, Any]]:
        """Get candidate setups from autotrader_pipeline service."""
        candidates = []

        if analyze_asset_pipeline is None:
            logger.warning("autotrader_pipeline.analyze_asset_pipeline not available")
            return candidates

    def _filter_correlation_duplicates(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Phase 4.5: Correlation Guard — block concurrent GOLD+BTC same-direction entries.

        If both assets have candidates in the same direction, keep only the
        higher-scoring one to avoid double USD exposure.
        """
        if len(candidates) < 2:
            return candidates

        # Group by direction
        buys = [c for c in candidates if c.get("action", "").upper() == "BUY"]
        sells = [c for c in candidates if c.get("action", "").upper() == "SELL"]

        filtered = list(candidates)  # start with all

        for direction, group in (("BUY", buys), ("SELL", sells)):
            assets_in_group = [c.get("asset", "UNKNOWN") for c in group]
            if "GOLD" in assets_in_group and "BTC" in assets_in_group:
                # Both assets same direction — keep higher score, mark other for skip
                gold_c = [c for c in group if c.get("asset") == "GOLD"]
                btc_c = [c for c in group if c.get("asset") == "BTC"]
                if gold_c and btc_c:
                    g_score = max(gold_c[0].get("score", 0), gold_c[0].get("adaptive_score", 0))
                    b_score = max(btc_c[0].get("score", 0), btc_c[0].get("adaptive_score", 0))
                    if g_score >= b_score:
                        # Remove BTC candidate
                        for c in btc_c:
                            if c in filtered:
                                filtered.remove(c)
                                c["_correlation_blocked"] = True
                                c["_skip_reason"] = f"Correlation guard: GOLD {direction} has higher score ({g_score:.1f} vs {b_score:.1f})"
                    else:
                        # Remove GOLD candidate
                        for c in gold_c:
                            if c in filtered:
                                filtered.remove(c)
                                c["_correlation_blocked"] = True
                                c["_skip_reason"] = f"Correlation guard: BTC {direction} has higher score ({b_score:.1f} vs {g_score:.1f})"

        return filtered

    def _get_candidates(self) -> List[Dict[str, Any]]:
        """Get candidate setups from autotrader_pipeline service."""
        candidates = []

        if analyze_asset_pipeline is None:
            logger.warning("autotrader_pipeline.analyze_asset_pipeline not available")
            return candidates

        # Get macro data
        dxy_chg = 0.0
        tnx_chg = 0.0
        gsr = 80.0
        fg_val = 50

        if MARKET_DATA_AVAILABLE and market_data_feed:
            try:
                macro = market_data_feed.get_macro_snapshot()
                dxy_chg = float(macro.get("dxy_chg", 0.0))
                tnx_chg = float(macro.get("tnx_chg", 0.0))
                gsr = float(macro.get("gsr", 80.0))
                fg_val = int(macro.get("fg_val", 50))
            except Exception as e:
                logger.warning(f"Market data feed error: {e}")
        else:
            # Fallback: fetch directly via yfinance (same as pipeline does)
            try:
                import yfinance as yf
                dxy = yf.Ticker("DX-Y.NYB").history(period="5d")
                if not dxy.empty and len(dxy) >= 2:
                    dv = float(dxy["Close"].iloc[-1])
                    prev_dxy_close = float(dxy["Close"].iloc[-2])
                    dxy_chg = ((dv / prev_dxy_close) - 1) * 100 if prev_dxy_close != 0 else 0.0
                tnx = yf.Ticker("^TNX").history(period="5d")
                if not tnx.empty and len(tnx) >= 2:
                    tv = float(tnx["Close"].iloc[-1])
                    prev_tnx_close = float(tnx["Close"].iloc[-2])
                    tnx_chg = ((tv / prev_tnx_close) - 1) * 100 if prev_tnx_close != 0 else 0.0
                silver = yf.Ticker("SI=F").history(period="5d")
                gold_5d = yf.Ticker("GC=F").history(period="5d")
                if not gold_5d.empty and not silver.empty:
                    prev_silver_close = float(silver["Close"].iloc[-1])
                    gsr = float(gold_5d["Close"].iloc[-1] / prev_silver_close) if prev_silver_close != 0 else 75.0
            except Exception as e:
                logger.warning(f"Fallback macro fetch error: {e}")

        fg_val_str = "Neutral"
        try:
            from autotrader_pipeline import fetch_fear_greed
            fg_val, fg_val_str = fetch_fear_greed()
        except Exception:
            pass

        # Analyze both assets across all strategies (SCALP, SWING, BALANCE, SWAP)
        STRATEGIES = ["SCALP", "SWING", "BALANCE", "SWAP"]

        # Pre-compute HTF bias per asset (D1/H1) for reversal veto
        htf_bias_cache: Dict[str, Dict[str, Any]] = {}
        if compute_htf_bias is not None:
            try:
                import yfinance as yf
                import pandas as pd
                for symbol, asset_type in [("BTC-USD", "BTC"), ("GC=F", "GOLD")]:
                    try:
                        # Fetch D1 candles for HTF bias
                        df_d1 = yf.Ticker(symbol).history(period="6mo", interval="1d")
                        if not df_d1.empty and len(df_d1) >= 30:
                            df_d1.columns = [c.title() for c in df_d1.columns]
                            htf_bias_cache[asset_type] = compute_htf_bias(df_d1, asset_type)
                        else:
                            htf_bias_cache[asset_type] = {"bias": "NEUTRAL", "asset": asset_type}
                    except Exception as e:
                        logger.warning(f"HTF bias fetch failed for {asset_type}: {e}")
                        htf_bias_cache[asset_type] = {"bias": "NEUTRAL", "asset": asset_type}
            except Exception as e:
                logger.warning(f"HTF bias pre-computation failed: {e}")

        for symbol, asset_type in [("BTC-USD", "BTC"), ("GC=F", "GOLD")]:
            htf_bias = htf_bias_cache.get(asset_type, {"bias": "NEUTRAL", "asset": asset_type})
            for strategy in STRATEGIES:
                try:
                    res = analyze_asset_pipeline(symbol, asset_type, dxy_chg, tnx_chg, gsr, fg_val, strategy=strategy)
                    if res and res.get("action") not in ("STAND_ASIDE", None):
                        # Attach HTF bias to candidate for reversal veto gates
                        res["htf_bias"] = htf_bias
                        candidates.append(res)
                except Exception as e:
                    logger.warning(f"Pipeline analysis failed for {asset_type} {strategy}: {e}")

        return candidates

    def _evaluate_candidate(self, candidate: Dict[str, Any], snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate a single candidate and produce a decision."""
        asset = candidate.get("asset", "UNKNOWN")
        side = candidate.get("action", "STAND_ASIDE")
        score = float(candidate.get("score", 0))
        adaptive_score = float(candidate.get("adaptive_score", 0))
        regime = candidate.get("regime", "TREND_EXPANSION")
        regime_risk_pct = float(candidate.get("regime_risk_pct", 0.5))
        order_ticket = candidate.get("order_ticket", {})
        active_features = candidate.get("active_features", {})

        decision: Dict[str, Any] = {
            "asset": asset,
            "symbol": candidate.get("symbol", ""),
            "side": side,
            "entry": float(order_ticket.get("entry", 0)),
            "stop_loss": float(order_ticket.get("stop_loss", 0)),
            "tp1": float(order_ticket.get("tp1", 0)),
            "tp2": float(order_ticket.get("tp2", 0)),
            "score": score,
            "adaptive_score": adaptive_score,
            "regime": regime,
            "regime_risk_pct": regime_risk_pct,
            "order_type": order_ticket.get("order_type", "MARKET"),
            "order_ticket": order_ticket,
            "factors": candidate.get("factors", []),
            "action": "SKIP",
            "reason": "",
            "gates": [],
        }

        # Gate: confidence threshold (uses combined score)
        pass_s, reason_s = gates.check_confidence_threshold(max(score, adaptive_score), self.min_confluence_score)
        decision["gates"].append({"gate": "confidence_threshold", "pass": pass_s, "reason": reason_s})

        # Run all remaining candidate gates
        candidate_gates = self._run_candidate_gates(candidate, snapshot)
        decision["gates"].extend(candidate_gates)

        all_pass = all(g["pass"] for g in decision["gates"])
        if not all_pass:
            failed = [g for g in decision["gates"] if not g["pass"]]
            decision["action"] = "SKIP"
            decision["reason"] = "; ".join(g["reason"] for g in failed)
            logger.info(f"Candidate {asset} {side} blocked: {decision['reason']}")
            return decision

        # All gates passed — decision is TRADE
        decision["action"] = side
        decision["reason"] = "All gates passed"
        decision["regime"] = regime
        decision["applied_risk_pct"] = regime_risk_pct

        # Enhancement: Structure-Based SL + Smart Lot Sizing by Confidence
        try:
            entry = float(order_ticket.get("entry", 0))
            sl = float(order_ticket.get("stop_loss", 0))
            tp1 = float(order_ticket.get("tp1", 0))
            confidence = max(score, adaptive_score)

            # Extract swing levels from candidate/order_ticket if available
            swing_high = float(order_ticket.get("swing_high", 0) or candidate.get("swing_high", 0))
            swing_low = float(order_ticket.get("swing_low", 0) or candidate.get("swing_low", 0))
            atr = float(order_ticket.get("atr", 0) or candidate.get("atr", 0) or 0)

            if swing_high > 0 or swing_low > 0:
                sl_result = calculate_structure_based_sl(
                    asset=asset, current_price=entry, action=side,
                    swing_high=swing_high, swing_low=swing_low, atr=atr
                )
                if sl_result.get("sl_type") == "structure" and sl_result.get("stop_loss"):
                    decision["stop_loss"] = sl_result["stop_loss"]
                    decision["sl_dist"] = sl_result["sl_dist"]
                    decision["sl_type"] = "structure"
                    logger.info(f"Structure-based SL applied: ${sl_result['stop_loss']:,.2f} (dist={sl_result['sl_dist']})")
                else:
                    decision["sl_type"] = "fallback_atr"
            else:
                decision["sl_type"] = "fallback_atr"

            # Smart lot sizing by confidence
            account_balance = float(bot_state.equity or snapshot.get("equity", 10000.0))
            max_risk_pct = float(os.environ.get("MAX_RISK_PCT_PER_TRADE", "1.0"))
            lot_result = calculate_smart_lot_by_confidence(
                asset=asset, entry_price=entry, stop_loss_price=decision["stop_loss"],
                confidence_score=confidence, account_balance=account_balance,
                max_risk_pct=max_risk_pct, regime_risk_pct=regime_risk_pct
            )
            if not lot_result.get("skip", False):
                decision["lot_size"] = lot_result["lots"]
                decision["risk_pct"] = lot_result["risk_pct"]
                decision["risk_usd"] = lot_result["risk_usd"]
                decision["confidence_score"] = confidence
                order_ticket["lot_size"] = lot_result["lots"]
                order_ticket["risk_pct"] = lot_result["risk_pct"]
                logger.info(f"Smart lot sizing: {lot_result['lots']} lots @ {lot_result['risk_pct']:.2f}% risk (confidence={confidence:.1f})")
            else:
                decision["action"] = "SKIP"
                decision["reason"] = lot_result.get("skip_reason", "Confidence too low")
                logger.info(f"Candidate {asset} {side} skipped: {decision['reason']}")
                return decision
        except Exception as e:
            logger.warning(f"Enhancement (structure SL / smart lot) failed: {e}")
            decision["sl_type"] = "fallback_atr"

        logger.info(f"Candidate {asset} {side} APPROVED (score={score:.1f}, regime={regime}, risk={regime_risk_pct:.2f}%)")
        return decision

    def _execute_decision(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a trade decision through mt5_executor only."""
        asset = decision["asset"]
        side = decision["side"]
        entry = decision["entry"]
        sl = decision["stop_loss"]
        tp1 = decision["tp1"]
        tp2 = decision["tp2"]
        lot_size = float(decision.get("order_ticket", {}).get("lot_size", 0.01))
        order_type = decision.get("order_type", "MARKET")
        limit_price = float(decision.get("order_ticket", {}).get("limit_price", entry))
        zone = decision.get("order_ticket", {}).get("zone")
        expiry_min = int(decision.get("order_ticket", {}).get("expiry_minutes", self.limit_order_expiry_min))

        if self.broker is None:
            return {"success": False, "error": "MT5 broker not connected"}

        try:
            if order_type == "LIMIT" and self.limit_orders_enabled:
                result = self.broker.execute_live_limit_order(
                    asset=asset,
                    action=side,
                    limit_price=limit_price,
                    stop_loss=sl,
                    take_profit=tp1,
                    lot_size=lot_size,
                    zone=zone,
                    expiry_minutes=expiry_min,
                    comment="Orchestrator-Limit",
                )
            else:
                result = self.broker.execute_live_sniper_order(
                    asset=asset,
                    action=side,
                    entry_price=entry,
                    stop_loss=sl,
                    take_profit=tp1,
                    lot_size=lot_size,
                    comment="Orchestrator-Market",
                )
            return result
        except Exception as exc:
            logger.error(f"Execution error for {asset} {side}: {exc}")
            return {"success": False, "error": str(exc)}

    def _get_current_prices(self) -> Dict[str, float]:
        """Fetch live prices for GOLD and BTC from market data feed or yfinance fallback."""
        prices: Dict[str, float] = {}
        try:
            if market_data_feed:
                try:
                    g = market_data_feed.get_live_price("GOLD")
                    if g and g.get("price", 0) > 0:
                        prices["GOLD"] = float(g["price"])
                except Exception:
                    pass
                try:
                    b = market_data_feed.get_live_price("BTC")
                    if b and b.get("price", 0) > 0:
                        prices["BTC"] = float(b["price"])
                except Exception:
                    pass
        except Exception:
            pass

        # yfinance fallback
        if not prices:
            try:
                import yfinance as yf
                if "GOLD" not in prices:
                    g = yf.Ticker("GC=F").history(period="1d", interval="1m")
                    if not g.empty:
                        prices["GOLD"] = float(g["Close"].iloc[-1])
                if "BTC" not in prices:
                    b = yf.Ticker("BTC-USD").history(period="1d", interval="1m")
                    if not b.empty:
                        prices["BTC"] = float(b["Close"].iloc[-1])
            except Exception:
                pass

        return prices

    def manage_positions(self) -> List[Dict[str, Any]]:
        """Manage existing positions: trailing stops, breakeven, partial TP.

        Runs for BOTH live MT5 and Paper modes. When MT5 is disconnected,
        paper positions are still managed via safety_manager so trailing/BE/TP
        never stop working.
        """
        self.state = self.MANAGING
        try:
            if self.broker is not None and self.broker.is_connected:
                events = self.broker.trail_positions(default_strategy="SCALP")
            else:
                # MT5 not connected — manage paper positions only
                current_prices = self._get_current_prices()
                if safety_manager and current_prices:
                    events = safety_manager.trail_paper_positions(
                        current_prices, default_strategy="SCALP"
                    ) or []
                else:
                    events = []
            self.state = self.IDLE
            return events or []
        except Exception as exc:
            logger.error(f"Position management error: {exc}")
            self.state = self.IDLE
            return []

    def stop(self) -> None:
        """Stop the orchestrator."""
        self.running = False
        self.state = self.STOPPED
        single_instance_lock.release()
        logger.info("Orchestrator stopped and lock released")


def _bot_global_excepthook(exctype, value, tb):
    """Global unhandled exception hook — dispatches crash alert via Telegram."""
    import traceback
    tb_str = "".join(traceback.format_exception(exctype, value, tb))
    logger.critical(f"Unhandled exception caught by global hook: {value}", exc_info=(exctype, value, tb))
    if TELEGRAM_AVAILABLE:
        send_crash_alert(value, context="Orchestrator Global Unhandled Exception", tb_str=tb_str)
    sys.__excepthook__(exctype, value, tb)


# Singleton instance
orchestrator = Orchestrator()
