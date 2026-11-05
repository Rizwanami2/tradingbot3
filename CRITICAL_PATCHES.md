# Critical Safety Patches

Apply these 3 changes manually (or via PR) before any live trading.

---

## Patch 1: risk_engine.py – Change Default Trading Mode

**File:** `risk_engine.py`  
**Location:** Around line 78

**Find:**
```python
DEFAULT_TRADING_MODE = "LIVE"
```

**Replace with:**
```python
DEFAULT_TRADING_MODE = "PAPER"       # CRITICAL SAFETY: Never default to LIVE
```

---

## Patch 2: risk_engine.py – Restore First Trade Confirmation

**File:** `risk_engine.py`  
**Location:** Around lines 261–269

**Find this entire method:**
```python
    def is_first_trade_confirmed_today(self) -> bool:
        """First trade confirmation removed - auto-trade is always allowed."""
        return True

    def confirm_first_trade_today(self) -> tuple:
        today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.state["first_trade_confirmed_date"] = today_utc
        self.save_state()
        return True, "✅ First trade of the day confirmed. Live auto-execution authorized for today."
```

**Replace with:**
```python
    def is_first_trade_confirmed_today(self) -> bool:
        """Return True only if the first live trade of today has been explicitly confirmed."""
        today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        confirmed_date = self.state.get("first_trade_confirmed_date", "")
        return confirmed_date == today_utc

    def confirm_first_trade_today(self) -> tuple:
        today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.state["first_trade_confirmed_date"] = today_utc
        self.save_state()
        return True, "✅ First trade of the day confirmed. Live auto-execution authorized for today."
```

---

## Patch 3: self_learning.py – Remove Hardcoded Win Rates

**File:** `self_learning.py`

Search for any of these patterns and remove/replace them:

- Any dictionary or variable containing hardcoded values like:
  - `"win_rate": 0.81`
  - `"empirical_win_rate": 0.71`
  - Comments mentioning `81.2% (32 trades)` or similar small-sample stats

**Recommended action:**
- Initialize performance tracking with empty / neutral values.
- Only update win rates from real closed trades.
- Add a minimum sample size (e.g. 30+ trades) before using learned rates for decision making.

Example safe initialization:
```python
self.strategy_stats = {
    "total_trades": 0,
    "wins": 0,
    "losses": 0,
    "win_rate": 0.5,          # Neutral prior
    "avg_r": 0.0,
}
```

---

## After Applying Patches

1. Search the codebase for any remaining `"LIVE"` defaults.
2. Run the bot in **paper** mode and verify:
   - Mode shows as PAPER
   - First trade in LIVE still requires confirmation
3. Only then consider enabling live trading.

---

These three changes are the highest priority safety improvements remaining.
