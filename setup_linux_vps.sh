#!/usr/bin/env bash
# ==============================================================================
# Complete Fresh Setup Script for Linux VPS (Ubuntu / Debian)
# Supports:
#   1. Native Linux Python (Paper Trading, Scanners, Telegram Bot, Web Feeds)
#   2. Wine + MT5 Windows Environment (Live MetaTrader 5 Broker on Linux)
#   3. Systemd 24/7 background service with auto-restart
# ==============================================================================
set -e

echo "=================================================================="
echo "  🚀 Fully Automated Linux VPS Setup for tradingbot3"
echo "=================================================================="

# 1. Update OS Packages
echo "[*] Updating system packages..."
sudo apt-get update -y
sudo apt-get install -y git curl wget build-essential python3 python3-pip python3-venv xvfb screen

# 2. Setup Native Linux Python Environment
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "[*] Creating native Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

echo "[*] Installing Python packages in venv..."
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

# 3. Configure .env
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "    ✅ Created .env from .env.example"
        echo "    ⚠️ Please configure TELEGRAM_BOT_TOKEN and credentials in .env"
    fi
fi

# 4. Optional Wine Setup for MetaTrader 5 (if user chooses)
echo ""
echo "------------------------------------------------------------------"
echo "Do you want to install Wine & MetaTrader 5 on this Linux VPS? (y/n)"
echo "------------------------------------------------------------------"
read -t 15 -p "Enter choice [y/N]: " INSTALL_WINE || INSTALL_WINE="n"

if [[ "$INSTALL_WINE" =~ ^[Yy]$ ]]; then
    echo "[*] Installing Wine for MetaTrader 5..."
    sudo dpkg --add-architecture i386
    sudo apt-get update -y
    sudo apt-get install -y wine wine64 wine32 cabextract

    export WINEARCH=win64
    export WINEPREFIX="$HOME/.wine"

    # Install Windows Python inside Wine for MT5 library compatibility
    if ! wine python --version &> /dev/null; then
        echo "[*] Downloading official Windows Python 3.11 for Wine..."
        wget -q -O /tmp/python-3.11.9-amd64.exe https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe
        echo "[*] Installing Windows Python in Wine..."
        wine /tmp/python-3.11.9-amd64.exe /quiet InstallAllUsers=1 PrependPath=1
        wine python -m pip install --upgrade pip
        wine python -m pip install -r requirements.txt
    fi

    # Install MT5 if installer present
    if [ -f "mt5setup.exe" ]; then
        echo "[*] Installing MetaTrader 5 terminal via Wine..."
        xvfb-run -a wine mt5setup.exe /auto || true
    fi
    echo "    ✅ Wine & MT5 Windows environment ready!"
fi

# 5. Verification Test Suite
echo ""
echo "[*] Running verification test suite..."
./venv/bin/python3 test_suite.py

# 6. Setup Systemd Service for 24/7 Autostart
USER_NAME="$(whoami)"
SERVICE_FILE="/etc/systemd/system/tradingbot.service"

echo "[*] Configuring systemd background service (24/7 auto-restart)..."
sudo bash -c "cat <<EOF > $SERVICE_FILE
[Unit]
Description=Institutional Gold & BTC Quantitative Trading Bot
After=network.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$SCRIPT_DIR
ExecStart=$SCRIPT_DIR/venv/bin/python3 $SCRIPT_DIR/telegram_bot.py
Restart=always
RestartSec=5
StandardOutput=append:$SCRIPT_DIR/logs/tradingbot.log
StandardError=append:$SCRIPT_DIR/logs/tradingbot.log

[Install]
WantedBy=multi-user.target
EOF"

sudo systemctl daemon-reload
echo "    ✅ Systemd service created: tradingbot.service"

echo "=================================================================="
echo "  🎉 Setup Complete!"
echo "=================================================================="
echo "Next Steps:"
echo "1. Edit .env with your bot credentials: nano .env"
echo "2. Start the 24/7 service:"
echo "     sudo systemctl enable tradingbot"
echo "     sudo systemctl start tradingbot"
echo "3. Check live logs: sudo journalctl -u tradingbot -f"
echo "4. Open Telegram and send /start to launch your Omni-Cockpit!"
echo "=================================================================="
