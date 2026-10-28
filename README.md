# Bottreding: Gold (XAU/USD) & Bitcoin (BTC/USD) Quantitative Telegram Trading Bot

An institutional-grade, multi-factor algorithmic trading and risk management platform designed exclusively for **Gold (`XAU/USD`)** and **Bitcoin (`BTC/USD`)**. Features automated Telegram alerts, real-time macro analysis, and **autonomous self-learning**.

> **100% Standalone & Zero MT5 Dependency:** Runs on **any VPS** (Windows, Linux, Ubuntu, macOS) with free public data feeds. No MetaTrader 5 installation or broker login required.

---

## ⚡ Key Highlights

- **Asset Focus:** Exclusively hard monetary assets — Gold and Bitcoin.
- **Zero Broker Lock-in:** No MT5 or broker account needed. Works 100% via Telegram.
- **Automated 30-Minute Market Scanner:** Continuously audits the markets in the background and sends push notifications to your phone whenever an A+ setup ($\ge 8/10$) appears.
- **Autonomous Self-Learning (`self_learning.py`):** Automatically evaluates trade setups and tunes confluence factor weights based on historical win rates.
- **4-Stage Confluence Pipeline:** Enforces structural location (0.618–0.650 Fibonacci Golden Pocket, 50/200 SMA), Wyckoff trap wicks ($\ge 40\%$), and macro context (DXY, 10Y Yields, GSR, Fear & Greed).
- **Exact Actionable Order Tickets:** Provides Entry, Stop-Loss, TP1 (+2R), and TP2 for every valid setup.

---

## 🚀 Quick Setup on Any VPS (Windows / Linux)

### Step 1: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 2: Test & Connect Telegram in 30 Seconds
Run the built-in diagnostic tool:
```bash
python test_telegram.py
```
Paste your token from `@BotFather`. It will automatically test the connection and save it to `.env`.

### Step 3: Start the Bot
```bash
python telegram_bot.py
```

Open Telegram, search for your bot, and send **`/start`**!

---

## 📱 Telegram Commands

| Command | Action |
|---|---|
| `/start` | Connects your session and displays menu |
| `/scan` | Full market scan for Gold & BTC with dual confluence scores (Base + Learned) |
| `/btc` | Detailed Bitcoin structure, 50/200 SMA, Golden Pocket status & trade ticket |
| `/gold` | Detailed Gold structure, 50/200 SMA, Golden Pocket status & trade ticket |
| `/macro` | Real-time DXY, US 10-Year Real Yields, GSR, and Crypto Fear & Greed |
| `/learn` | Displays self-learning factor rankings and win-rate attribution |
| `/train` | Triggers walk-forward historical training on past price action |

---

## 📁 Repository Structure

```
Bottreding/
├── telegram_bot.py           # Primary Telegram Bot (Zero MT5, runs on any VPS)
├── test_telegram.py          # Quick 30-second Telegram token test & setup tool
├── autotrader_pipeline.py    # 4-stage deterministic execution engine
├── self_learning.py          # Self-learning & adaptive weight optimization engine
├── learning_memory.json      # Persistent learning memory & trade journal
├── terminal.py               # Interactive hard-asset multi-factor dashboard
├── find_levels.py            # Key level, S/R flip & Fibonacci Golden Pocket scanner
├── detect_fakeout.py         # Bull/Bear trap and liquidity sweep analyzer
├── .env.example              # Environment variables template
├── requirements.txt          # Python dependencies (No MT5 required)
└── README.md                 # System documentation
```

---

## 📄 License
This project is licensed under the Apache 2.0 License - see the [LICENSE](LICENSE) file for details.
