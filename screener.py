#!/usr/bin/env python3
"""
trader-gold-btc: screener.py
Screens Gold and BTC for entry signals based on configurable rules.
"""
import argparse, json, urllib.request

def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "trader-gold-btc/1.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def compute_rsi(prices, period=14):
    if len(prices) < period + 1: return float("nan")
    gains = [max(prices[i]-prices[i-1], 0) for i in range(1,len(prices))]
    losses = [max(prices[i-1]-prices[i], 0) for i in range(1,len(prices))]
    ag = sum(gains[-period:])/period
    al = sum(losses[-period:])/period
    return round(100 - (100/(1+(ag/al))), 2) if al != 0 else 100.0

def get_btc_metrics():
    data   = fetch_json("https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=200&interval=daily")
    fg     = fetch_json("https://api.alternative.me/fng/?limit=1")
    prices = [p[1] for p in data["prices"]]
    ma200  = sum(prices[-200:])/200
    return {
        "price":         prices[-1],
        "rsi_14":        compute_rsi(prices),
        "price_vs_ma200": prices[-1] - ma200,
        "fear_greed":    int(fg["data"][0]["value"]),
        "etf_flow_7d":   0,   # Placeholder — fetch from farside.co.uk manually
    }

def evaluate_rules(asset, metrics, rules):
    ops = {">": lambda a,b: a>b, "<": lambda a,b: a<b, "==": lambda a,b: a==b, ">=": lambda a,b: a>=b, "<=": lambda a,b: a<=b}
    results = []
    for r in rules:
        val = metrics.get(r["metric"])
        if val is None:
            results.append((r["label"], None, "no data"))
            continue
        passed = ops[r["op"]](val, r["value"])
        results.append((r["label"], passed, f"{r['metric']}={val} {r['op']} {r['value']}"))
    return results

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--rules", default="scripts/rules.json")
    p.add_argument("--asset", default="ALL", choices=["BTC","GOLD","ALL"])
    args = p.parse_args()

    try:
        with open(args.rules) as f:
            config = json.load(f)
    except FileNotFoundError:
        # Default rules
        config = {
            "BTC":  [
                {"metric":"rsi_14","op":"<","value":60,"label":"RSI not overbought"},
                {"metric":"price_vs_ma200","op":">","value":0,"label":"Above 200D MA"},
                {"metric":"fear_greed","op":"<","value":75,"label":"Not extreme greed"},
            ]
        }

    print("\n=== SCREENER RESULTS ===")
    if args.asset in ("BTC","ALL"):
        print("\n📊 BTC")
        try:
            m = get_btc_metrics()
            results = evaluate_rules("BTC", m, config.get("BTC",[]))
            passed  = sum(1 for _,p,_ in results if p is True)
            total   = len(results)
            for label, ok, detail in results:
                print(f"  {'✅' if ok else '❌' if ok is False else '⚠'} {label} ({detail})")
            signal = "SIGNAL 🟢" if passed == total else f"NO SIGNAL 🔴 ({passed}/{total} rules)"
            print(f"\n  BTC → {signal}")
        except Exception as e:
            print(f"  Error fetching BTC data: {e}")

    if args.asset in ("GOLD","ALL"):
        print("\n📊 GOLD")
        print("  ⚠  Gold screening requires yfinance: pip install yfinance")
        print("     Then add GOLD rules to rules.json and re-run.")
    print()
