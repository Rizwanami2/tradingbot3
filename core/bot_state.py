"""
core/bot_state.py
Single source of truth for tradingbot3 runtime state.

Aggregates:
  - risk_engine.SafetyManager (paper/live mode, kill switch, daily PnL, cooldowns)
  - mt5_executor.MT5LiveBroker (live equity, free margin, open positions)

No trade decisions are made here — only state aggregation and access.
"""

import os
import time
import threading
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

try:
    from utils.logger import get_logger
    logger = get_logger("bot_state")
except Exception:
    import logging
    logger = logging.getLogger("bot_state")

try:
    from risk_engine import safety_manager, DEFAULT_ACCOUNT_BALANCE
except Exception:
    safety_manager = None
    DEFAULT_ACCOUNT_BALANCE = 10_000.0

try:
    from mt5_executor import MT5LiveBroker
except Exception:
    MT5LiveBroker = None


class BotState:
    """
    Thread-safe runtime state container.

    Attributes:
        equity: Current account equity (fresh from MT5 or paper)
        free_margin: Current free margin
        balance: Account balance
        margin_level: Margin level percentage
        open_positions: List of open position dicts
        open_positions_count: Number of open positions
        daily_pnl: Realized daily PnL
        starting_daily_equity: Equity at start of trading day
        regime: Current market regime string
        kill_switch_active: Whether emergency kill switch is active
        kill_switch_reason: Reason for kill switch
        cooldowns: Dict of asset -> cooldown_until timestamp
        trading_mode: PAPER/DEMO/LIVE
        max_daily_loss_pct: Daily loss limit percentage
        max_total_open_risk_pct: Max combined open risk percentage
        last_update_ts: Last state refresh timestamp
    """

    def __init__(self):
        self._lock = threading.RLock()
        self.equity = DEFAULT_ACCOUNT_BALANCE
        self.free_margin = DEFAULT_ACCOUNT_BALANCE * 0.95
        self.balance = DEFAULT_ACCOUNT_BALANCE
        self.margin_level = 1000.0
        self.open_positions: List[Dict[str, Any]] = []
        self.open_positions_count = 0
        self.daily_pnl = 0.0
        self.starting_daily_equity = DEFAULT_ACCOUNT_BALANCE
        self.regime = "TREND_EXPANSION"
        self.kill_switch_active = False
        self.kill_switch_reason = ""
        self.cooldowns: Dict[str, float] = {}  # asset -> cooldown_until epoch
        self.trading_mode = "PAPER"
        self.max_daily_loss_pct = 1.5
        self.max_total_open_risk_pct = 2.5
        self.consecutive_losses = 0
        self.daily_circuit_breaker_tripped = False
        self.last_update_ts = 0.0
        self._mt5_broker = None

    @property
    def last_update_age_seconds(self) -> float:
        return time.time() - self.last_update_ts if self.last_update_ts > 0 else float("inf")

    def refresh_from_mt5(self, broker: Optional[MT5LiveBroker] = None) -> bool:
        """Pull fresh account data from MT5. Returns True on success."""
        if broker is None and MT5LiveBroker is not None:
            broker = MT5LiveBroker()
        if broker is None:
            logger.warning("MT5 broker not available for state refresh")
            return False

        try:
            data = broker.get_live_account_data()
            if data is None:
                return False

            with self._lock:
                self.equity = float(data.get("equity", self.equity))
                self.free_margin = float(data.get("margin_free", self.free_margin))
                self.balance = float(data.get("balance", self.balance))
                self.margin_level = float(data.get("margin_level", self.margin_level))
                self.open_positions = data.get("positions", [])
                self.open_positions_count = int(data.get("open_positions_count", len(self.open_positions)))
                self.last_update_ts = time.time()
                self.trading_mode = safety_manager.get_trading_mode() if safety_manager else "PAPER"

            # Sync safety manager state
            if safety_manager:
                with self._lock:
                    self.kill_switch_active, self.kill_switch_reason = safety_manager.is_kill_switch_active()
                    self.max_daily_loss_pct = float(os.environ.get("MAX_DAILY_LOSS_PCT", "1.5"))
                    self.max_total_open_risk_pct = float(os.environ.get("MAX_TOTAL_OPEN_RISK_PCT", "2.5"))
                    sm_state = safety_manager.state
                    self.daily_pnl = float(sm_state.get("realized_daily_pnl", 0.0))
                    self.starting_daily_equity = float(sm_state.get("starting_daily_equity", DEFAULT_ACCOUNT_BALANCE))
                    self.consecutive_losses = int(sm_state.get("consecutive_losses", 0))
                    self.daily_circuit_breaker_tripped = bool(sm_state.get("daily_circuit_breaker_tripped", False))
                    sm_kill, sm_reason = safety_manager.is_kill_switch_active()
                    self.kill_switch_active = sm_kill
                    self.kill_switch_reason = sm_reason

            return True
        except Exception as e:
            logger.error(f"Failed to refresh state from MT5: {e}")
            return False

    def refresh_from_safety_manager(self) -> None:
        """Sync state from risk_engine.SafetyManager without MT5."""
        if safety_manager is None:
            return
        try:
            with self._lock:
                self.trading_mode = safety_manager.get_trading_mode()
                self.kill_switch_active, self.kill_switch_reason = safety_manager.is_kill_switch_active()
                sm_state = safety_manager.state
                self.daily_pnl = float(sm_state.get("realized_daily_pnl", 0.0))
                self.starting_daily_equity = float(sm_state.get("starting_daily_equity", DEFAULT_ACCOUNT_BALANCE))
                self.consecutive_losses = int(sm_state.get("consecutive_losses", 0))
                self.daily_circuit_breaker_tripped = bool(sm_state.get("daily_circuit_breaker_tripped", False))
                self.max_daily_loss_pct = float(os.environ.get("MAX_DAILY_LOSS_PCT", "1.5"))
                self.max_total_open_risk_pct = float(os.environ.get("MAX_TOTAL_OPEN_RISK_PCT", "2.5"))
                self.last_update_ts = time.time()
        except Exception as e:
            logger.error(f"Failed to sync state from safety manager: {e}")

    def is_cooldown_active(self, asset: str) -> bool:
        """Check if asset is in cooldown period."""
        until = self.cooldowns.get(asset, 0.0)
        return until > time.time()

    def set_cooldown(self, asset: str, seconds: float) -> None:
        """Set cooldown for an asset."""
        with self._lock:
            self.cooldowns[asset] = time.time() + seconds

    def get_snapshot(self) -> Dict[str, Any]:
        """Return a thread-safe snapshot of current state."""
        with self._lock:
            return {
                "equity": self.equity,
                "free_margin": self.free_margin,
                "balance": self.balance,
                "margin_level": self.margin_level,
                "open_positions": list(self.open_positions),
                "open_positions_count": self.open_positions_count,
                "daily_pnl": self.daily_pnl,
                "starting_daily_equity": self.starting_daily_equity,
                "regime": self.regime,
                "kill_switch_active": self.kill_switch_active,
                "kill_switch_reason": self.kill_switch_reason,
                "cooldowns": dict(self.cooldowns),
                "trading_mode": self.trading_mode,
                "max_daily_loss_pct": self.max_daily_loss_pct,
                "max_total_open_risk_pct": self.max_total_open_risk_pct,
                "consecutive_losses": self.consecutive_losses,
                "daily_circuit_breaker_tripped": self.daily_circuit_breaker_tripped,
                "last_update_ts": self.last_update_ts,
                "last_update_age_seconds": self.last_update_age_seconds,
            }

    def reconcile_positions(self, mt5_positions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Reconcile MT5 live positions with internal state.
        Detects drift (missing/extra positions) and returns a report.
        Does NOT modify state — returns reconciliation report for orchestrator to act on.
        """
        internal = {str(p.get("ticket")): p for p in self.open_positions}
        external = {str(p.get("ticket")): p for p in mt5_positions}

        internal_tickets = set(internal.keys())
        external_tickets = set(external.keys())

        missing_in_internal = external_tickets - internal_tickets  # MT5 has, we don't
        missing_in_mt5 = internal_tickets - external_tickets       # we have, MT5 doesn't
        matched = internal_tickets & external_tickets

        drift_detected = len(missing_in_internal) > 0 or len(missing_in_mt5) > 0

        report = {
            "reconciled": not drift_detected,
            "drift_detected": drift_detected,
            "matched_count": len(matched),
            "missing_in_internal": [external[t] for t in missing_in_internal],
            "missing_in_mt5": [internal[t] for t in missing_in_mt5],
            "matched_positions": [internal[t] for t in matched],
            "total_mt5": len(external),
            "total_internal": len(internal),
        }

        if drift_detected:
            logger.warning(
                f"Position drift detected: MT5={len(external)} vs Internal={len(internal)}, "
                f"missing_in_internal={len(missing_in_internal)}, missing_in_mt5={len(missing_in_mt5)}"
            )

        return report


# Singleton instance
bot_state = BotState()
