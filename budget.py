#!/usr/bin/env python3
"""
trader-gold-btc: budget.py
Capital allocation calculator for Gold and BTC positions.
"""
import argparse

def run_budget(portfolio: float, gold_pct: float, btc_pct: float,
               gold_price: float = None, btc_price: float = None,
               dca_weeks: int = 0):

    gold_usd = portfolio * (gold_pct / 100)
    btc_usd  = portfolio * (btc_pct / 100)
    cash_usd = portfolio - gold_usd - btc_usd
    cash_pct = (cash_usd / portfolio) * 100

    print(f"""
╔══════════════════════════════════════════════════════╗
║               BUDGET ALLOCATION                      ║
╠══════════════════════════════════════════════════════╣
  Portfolio Value:  ${portfolio:>12,.2f}
╠══════════════════════════════════════════════════════╣
  Gold  ({gold_pct:.1f}%):   ${gold_usd:>12,.2f}""")

    if gold_price:
        oz = gold_usd / gold_price
        gld_shares = gold_usd / (gold_price * 0.096)  # GLD ≈ 0.096 oz/share approx
        print(f"               ≈ {oz:.3f} oz  |  ≈ {gld_shares:.1f} GLD shares")

    print(f"""
  BTC   ({btc_pct:.1f}%):    ${btc_usd:>12,.2f}""")

    if btc_price:
        btc_units = btc_usd / btc_price
        print(f"               ≈ {btc_units:.6f} BTC")

    print(f"""
  Cash  ({cash_pct:.1f}%):  ${cash_usd:>12,.2f}
  {'⚠ WARNING: Cash below 20% minimum!' if cash_pct < 20 else '✅ Cash buffer adequate'}
╠══════════════════════════════════════════════════════╣""")

    if dca_weeks > 0:
        weekly_gold = gold_usd / dca_weeks
        weekly_btc  = btc_usd / dca_weeks
        print(f"""  DCA SCHEDULE ({dca_weeks} weeks):
    Weekly Gold:  ${weekly_gold:>10,.2f} / week
    Weekly BTC:   ${weekly_btc:>10,.2f} / week""")

    print("╚══════════════════════════════════════════════════════╝\n")

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Gold & BTC Budget Allocator")
    p.add_argument("--portfolio-value", required=True, type=float)
    p.add_argument("--gold-pct",        required=True, type=float, help="Gold allocation % (e.g. 15)")
    p.add_argument("--btc-pct",         required=True, type=float, help="BTC allocation % (e.g. 8)")
    p.add_argument("--gold-price",      type=float, help="Current gold spot price (optional)")
    p.add_argument("--btc-price",       type=float, help="Current BTC price (optional)")
    p.add_argument("--dca-weeks",       type=int,   default=0, help="DCA over N weeks (0=lump sum)")
    args = p.parse_args()

    run_budget(
        portfolio=args.portfolio_value,
        gold_pct=args.gold_pct,
        btc_pct=args.btc_pct,
        gold_price=args.gold_price,
        btc_price=args.btc_price,
        dca_weeks=args.dca_weeks,
    )
