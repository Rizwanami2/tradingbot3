#!/usr/bin/env python3
"""
trader-gold-btc: mt5_telegram_bot.py
Clean & Classic MetaTrader 5 & Telegram Remote Control Execution Engine.
Direct forwarder to production dual-slot engine in telegram_bot.py.
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from telegram_bot import start_bot

if __name__ == "__main__":
    start_bot()
