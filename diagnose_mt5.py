#!/usr/bin/env python3
"""
diagnose_mt5.py - Institutional MetaTrader 5 Connectivity Diagnostic Tool
Runs a 6-step deep audit to troubleshoot why MT5 cannot connect.
"""

import os
import sys
import platform

print("=" * 70)
print("  🔍 METATRADER 5 (MT5) CONNECTIVITY DIAGNOSTIC AUDIT")
print("=" * 70)

# Check 1: Python Architecture & Version
is_64bit = sys.maxsize > 2**32
py_ver = platform.python_version()
print(f"[*] Check 1: Python Architecture: {platform.architecture()[0]} (Python {py_ver})")
if not is_64bit:
    print("    ❌ CRITICAL: You are running 32-bit Python! MetaTrader 5 requires 64-bit Python.")
    print("    --> Fix: Install Python 3.11 64-bit from python.org.")
else:
    print("    ✅ 64-bit Python verified.")

# Check 2: MetaTrader5 Library
print("\n[*] Check 2: MetaTrader5 Python Package...")
try:
    import MetaTrader5 as mt5
    print(f"    ✅ MetaTrader5 package installed (Version: {mt5.__version__}, Author: {mt5.__author__})")
except ImportError:
    print("    ❌ MetaTrader5 package is NOT installed in this environment.")
    print("    --> Fix: Run: py -3.11 -m pip install MetaTrader5")
    sys.exit(1)

# Check 3: Check if terminal64.exe process is running
print("\n[*] Check 3: Checking if MetaTrader 5 is currently open in Windows...")
running = False
if sys.platform == "win32":
    try:
        tasks = os.popen("tasklist /FI \"IMAGENAME eq terminal64.exe\"").read()
        if "terminal64.exe" in tasks.lower():
            running = True
            print("    ✅ terminal64.exe is currently RUNNING in Task Manager.")
        else:
            print("    ⚠️ terminal64.exe is NOT currently running.")
            print("    --> Note: MetaTrader 5 must be opened on your desktop for Python to attach.")
    except Exception as e:
        print(f"    Could not query tasklist: {e}")

# Check 4: Locate terminal64.exe on Disk
print("\n[*] Check 4: Searching for MetaTrader 5 installation on disk...")
common_paths = [
    os.environ.get("MT5_PATH", "").strip(),
    "C:\\Program Files\\MetaTrader 5\\terminal64.exe",
    "C:\\Program Files (x86)\\MetaTrader 5\\terminal64.exe",
    "C:\\Program Files\\FTMO MetaTrader 5\\terminal64.exe",
    "C:\\Program Files\\ICMarkets MetaTrader 5\\terminal64.exe",
    "C:\\Program Files\\Exness MetaTrader 5\\terminal64.exe",
    "C:\\Program Files\\XM Global MT5\\terminal64.exe",
    "C:\\Program Files\\FBS MetaTrader 5\\terminal64.exe",
    "C:\\Program Files\\Vantage Markets MT5\\terminal64.exe"
]

found_paths = []
for p in common_paths:
    if p and os.path.exists(p) and p not in found_paths:
        found_paths.append(p)

if os.path.exists("C:\\Program Files"):
    try:
        for entry in os.listdir("C:\\Program Files"):
            sub = os.path.join("C:\\Program Files", entry, "terminal64.exe")
            if os.path.exists(sub) and sub not in found_paths:
                found_paths.append(sub)
    except Exception:
        pass

if found_paths:
    print(f"    ✅ Found {len(found_paths)} MetaTrader 5 terminal(s):")
    for fp in found_paths:
        print(f"       • {fp}")
else:
    print("    ❌ No terminal64.exe found in standard Program Files directories.")
    print("    --> Fix: If installed elsewhere, set MT5_PATH in .env (e.g. MT5_PATH=D:\\MT5\\terminal64.exe)")

# Check 5: Attempt mt5.initialize()
print("\n[*] Check 5: Testing mt5.initialize()...")
init_ok = False
used_path = None

if found_paths:
    for candidate in found_paths:
        print(f"    Attempting connection with: {candidate}...")
        init_ok = mt5.initialize(path=candidate)
        if init_ok:
            used_path = candidate
            break

if not init_ok:
    print("    Attempting default attach (mt5.initialize())...")
    init_ok = mt5.initialize()

if init_ok:
    print(f"    ✅ mt5.initialize() SUCCESSFUL! (Attached via: {used_path or 'Default IPC'})")
else:
    err = mt5.last_error()
    print(f"    ❌ mt5.initialize() FAILED: Error {err}")
    if err[0] == -10003:
        print("       Cause: MetaTrader 5 is either closed or permission mismatch.")
        print("       Solution:")
        print("       1. Double-click your MetaTrader 5 desktop icon to open the app.")
        print("       2. Make sure both Python and MT5 are run with the same privileges (both regular user or both Admin).")
    sys.exit(1)

# Check 6: Account Info & Algorithmic Trading Permission
print("\n[*] Check 6: Verifying Account and Algo Trading Permissions...")
term_info = mt5.terminal_info()
acc_info = mt5.account_info()

if term_info:
    print(f"    • Connected Terminal : {term_info.name} ({term_info.path})")
    print(f"    • Community Account  : {term_info.community_account or 'None'}")
    if term_info.trade_allowed:
        print("    • Algo Trading       : ✅ ENABLED (Bot has permission to execute orders)")
    else:
        print("    • Algo Trading       : ⚠️ DISABLED in MT5 settings!")
        print("      --> Fix: In MT5, go to Tools -> Options -> Expert Advisors -> check 'Allow algorithmic trading'")
        print("      --> Also check that the 'Algo Trading' toolbar button is green.")

if acc_info:
    print(f"    • Broker Company     : {acc_info.company}")
    print(f"    • Account Number     : #{acc_info.login}")
    print(f"    • Account Server     : {acc_info.server}")
    print(f"    • Balance / Equity   : ${acc_info.balance:,.2f} / ${acc_info.equity:,.2f} {acc_info.currency}")
    print(f"    • Leverage           : 1:{acc_info.leverage}")
    print(f"    • Trade Mode         : {'Demo' if acc_info.trade_mode == 0 else ('Contest' if acc_info.trade_mode == 1 else 'REAL LIVE CAPITAL')}")
    print("\n" + "=" * 70)
    print("  🎉 DIAGNOSIS RESULT: ALL CHECKS PASSED! MT5 IS READY FOR TRADING.")
    print("=" * 70)
else:
    print("    ⚠️ Could not fetch account info. Terminal is open but no broker account is logged in.")
    print("    --> Fix: In MT5, click File -> Login to Trade Account and enter your broker credentials.")

mt5.shutdown()
