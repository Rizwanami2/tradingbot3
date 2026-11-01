#!/usr/bin/env python3
"""
run_bot.py — Continuous unattended runner for tradingbot3 Precision Engine.
Designed for VPS deployment. Loops Orchestrator.run_cycle() with a configurable
interval until manually stopped. Enforces single-instance lock and safety gates
on every cycle.

Usage:
    python run_bot.py                    # Runs indefinitely (Ctrl+C to stop)
    python run_bot.py --once             # Runs one cycle then exits
    python run_bot.py --interval 30      # Runs every 30 seconds

Environment (.env):
    TRADING_MODE=live                   # REQUIRED for live capital execution
    LIVE_CONFIRM=CONFIRM                # REQUIRED if TRADING_MODE=live (double-confirm guard)
    MT5_LOGIN / MT5_PASSWORD / MT5_SERVER  # MT5 broker credentials (if not already logged in terminal)
    MAX_DAILY_LOSS_PCT=1.5              # Daily drawdown kill-switch
    MAX_TOTAL_OPEN_RISK_PCT=2.5         # Portfolio risk cap
    ... see .env.example for all options
"""

import os
import sys
import time
import signal
import argparse
import threading

# Ensure project root on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from utils.logger import get_logger
    logger = get_logger("run_bot")
except Exception:
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logger = logging.getLogger("run_bot")

try:
    from config_validator import validate_config, load_env_file
except Exception:
    def validate_config(fail_fast=False):
        return True, []
    def load_env_file():
        pass

try:
    from core.orchestrator import orchestrator
except Exception as exc:
    logger.critical(f"Failed to import orchestrator: {exc}")
    sys.exit(1)

try:
    from core.lock import single_instance_lock
except Exception:
    single_instance_lock = None

# ── Graceful Shutdown ──────────────────────────────────────────────────────
_stop_requested = threading.Event()


def _signal_handler(signum, frame):
    logger.info(f"Received signal {signum}. Shutting down gracefully...")
    _stop_requested.set()


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)

# ── Main ───────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="tradingbot3 Precision Engine Runner")
    parser.add_argument("--once", action="store_true", help="Run one cycle then exit")
    parser.add_argument("--interval", type=float, default=60.0, help="Seconds between cycles (default: 60)")
    parser.add_argument("--dry-run", action="store_true", help="Validate config only, do not trade")
    args = parser.parse_args()

    # Load .env
    load_env_file()

    # Validate configuration
    is_valid, errors = validate_config(fail_fast=False)
    if not is_valid:
        logger.critical("Configuration validation failed:")
        for e in errors:
            logger.critical(f"  • {e}")
        sys.exit(1)

    logger.info("Configuration validated successfully.")

    trading_mode = os.environ.get("TRADING_MODE", "PAPER").upper()
    if trading_mode == "LIVE":
        live_confirm = os.environ.get("LIVE_CONFIRM", "").strip().upper()
        if live_confirm != "CONFIRM":
            logger.critical("LIVE mode requires LIVE_CONFIRM=CONFIRM in .env. Aborting for safety.")
            sys.exit(1)
        logger.warning("⚠️  LIVE CAPITAL MODE ENABLED — Real orders will be sent to MT5.")

    # Acquire single-instance lock
    if single_instance_lock:
        if not single_instance_lock.acquire(block=False):
            logger.critical("Another tradingbot3 instance is already running. Exiting.")
            sys.exit(1)

    # Initialize orchestrator
    ok, msg = orchestrator.initialize()
    if not ok:
        logger.critical(f"Orchestrator initialization failed: {msg}")
        single_instance_lock.release()
        sys.exit(1)
    logger.info(f"Orchestrator initialized: {msg}")

    if args.dry_run:
        logger.info("Dry-run complete. Configuration and orchestrator are valid.")
        orchestrator.stop()
        return

    # ── Run Loop ─────────────────────────────────────────────────────────
    cycle_count = 0
    logger.info(f"Starting Precision Engine loop (interval={args.interval}s, mode={trading_mode})...")

    try:
        while not _stop_requested.is_set():
            cycle_count += 1
            try:
                result = orchestrator.run_cycle()
                decision = result.get("decision", "UNKNOWN")
                logger.info(f"Cycle #{cycle_count}: decision={decision}")

                # Log any executed orders
                for dec in result.get("decisions", []):
                    if dec.get("action") in ("BUY", "SELL"):
                        exec_result = dec.get("execution", {})
                        if exec_result.get("success"):
                            logger.info(
                                f"  ✅ EXECUTED: {dec['side']} {dec['asset']} "
                                f"@ ${dec['entry']:,.2f} (SL: ${dec['stop_loss']:,.2f}, "
                                f"TP1: ${dec['tp1']:,.2f}, Risk: {dec.get('risk_pct', 0):.2f}%)"
                            )
                        else:
                            logger.warning(
                                f"  ❌ Execution rejected: {dec['side']} {dec['asset']} — "
                                f"{exec_result.get('error', 'unknown error')}"
                            )

                # Log position management events
                for ev in result.get("position_management", []):
                    logger.info(f"  🛠 MGMT: {ev.get('action')} #{ev.get('ticket')} {ev.get('symbol')}")

                # Log reconciliation drift
                recon = result.get("position_reconciliation", {})
                if recon and not recon.get("reconciled", True):
                    logger.warning(
                        f"  ⚠ Position drift: MT5={recon.get('total_mt5')} vs Internal={recon.get('total_internal')}"
                    )

            except Exception as exc:
                logger.error(f"Cycle #{cycle_count} error: {exc}", exc_info=True)

            if args.once:
                break

            # Wait for next cycle (respects stop signal)
            _stop_requested.wait(args.interval)

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received.")
    finally:
        orchestrator.stop()
        logger.info("Precision Engine stopped gracefully.")


if __name__ == "__main__":
    main()
