#!/usr/bin/env bash
# ==============================================================================
# Linux VPS & Wine Update Script for tradingbot3
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=================================================================="
echo "  🚀 Updating tradingbot3 on Linux VPS (Native venv & Wine)"
echo "=================================================================="

echo "[*] Pulling latest updates from GitHub..."
git pull origin main

# 1. Update Native Linux Python (Paper Trading / Scanner / Telegram)
if [ -d "venv" ]; then
    echo "[*] Updating Linux venv dependencies..."
    ./venv/bin/python3 -m pip install -r requirements.txt
    ./venv/bin/python3 test_suite.py
elif command -v python3 &> /dev/null; then
    echo "[*] Updating system python3 packages..."
    python3 -m pip install -r requirements.txt
    python3 test_suite.py
fi

# 2. Update Wine Windows Python (if MT5 Live Broker is used under Wine)
if command -v wine &> /dev/null; then
    echo "[*] Wine detected. Checking Wine Python environment..."
    if wine python --version &> /dev/null; then
        echo "[*] Updating Wine Python packages..."
        wine python -m pip install -r requirements.txt
    fi
fi

echo "=================================================================="
echo "  ✅ Update complete! To run:"
echo "     Native / Paper Mode : ./venv/bin/python3 telegram_bot.py"
echo "     Wine / MT5 Live Mode: wine python telegram_bot.py"
echo "=================================================================="
