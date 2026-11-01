#!/usr/bin/env python3
"""
config_validator.py
Startup Configuration Validator for tradingbot3.
Validates environment variables, trading mode rules, safety thresholds, and credentials.
Fails fast with clear, actionable error messages before execution begins.
"""

import os
import sys
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import json
import logging
from typing import Tuple, List

try:
    from utils.logger import get_logger
    logger = get_logger("config_validator")
except Exception:
    logger = logging.getLogger("config_validator")


def load_env_file(filepath: str = ".env"):
    """Loads key-value pairs from .env into os.environ if not already set."""
    if not os.path.exists(filepath):
        return
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception as e:
        logger.warning(f"Could not parse {filepath}: {e}")


def parse_telegram_ids(raw_val: str) -> List[str]:
    """Parses ALLOWED_TELEGRAM_IDS from string, json, or comma-separated list."""
    if not raw_val:
        return []
    raw_val = raw_val.strip()
    if raw_val.startswith("[") and raw_val.endswith("]"):
        try:
            parsed = json.loads(raw_val)
            return [str(x).strip() for x in parsed if str(x).strip()]
        except Exception:
            pass
    items = [x.strip() for x in raw_val.split(",") if x.strip()]
    return items


def validate_config(fail_fast: bool = False) -> Tuple[bool, List[str]]:
    """
    Validates all required startup configurations and safety gate thresholds.
    Returns (is_valid, error_list).
    If fail_fast=True, raises ValueError on the first set of errors.
    """
    load_env_file()
    errors: List[str] = []

    # 1. Trading Mode & Live Confirmation Check
    trading_mode = os.environ.get("TRADING_MODE", "paper").strip().lower()
    valid_modes = ("paper", "demo", "live")
    if trading_mode not in valid_modes:
        errors.append(f"Invalid TRADING_MODE='{trading_mode}'. Must be one of {valid_modes}.")

    if trading_mode == "live":
        live_confirm = os.environ.get("LIVE_CONFIRM", "").strip().upper()
        if live_confirm != "CONFIRM":
            errors.append(
                "TRADING_MODE is set to 'live' but LIVE_CONFIRM is not 'CONFIRM'. "
                "Real capital execution is blocked. Set LIVE_CONFIRM=CONFIRM in .env to authorize live trading."
            )

    # 2. MT5 Configuration & Path Check
    mt5_path = os.environ.get("MT5_PATH", "").strip()
    if mt5_path and not os.path.exists(mt5_path):
        errors.append(f"Configured MT5_PATH does not exist: '{mt5_path}'")

    # 3. Numeric Safety Ranges
    def check_float(var_name: str, default: float, min_val: float, max_val: float, inclusive_max: bool = False):
        raw = os.environ.get(var_name, str(default)).strip()
        try:
            val = float(raw)
            if inclusive_max:
                if not (min_val < val <= max_val):
                    errors.append(f"{var_name}={val} out of bounds. Must be > {min_val} and <= {max_val}.")
            else:
                if not (min_val < val < max_val):
                    errors.append(f"{var_name}={val} out of bounds. Must be > {min_val} and < {max_val}.")
        except ValueError:
            errors.append(f"{var_name} must be a valid float number, got '{raw}'.")

    # MAX_DAILY_LOSS_PCT: > 0 and < 10
    check_float("MAX_DAILY_LOSS_PCT", 1.5, 0.0, 10.0, inclusive_max=False)

    # MAX_TOTAL_OPEN_RISK_PCT: > 0 and <= 10
    check_float("MAX_TOTAL_OPEN_RISK_PCT", 2.5, 0.0, 10.0, inclusive_max=True)

    # MAX_SPREAD_PIPS: > 0 and <= 100
    check_float("MAX_SPREAD_PIPS", 30.0, 0.0, 100.0, inclusive_max=True)

    # MAX_SLIPPAGE_PIPS: > 0 and <= 20
    check_float("MAX_SLIPPAGE_PIPS", 3.0, 0.0, 20.0, inclusive_max=True)

    # RISK_PCT_PER_TRADE: > 0 and <= 5.0
    check_float("RISK_PCT_PER_TRADE", 1.0, 0.0, 5.0, inclusive_max=True)

    # ACCOUNT_BALANCE: > 0
    raw_bal = os.environ.get("ACCOUNT_BALANCE", "10000").strip()
    try:
        bal = float(raw_bal)
        if bal <= 0:
            errors.append(f"ACCOUNT_BALANCE must be > 0, got {bal}.")
    except ValueError:
        errors.append(f"ACCOUNT_BALANCE must be a valid number, got '{raw_bal}'.")

    # 4. Telegram IDs Check
    allowed_ids_raw = os.environ.get("ALLOWED_TELEGRAM_IDS", "").strip()
    if allowed_ids_raw and allowed_ids_raw not in ("[]", ""):
        parsed_ids = parse_telegram_ids(allowed_ids_raw)
        for tid in parsed_ids:
            if not tid.lstrip("-").isdigit():
                errors.append(f"ALLOWED_TELEGRAM_IDS contains non-numeric ID: '{tid}'")

    is_valid = len(errors) == 0
    if not is_valid:
        error_msg = "[Config Validation Failed]\n" + "\n".join(f"  • {e}" for e in errors)
        logger.error(error_msg)
        if fail_fast:
            raise ValueError(error_msg)
    else:
        logger.info(f"Startup Config Validation Passed. Trading Mode: {trading_mode.upper()} ✅")

    return is_valid, errors


def ensure_valid_config():
    """Convenience function that fails fast with exit code 1 if config is invalid."""
    is_valid, errors = validate_config(fail_fast=False)
    if not is_valid:
        sys.stderr.write("\n" + "=" * 70 + "\n")
        sys.stderr.write("  🛑 CRITICAL STARTUP CONFIGURATION ERROR\n")
        sys.stderr.write("=" * 70 + "\n")
        for err in errors:
            sys.stderr.write(f"  • {err}\n")
        sys.stderr.write("=" * 70 + "\n\n")
        sys.exit(1)
    return True


if __name__ == "__main__":
    valid, errs = validate_config()
    if valid:
        print("✅ Config validation passed successfully!")
    else:
        print(f"❌ Found {len(errs)} configuration errors:")
        for e in errs:
            print(f"   - {e}")
        sys.exit(1)
