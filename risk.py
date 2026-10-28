#!/usr/bin/env python3
"""
trader-gold-btc: risk.py
Validates a proposed Gold or BTC position against risk guardrails.
Edit RISK_CONFIG below to match your personal risk tolerance.
"""

import argparse
import sys

# ── Risk Configuration (edit these) ───────────────────────────────────────────

RISK_CONFIG = {
    "max_gold_allocation_pct":   0.20,   # Max 20% of portfolio in Gold
    "max_btc_allocation_pct":    0.10,   # Max 10% of portfolio in BTC
    "max_combined_hard_assets":  0.30,   # Max 30% total (Gold + BTC)
    "max_single_order_usd":      5_000,  # Max $5,000 per single order
    "min_cash_buffer_pct":       0.20,   # Always keep 20% cash
    "gold_stop_loss_pct":        0.08,   # 8% default stop-loss for Gold
    "btc_stop_loss_pct":         0.15,   # 15% default stop-loss for BTC
    "btc_vol_halt_threshold":    0.80,   # Halt BTC if 30D annualized vol > 80%
    "gold_vol_halt_threshold":   0.25,   # Halt Gold if 30D annualized vol > 25%
    "allow_leverage":            False,
    "allow_shorting":            False,
    "allow_options":             False,
    "blocked_assets":            [],     # e.g. ["GBTC"] if you want to block
}

# ── Risk Checker ───────────────────────────────────────────────────────────────

def check(label: str, passed: bool, reason: str, blocks: list):
    icon = "✅" if passed else "❌"
    print(f"  {icon}  {label}")
    if not passed:
        blocks.append(reason)

def run_risk_check(asset: str, action: str, size_pct: float,
                   portfolio_value: float, current_allocation_pct: float,
                   other_hard_asset_pct: float, cash_pct: float):

    asset = asset.upper()
    size_usd = size_pct * portfolio_value
    stop_loss_pct = (RISK_CONFIG["btc_stop_loss_pct"]
                     if asset == "BTC" else RISK_CONFIG["gold_stop_loss_pct"])
    max_alloc = (RISK_CONFIG["max_btc_allocation_pct"]
                 if asset == "BTC" else RISK_CONFIG["max_gold_allocation_pct"])
    new_allocation = current_allocation_pct + size_pct
    new_combined   = new_allocation + other_hard_asset_pct
    new_cash       = cash_pct - size_pct

    print(f"""
╔══════════════════════════════════════════════════════╗
║                    RISK CHECK                        ║
╠══════════════════════════════════════════════════════╣
  Asset:     {asset}
  Action:    {action}
  Size:      {size_pct*100:.1f}%  (${size_usd:,.0f} on ${portfolio_value:,.0f} portfolio)
  Stop-Loss: {stop_loss_pct*100:.0f}%  (exit at ${size_usd*(1-stop_loss_pct):,.0f} loss)
╠══════════════════════════════════════════════════════╣
  CHECKS:""")

    blocks = []

    if asset in RISK_CONFIG["blocked_assets"]:
        check(f"{asset} is not on blocked list",
              False, f"{asset} is blocked in risk config", blocks)
    else:
        check(f"{asset} not blocked", True, "", blocks)

    check(f"Within {asset} max allocation ({max_alloc*100:.0f}%)",
          new_allocation <= max_alloc,
          f"New allocation {new_allocation*100:.1f}% exceeds max {max_alloc*100:.0f}%", blocks)

    check(f"Combined hard assets ≤ {RISK_CONFIG['max_combined_hard_assets']*100:.0f}%",
          new_combined <= RISK_CONFIG["max_combined_hard_assets"],
          f"Combined allocation {new_combined*100:.1f}% exceeds {RISK_CONFIG['max_combined_hard_assets']*100:.0f}%", blocks)

    check(f"Single order ≤ ${RISK_CONFIG['max_single_order_usd']:,}",
          size_usd <= RISK_CONFIG["max_single_order_usd"],
          f"Order size ${size_usd:,.0f} exceeds single-order cap", blocks)

    check(f"Cash buffer preserved (≥ {RISK_CONFIG['min_cash_buffer_pct']*100:.0f}%)",
          new_cash >= RISK_CONFIG["min_cash_buffer_pct"],
          f"Cash would drop to {new_cash*100:.1f}% — below {RISK_CONFIG['min_cash_buffer_pct']*100:.0f}% minimum", blocks)

    if action in ("SHORT", "SELL_SHORT"):
        check("Shorting allowed", RISK_CONFIG["allow_shorting"],
              "Shorting is disabled in risk config", blocks)

    verdict = "PASS ✅" if not blocks else "BLOCK ❌"
    print(f"""
╠══════════════════════════════════════════════════════╣
  VERDICT: {verdict}""")

    if blocks:
        print("  Reasons:")
        for b in blocks:
            print(f"    • {b}")

    print("╚══════════════════════════════════════════════════════╝\n")
    return len(blocks) == 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Gold & BTC Risk Checker")
    p.add_argument("--asset",                required=True, choices=["BTC","GOLD","GLD","IAU","IBIT","FBTC"])
    p.add_argument("--action",               required=True, choices=["BUY","SELL","HOLD"])
    p.add_argument("--size-pct",             required=True, type=float, help="Position size as decimal (e.g. 0.05 = 5%%)")
    p.add_argument("--portfolio-value",      required=True, type=float)
    p.add_argument("--current-allocation",   type=float, default=0.0, help="Current % already in this asset")
    p.add_argument("--other-hard-asset-pct", type=float, default=0.0, help="% in other hard asset (gold if checking BTC, vice versa)")
    p.add_argument("--cash-pct",             type=float, default=1.0, help="Current cash % of portfolio")
    args = p.parse_args()

    ok = run_risk_check(
        asset=args.asset,
        action=args.action,
        size_pct=args.size_pct,
        portfolio_value=args.portfolio_value,
        current_allocation_pct=args.current_allocation,
        other_hard_asset_pct=args.other_hard_asset_pct,
        cash_pct=args.cash_pct,
    )
    sys.exit(0 if ok else 1)
