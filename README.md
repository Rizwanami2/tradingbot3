# Bottreding: Gold (XAU/USD) & Bitcoin (BTC/USD) Live MT5 Telegram Trading Bot

An institutional-grade algorithmic trading and risk management platform designed exclusively for **Gold (`XAU/USD`)** and **Bitcoin (`BTC/USD`)**. Features automated Telegram remote control, real-time macro analysis, **live MetaTrader 5 (MT5) broker execution**, and **autonomous self-learning**.

> **100% Live Account Architecture & Zero Paper Trading:** Real-time integration with your live MetaTrader 5 broker. Automatically reads your live balance and equity to calculate exact small lot sizes with tight stop-loss and take-profit targets focused on a **high win-rate %**.

---

## ⚡ Key Highlights

- **Asset Focus:** Exclusively hard monetary assets — Gold and Bitcoin.
- **Live MT5 Broker Integration:** Directly connects to your live broker account. Real-time balance, equity, and margin tracking with one-tap `/buy` and `/sell` execution.
- **High Win-Rate Sniper Mode:** Small Stop-Loss (0.4–0.6x ATR), Small Take-Profit (1.2R quick scalp with ~75% target hit rate), and conservative micro-lot position sizing.
- **Auto Real-Time Balance Risk:** Position sizing is dynamically calculated from your live MT5 equity. Zero hardcoded balances.
- **Default Visual MT5 Candlestick Charts:** Institutional dark-themed charts with 50/200 SMA, S/R, and Golden Pocket (0.618-0.650) automatically generated and sent with `/scan`, `/btc`, `/gold`, and alerts.
- **Continuous 1-Minute Candle Scanner (Zero Spam):** Audits Gold and Bitcoin in the background on every 1-minute candle close (:00s). Uses an institutional Signal State Machine: only fires for high-quality A+ setups ($\ge 8/10$), broadcasts **exactly 1 alert per setup** (no repeated spam while active), and sends a single 1-line update when Take-Profit is reached.
- **Autonomous Self-Learning (`self_learning.py`):** Automatically evaluates trade setups and tunes confluence factor weights based on historical win rates.
- **Emergency Circuit Breaker:** Instant `/close_all` command to liquidate all open live positions immediately.

---

## 🚀 Quick Setup on Windows VPS

### Step 1: Install Dependencies
```bash
py -3.11 -m pip install -r requirements.txt MetaTrader5
```

### Step 2: Configure Telegram & MT5
Run the built-in diagnostic tool:
```bash
python test_telegram.py
```
Paste your token from `@BotFather`. It will automatically test the connection and save it to `.env`.
*(Ensure your MetaTrader 5 terminal is open and logged into your live trading account with "Allow algorithmic trading" enabled in Tools -> Options -> Expert Advisors).*

### Step 3: Start the Bot
```bash
python telegram_bot.py
```

Open Telegram, search for your bot, and send **`/start`**!

---

## 📱 Organized Telegram Commands

### 💼 1. Live MT5 Broker & Trading
| Command | Action |
|---|---|
| `/account` | Live MT5 account equity, balance, free margin, broker name & status |
| `/positions` | Live MT5 open trades with real-time floating PnL |
| `/buy_gold` | Instant Live MT5 Buy on Gold with small SL & small TP (High Win Rate) |
| `/sell_gold` | Instant Live MT5 Sell on Gold with small SL & small TP (High Win Rate) |
| `/buy_btc` | Instant Live MT5 Buy on Bitcoin with small SL & small TP (High Win Rate) |
| `/sell_btc` | Instant Live MT5 Sell on Bitcoin with small SL & small TP (High Win Rate) |
| `/close_all` | 🚨 Emergency circuit breaker: Instantly closes all live open positions |
| `/auto_trade on\|off` | Toggle automatic execution of 1-minute A+ setups ($\ge 8/10$) |

### 📊 2. Market Audit & MT5 Charts
| Command | Action |
|---|---|
| `/scan` | Full market scan for Gold & BTC with dual confluence scores & default MT5 charts |
| `/btc` | Detailed Bitcoin structure, 50/200 SMA, Golden Pocket, MT5 chart & sniper ticket |
| `/gold` | Detailed Gold structure, 50/200 SMA, Golden Pocket, MT5 chart & sniper ticket |
| `/levels` | Institutional S/R levels, Daily Pivots & Fibonacci Golden Pocket (0.618-0.650) |
| `/traps` | Wyckoff microstructure inspection (Bear Springs & Bull Trap Upthrusts) |
| `/macro` | Real-time DXY, US 10-Year Real Yields, GSR, and Crypto Fear & Greed |
| `/debate` | Adversarial Bull vs. Bear debate pressure-testing both sides |

### 🛡️ 3. Risk Management & Dynamic Sizing
| Command | Action |
|---|---|
| `/risk` | Institutional risk audit & small lot sizing on live MT5 equity |
| `/risk [balance]` | Simulate custom equity and calculate exact lot sizes (e.g. `/risk 25000`) |

### 🧠 4. Autonomous Self-Learning & System
| Command | Action |
|---|---|
| `/learn` | Displays self-learning factor rankings and win-rate attribution |
| `/train` | Triggers walk-forward historical training on past price action |
| `/status` | Live bot health, MT5 connection status & 1-minute scanner uptime |
| `/menu` | Redisplay organized command directory |

---

## 📁 Repository Structure

```
Bottreding/
├── telegram_bot.py           # Unified Telegram Bot (Live MT5, 12 skills + auto-charts)
├── mt5_executor.py           # MT5 Live Broker Engine (Orders, Live Balance, Symbol Resolver)
├── risk_engine.py            # Dynamic lot sizing, VaR, Kelly Criterion & Circuit Breakers
├── chart_generator.py        # MT5 Dark Candlestick Chart Engine (SMA, Golden Pocket, S/R)
├── test_telegram.py          # Quick 30-second Telegram token test & setup tool
├── autotrader_pipeline.py    # 4-stage deterministic execution engine
├── self_learning.py          # Self-learning & adaptive weight optimization engine
├── terminal.py               # Interactive hard-asset multi-factor dashboard
├── find_levels.py            # Key level, S/R flip & Fibonacci Golden Pocket scanner
├── detect_fakeout.py         # Bull/Bear trap and liquidity sweep analyzer
├── risk.py                   # Portfolio concentration & allocation checker
├── .env.example              # Environment variables template
├── requirements.txt          # Python dependencies
└── README.md                 # System documentation
```

---

## 📄 License
This project is licensed under the Apache 2.0 License - see the [LICENSE](LICENSE) file for details.
