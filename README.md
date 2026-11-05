# tradingbot3 — Institutional Hard-Asset Trading Bot

Autonomous trading engine for Gold (XAU/USD) and Bitcoin (BTC/USD) with profile-aware risk management, automated trailing stops, breakeven protection, Telegram command hub, self-learning, and MT5 integration.

## ⚠️ Safety First

- **Default mode is PAPER** (no real capital at risk).
- **LIVE mode is opt-in only**: set `TRADING_MODE=live` and `LIVE_CONFIRM=CONFIRM` in `.env`.
- First live trade of the day requires a second one-time confirmation via `/confirm_trade YES`.
- Never run LIVE mode without understanding the risk. You can lose money.

---

## Architecture

| Module | Responsibility |
|--------|---------------|
| `risk_engine.py` | SafetyManager: trading modes, circuit breakers, risk checks, paper account, audit logging |
| `mt5_executor.py` | MT5LiveBroker: live order execution, trailing stops, breakeven, pending orders |
| `core/orchestrator.py` | One-Brain Precision Orchestrator: single decision point, cycle loop, position management |
| `autotrader_pipeline.py` | Candidate setup generation (confluence scoring, no execution) |
| `self_learning.py` | Strategy weights, win-rate learning from real trades, negative memory |
| `market_data.py` | Multi-source price feed (MT5 → Yahoo → secondary → cache) |
| `telegram_bot.py` | Telegram command hub: `/trail`, `/mode`, `/strategy`, `/risk`, `/kill`, etc. |
| `institutional_engine.py` | HTF bias, SMC, neuro-symbolic predictor, forensic council |
| `backtest.py` | Historical backtesting engine |
| `config_validator.py` | Startup config validation (fails fast on invalid settings) |
| `chart_generator.py` | MT5-style candlestick chart PNG generation |

---

## Quick Start

### 1. Install dependencies

```powershell
pip install -r requirements.txt
pip install MetaTrader5   # Required for LIVE mode only
```

### 2. Configure environment

Copy `.env.example` to `.env` and fill in your values:

```powershell
copy .env.example .env
```

Key settings in `.env`:

| Variable | Description | Example |
|----------|-------------|---------|
| `TRADING_MODE` | `paper`, `demo`, or `live` (default: `paper`) | `paper` |
| `LIVE_CONFIRM` | Must be `CONFIRM` only when `TRADING_MODE=live` | `CONFIRM` |
| `MT5_LOGIN` | MT5 account login | `12345678` |
| `MT5_PASSWORD` | MT5 account password | `your_password` |
| `MT5_SERVER` | MT5 broker server | `Broker-Demo` |
| `MT5_PATH` | Path to MT5 terminal64.exe | `C:\Program Files\MetaTrader 5\terminal64.exe` |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token | `123456:ABC-DEF...` |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID | `987654321` |
| `ALLOWED_TELEGRAM_IDS` | Allowed Telegram user IDs | `[123456789]` |

### 3. Validate configuration

```powershell
python config_validator.py
```

### 4. Run the bot (PAPER mode by default)

```powershell
python run_bot.py
```

For LIVE mode (after setting `.env` correctly):

```powershell
python run_bot.py --interval 5
```

---

## Core Safety Rules

1. **PAPER by default** — No real money is at risk unless you explicitly opt into LIVE.
2. **LIVE requires double confirmation** — `LIVE_CONFIRM=CONFIRM` in `.env` + `/confirm_trade YES` for the first trade each day.
3. **Circuit breakers** — Daily loss limit (2.0%), max total open risk (2.5%), max 2 concurrent positions.
4. **Kill-switch** — `/kill` halts all trading immediately; `/kill_reset CONFIRM` to restore.
5. **Stale data protection** — Quotes older than 15 minutes are rejected.
6. **Spread & slippage guards** — Orders rejected if spread/slippage exceeds configured limits.

---

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome & onboarding |
| `/help` | Full command list |
| `/menu` | Main menu with quick buttons |
| `/mode paper\|demo\|live` | Switch trading mode |
| `/enable_live CONFIRM` | Authorize LIVE mode |
| `/confirm_trade YES` | Confirm first live trade of the day |
| `/trail on\|off\|status` | Automated trailing stop & breakeven |
| `/strategy scalp\|swing\|balance\|swap` | Set active strategy profile |
| `/risk` | Show risk & safety dashboard |
| `/positions` | Show open positions |
| `/portfolio` | Portfolio summary |
| `/account` | Account info |
| `/kill` | Emergency kill-switch |
| `/kill_reset CONFIRM` | Reset kill-switch |
| `/safety` | Safety controls overview |
| `/auto_trade on\|off` | Enable/disable auto-trading |
| `/backtest gold scalp 90` | Run historical backtest |
| `/learn` | Self-learning status |

---

## Configuration Files

| File | Purpose |
|------|---------|
| `.env` | Runtime environment variables (secrets, not committed) |
| `.env.example` | Template for `.env` |
| `config_bot.json` | Centralized bot configuration (risk, automation, MT5, Telegram) |
| `config_telegram.json` | Telegram-specific configuration |
| `rules.json` | Trading rules and constraints |
| `safety_state.json` | Persisted safety state (kill switch, daily PnL, mode) |
| `learning_memory.json` | Self-learning memory (strategy weights, win rates) |
| `trade_audit.jsonl` | Order audit log |

---

## Development

### Run tests

```powershell
python test_suite.py
```

### Project structure

```
tradingbot3/
├── core/
│   ├── orchestrator.py      # One-Brain decision engine
│   ├── bot_state.py         # Bot state synchronization
│   ├── gates.py             # Safety gates & risk checks
│   └── lock.py              # Single-instance lock
├── risk_engine.py           # Risk management & SafetyManager
├── mt5_executor.py          # MT5 broker execution
├── autotrader_pipeline.py   # Setup generation (no execution)
├── self_learning.py         # Strategy learning & memory
├── market_data.py           # Multi-source price feed
├── telegram_bot.py          # Telegram command hub
├── institutional_engine.py  # HTF bias, SMC, predictor
├── backtest.py              # Historical backtesting
├── chart_generator.py       # Chart PNG generation
├── config_validator.py      # Startup validation
├── config_bot.json          # Centralized configuration
├── requirements.txt         # Python dependencies
└── test_suite.py            # Test harness
```

---

## License

See LICENSE file.