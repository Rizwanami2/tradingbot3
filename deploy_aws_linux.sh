#!/usr/bin/env bash
# ==============================================================================
# AWS Linux / Ubuntu VPS Deployment Script for Gold & BTC Trading Bot
# ==============================================================================
set -e

echo "=================================================================="
echo "  🚀 Deploying Institutional Gold & BTC Bot on AWS Linux VPS"
echo "=================================================================="

# 1. Update packages & install dependencies
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip python3-venv git curl

# 2. Setup project directory
APP_DIR="/home/ubuntu/tradingbot3"
if [ ! -d "$APP_DIR" ]; then
    echo "Cloning repository..."
    git clone https://github.com/Rizwanami2/tradingbot3.git "$APP_DIR"
fi

cd "$APP_DIR"

# 3. Virtual environment setup
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 4. Check for .env file
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "⚠️ Created .env from .env.example. Please edit .env with your Telegram bot token."
    fi
fi

# 5. Install systemd service for 24/7 background operation
if [ -f "tradingbot.service" ]; then
    sudo cp tradingbot.service /etc/systemd/system/tradingbot.service
    sudo systemctl daemon-reload
    sudo systemctl enable tradingbot.service
    sudo systemctl restart tradingbot.service
    echo "✅ Systemd service installed & started!"
    echo "• Check status : sudo systemctl status tradingbot"
    echo "• View logs    : sudo journalctl -u tradingbot -f"
fi

echo "=================================================================="
echo "  ✅ AWS Linux VPS Deployment Complete! Bot running 24/7."
echo "=================================================================="
