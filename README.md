# tradingbot3 – Hard Asset Precision Desk

Institutional-style trading bot focused on **GOLD (XAUUSD)** and **BTC (BTCUSD)**.

Built around confluence scoring, multi-layer risk management, self-learning, and Telegram control.

> **⚠️ SAFETY FIRST**  
> This project must always start in **PAPER** mode.  
> Never run LIVE until you fully understand the risk system and have tested thoroughly.

---

## Current Status (fix/safety-and-bugs branch)

| Item | Status |
|------|--------|
| Default Trading Mode | Should be PAPER (critical fix still needed in `risk_engine.py`) |
| Config Validator | ✅ Fixed – supports paper / demo / live |
| Hardcoded Win Rates | ❌ Still present – must be removed |
| README | ✅ Added |
| .gitignore | ✅ Fixed (README now allowed) |

See **[FIXES.md](FIXES.md)** for the full list of known issues and required fixes.

---

## Architecture Overview

```
┌─────────────────────┐
│   Telegram Bot      │  ← Control plane & alerts
└─────────┬───────────┘
          │
┌─────────▼───────────┐
│   Orchestrator      │  ← Decision brain
└─────────┬───────────┘
          │
    ┌─────┴─────┬──────────────┬────────────────┐
    │           │              │                │
┌───▼───┐  ┌────▼────┐  ┌──────▼─────┐  ┌───────▼──────┐
│ Risk  │  │Confluence│  │ Self       │  │ Institutional│
│Engine │  │ Engine  │  │ Learning   │  │ Bias         │
└───┬───┘  └─────────┘  └────────────┘  └──────────────┘
    │
┌───▼──────────┐
│ MT5 Executor │  ← Live / Demo order execution
└──────────────┘
```

---

## Key Safety Features

- Multi-layer circuit breakers (daily loss, total open risk, kill-switch)
- Dynamic position sizing based on equity and SL distance
- Minimum Risk:Reward enforcement
- Spread & slippage guards
- News avoidance window
- Regime-based risk adjustment
- Emergency kill-switch (`/kill` + confirmation)

---

## Quick Start (Safe Mode)

1. **Clone the repository**
   ```bash
   git clone https://github.com/Rizwanami2/tradingbot3.git
   cd tradingbot3
   git checkout fix/safety-and-bugs
   ```

2. **Create virtual environment & install dependencies**
   ```bash
   python -m venv venv
   source venv/bin/activate          # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env → keep TRADING_MODE=paper
   ```

4. **Run in Paper mode**
   ```bash
   python main.py
   ```

---

## Important Configuration

| Variable | Recommended Value | Notes |
|----------|-------------------|-------|
| `TRADING_MODE` | `paper` | Always start here |
| `LIVE_CONFIRM` | (empty) | Only set to `CONFIRM` when you are ready for live |
| `RISK_PCT_PER_TRADE` | `0.5` – `1.0` | Never higher than 1% for most accounts |
| `MAX_DAILY_LOSS_PCT` | `1.5` – `2.0` | Hard daily stop |
| `MIN_CONFLUENCE_SCORE` | `8` | Quality filter |

---

## Critical Remaining Fixes

Before going live you **must** complete these:

1. Change `DEFAULT_TRADING_MODE = "LIVE"` → `"PAPER"` in `risk_engine.py`
2. Remove all hardcoded optimistic win rates from `self_learning.py`
3. Restore proper first-trade confirmation for live mode

Full details are in **[FIXES.md](FIXES.md)**.

---

## Disclaimer

This is experimental software. Trading involves substantial risk of loss.  
Use at your own risk. The authors are not responsible for any financial losses.

Always test thoroughly in paper/demo mode first.
