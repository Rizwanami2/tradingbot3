#!/usr/bin/env python3
"""
test_telegram.py
Quick Diagnostic Tool to test and verify your Telegram Bot connection.
Run on your VPS: python test_telegram.py
"""

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
import json
import urllib.request
import urllib.parse
import urllib.error

ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config_telegram.json")


def get_token():
    # 1. Try environment variable
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if token and token != "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        return token.strip()

    # 2. Try .env file
    if os.path.exists(ENV_PATH):
        try:
            with open(ENV_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("TELEGRAM_BOT_TOKEN="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val and val != "YOUR_TELEGRAM_BOT_TOKEN_HERE":
                            return val
        except Exception:
            pass

    # 3. Try config_telegram.json
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                val = data.get("telegram", {}).get("bot_token", "").strip()
                if val and val != "YOUR_TELEGRAM_BOT_TOKEN_HERE":
                    return val
        except Exception:
            pass

    return None


def main():
    print("=" * 65)
    print("  🔍 TELEGRAM BOT CONNECTION DIAGNOSTIC")
    print("=" * 65)

    token = get_token()

    if not token:
        print("\n❌ No Telegram Bot Token found in .env or config_telegram.json!")
        print("\nPlease enter your bot token from @BotFather:")
        try:
            user_input = input("Bot Token: ").strip()
            if user_input:
                token = user_input
                # Save to .env
                with open(ENV_PATH, "w", encoding="utf-8") as f:
                    f.write(f"TELEGRAM_BOT_TOKEN={token}\n")
                print(f"✅ Saved token to {ENV_PATH}")
            else:
                print("Aborted.")
                return
        except KeyboardInterrupt:
            return

    print(f"\n[*] Testing Token: {token[:8]}...{token[-4:]}")
    url = f"https://api.telegram.org/bot{token}/getMe"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "TelegramDiagnostic/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            res = json.loads(r.read())
            if res.get("ok"):
                bot_info = res["result"]
                username = bot_info.get("username")
                first_name = bot_info.get("first_name")
                print(f"✅ CONNECTION SUCCESSFUL!")
                print(f"   • Bot Name     : {first_name}")
                print(f"   • Bot Username : @{username}")
                print(f"   • Bot ID       : {bot_info.get('id')}")
                print("\n📱 Next Step:")
                print(f"   1. Open Telegram on your phone or PC.")
                print(f"   2. Search for: @{username}")
                print(f"   3. Send: /start")
                print("=" * 65)
            else:
                print(f"❌ Telegram API returned error: {res}")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print("\n❌ ERROR 401: Unauthorized!")
            print("   The token you entered is INVALID.")
            print("   Please open Telegram, chat with @BotFather, send /mybots, and copy your API token.")
        else:
            print(f"\n❌ HTTP Error {e.code}: {e.reason}")
    except Exception as e:
        print(f"\n❌ Network / Connection Error: {e}")
        print("   Check if your VPS has internet access and can reach https://api.telegram.org")


if __name__ == "__main__":
    main()
