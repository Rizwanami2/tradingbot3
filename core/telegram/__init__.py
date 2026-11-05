"""
Telegram Bot Extracted Modules

Provides modular, testable components extracted from the telegram_bot.py god object.
"""
from .stats import (
    compute_live_stats,
    format_stats_dashboard,
    inject_dependencies,
    STATS_CACHE,
)

__all__ = [
    "compute_live_stats",
    "format_stats_dashboard",
    "inject_dependencies",
    "STATS_CACHE",
]
