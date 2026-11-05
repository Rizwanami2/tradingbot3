# SAFETY CHECKLIST – tradingbot3

**Read this before enabling LIVE mode.**

---

## Mandatory Pre-Live Checklist

- [ ] `DEFAULT_TRADING_MODE` in `risk_engine.py` is set to `"PAPER"`
- [ ] `config_validator.py` allows paper / demo / live (already fixed in this branch)
- [ ] All hardcoded win rates removed from `self_learning.py`
- [ ] First-trade confirmation for LIVE mode is working
- [ ] You have tested at least 2–4 weeks in **PAPER** mode
- [ ] You understand the daily loss limit and kill-switch
- [ ] `LIVE_CONFIRM=CONFIRM` is only set when you intentionally want live trading
- [ ] Account risk per trade is ≤ 1%
- [ ] You have a working kill-switch command tested

---

## Recommended Risk Settings (Starting Point)

```env
TRADING_MODE=paper
RISK_PCT_PER_TRADE=0.75
MAX_DAILY_LOSS_PCT=1.5
MAX_TOTAL_OPEN_RISK_PCT=3.0
MIN_CONFLUENCE_SCORE=8.5
```

Only increase risk after consistent paper results.

---

## Emergency Commands

| Command | Action |
|---------|--------|
| `/kill CONFIRM` | Activate emergency kill-switch |
| `/kill_reset CONFIRM` | Reset kill-switch |
| `/mode paper` | Force paper mode |
| `/close_all` | Close all positions (use with caution) |

---

## Golden Rules

1. **Never** start in LIVE mode by default.
2. **Never** trust hardcoded performance numbers.
3. Paper trade until the system proves itself.
4. One mistake in live mode can be expensive — treat safety as the highest priority feature.

---

*This file exists to protect your capital.*
