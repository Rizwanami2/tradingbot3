"""
Dependency Injection Container for tradingbot3.

Provides a central container that holds application singletons so they can be
injected (or overridden for testing) instead of being imported as bare module
globals. Usage:

    from core.container import container
    sm = container.safety_manager
    broker = container.live_broker

To override for tests:

    container.safety_manager = MockSafetyManager()
"""
from __future__ import annotations

import threading
from typing import Any, Optional, Dict


class DIContainer:
    """Thread-safe dependency injection container."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._instances: Dict[str, Any] = {}

    def register(self, name: str, instance: Any) -> None:
        with self._lock:
            self._instances[name] = instance

    def get(self, name: str, default: Optional[Any] = None) -> Optional[Any]:
        with self._lock:
            return self._instances.get(name, default)

    def set(self, name: str, instance: Any) -> None:
        """Override a dependency (useful for testing/mocking)."""
        with self._lock:
            self._instances[name] = instance

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self._instances

    def reset(self) -> None:
        with self._lock:
            self._instances.clear()


# Global container instance
container = DIContainer()


def wire_defaults() -> None:
    """Wire default singleton instances into the container."""
    from risk_engine import safety_manager as _sm
    from mt5_executor import live_broker as _broker
    from self_learning import learning_engine as _learner
    from core.bot_state import bot_state as _bot_state
    from market_data import market_data_feed as _market_data
    from institutional_engine import (
        neuro_predictor as _neuro,
        omniscient_matrix as _omniscient,
    )

    container.register("safety_manager", _sm)
    container.register("live_broker", _broker)
    container.register("learning_engine", _learner)
    container.register("bot_state", _bot_state)
    container.register("market_data", _market_data)
    container.register("neuro_predictor", _neuro)
    container.register("omniscient_matrix", _omniscient)
