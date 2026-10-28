#!/usr/bin/env python3
"""
test_suite.py
Automated End-to-End Bug Detection & Command Verification Test Harness.
Tests all 30+ Telegram commands and modern hubs, MT5 execution engine,
trailing stop & breakeven protection, multi-strategy calculations (SCALP, SWING, BALANCE, SWAP),
auto-leverage margin controls, separate watchlist auto-trading, and chart generation.
"""

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
import unittest
import warnings
warnings.filterwarnings("ignore")

# Change directory to project root
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

import mt5_executor
import risk_engine
import chart_generator
import autotrader_pipeline
import self_learning
import telegram_bot


class MockTelegramSender:
    def __init__(self):
        self.sent_messages = []
        self.sent_charts = []

    def send_message(self, token, chat_id, text, reply_markup=None):
        self.sent_messages.append((chat_id, text))
        return {"ok": True, "result": {"message_id": len(self.sent_messages)}}

    def send_telegram_chart(self, token, chat_id, photo_buf, caption=""):
        self.sent_charts.append((chat_id, caption, photo_buf))
        return {"ok": True, "result": {"message_id": len(self.sent_charts)}}


class TestHardAssetProject(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        print("\n" + "=" * 70)
        print("  🧪 RUNNING COMPREHENSIVE PROJECT VERIFICATION TEST SUITE")
        print("=" * 70)
        cls.mock_tg = MockTelegramSender()
        telegram_bot.send_message = cls.mock_tg.send_message
        telegram_bot.send_telegram_chart = cls.mock_tg.send_telegram_chart

    def test_01_risk_engine_and_strategies(self):
        """Verify dynamic lot sizing, broker leverage margin limits, and all 4 strategies."""
        print("\n[*] 1. Testing Risk Engine & Multi-Strategy Matrix...")

        # 1. Test Gold Lot Sizing
        gold_lot = risk_engine.calculate_lot_size("GOLD", entry_price=2740.0, stop_loss_price=2735.0, account_balance=10000.0, risk_pct=1.0)
        self.assertTrue(gold_lot["valid"])
        self.assertEqual(gold_lot["lots"], 0.20)
        self.assertAlmostEqual(gold_lot["actual_risk_usd"], 100.0, delta=1.0)

        # 2. Test BTC Lot Sizing
        btc_lot = risk_engine.calculate_lot_size("BTC", entry_price=67500.0, stop_loss_price=67000.0, account_balance=10000.0, risk_pct=1.0)
        self.assertTrue(btc_lot["valid"])
        self.assertEqual(btc_lot["lots"], 0.20)
        self.assertAlmostEqual(btc_lot["actual_risk_usd"], 100.0, delta=1.0)

        # 3. Test Auto Leverage & Free Margin Capping
        capped_lot = risk_engine.calculate_lot_size(
            "GOLD", entry_price=2740.0, stop_loss_price=2735.0,
            account_balance=10000.0, risk_pct=1.0,
            broker_leverage=10, margin_free=500.0  # low leverage & tight margin
        )
        self.assertTrue(capped_lot["valid"])
        self.assertLessEqual(capped_lot["lots"], 0.05)

        # 4. Test Strategy Calculations for all 4 profiles (SCALP, SWING, BALANCE, SWAP)
        mock_levels = {"fib_500": 2748.0, "fib_618": 2738.0, "fib_650": 2736.0, "in_golden_pocket": True, "ma50": 2720.0, "ma200": 2680.0}
        for s_code in ("SCALP", "SWING", "BALANCE", "SWAP"):
            calc = risk_engine.calculate_strategy_levels("GOLD", 2740.0, atr=28.0, action="BUY", strategy=s_code, account_balance=10000.0, levels=mock_levels)
            self.assertEqual(calc["strategy"], s_code)
            self.assertGreater(calc["tp1"], calc["entry"])
            self.assertLess(calc["stop_loss"], calc["entry"])
            self.assertGreater(calc["tp2"], calc["tp1"])
            self.assertGreater(calc["lot_size"], 0.0)
            self.assertIn("breakeven_r", calc)
            self.assertIn("trail_start_r", calc)
            self.assertIn("trail_step_r", calc)
            if s_code == "BALANCE":
                self.assertEqual(calc["tp1"], 2748.0)  # Pinned to 0.50 Fib Equilibrium

        # 5. Test Strategy Accuracy Verification Engine
        # Scalp: Rejection wick >= 25% should fail
        scalp_bad = risk_engine.validate_strategy_accuracy("SCALP", "GOLD", 2740.0, atr=28.0, rsi=52.0, adx=24.0, levels=mock_levels, trap_type="CLEAN", upper_wick_pct=35.0)
        self.assertFalse(scalp_bad["passed"])
        self.assertIn("Rejection Wick", scalp_bad["veto_reasons"][0])

        scalp_good = risk_engine.validate_strategy_accuracy("SCALP", "GOLD", 2740.0, atr=28.0, rsi=52.0, adx=24.0, levels=mock_levels, trap_type="CLEAN", upper_wick_pct=10.0)
        self.assertTrue(scalp_good["passed"])

        # Swing: ADX < 20 (chop) should fail
        swing_bad = risk_engine.validate_strategy_accuracy("SWING", "GOLD", 2740.0, atr=28.0, rsi=52.0, adx=15.0, levels=mock_levels, trap_type="CLEAN")
        self.assertFalse(swing_bad["passed"])
        self.assertIn("Chop", swing_bad["veto_reasons"][0])

        swing_good = risk_engine.validate_strategy_accuracy("SWING", "GOLD", 2740.0, atr=28.0, rsi=52.0, adx=28.0, levels=mock_levels, trap_type="CLEAN")
        self.assertTrue(swing_good["passed"])

        # Balance: ADX > 28 (strong trend) should fail
        bal_bad = risk_engine.validate_strategy_accuracy("BALANCE", "GOLD", 2740.0, atr=28.0, rsi=52.0, adx=35.0, levels=mock_levels, trap_type="CLEAN")
        self.assertFalse(bal_bad["passed"])
        self.assertIn("Trend Breakout", bal_bad["veto_reasons"][0])

        bal_good = risk_engine.validate_strategy_accuracy("BALANCE", "GOLD", 2740.0, atr=28.0, rsi=52.0, adx=18.0, levels=mock_levels, trap_type="CLEAN")
        self.assertTrue(bal_good["passed"])

        # 6. Verify strategy switching
        risk_engine.set_active_strategy("SWING")
        self.assertEqual(risk_engine.get_active_strategy()["code"], "SWING")
        risk_engine.set_active_strategy("SCALP")  # Reset to default
        self.assertEqual(risk_engine.get_active_strategy()["code"], "SCALP")

        # 7. Test Risk Audit Text Generation
        audit_text = risk_engine.generate_risk_audit_text(account_balance=10000.0, risk_pct=1.0)
        self.assertIn("Portfolio Equity", audit_text)
        self.assertIn("Daily Circuit Breaker", audit_text)
        print("    ✅ Risk Engine & Multi-Strategy Matrix: ALL TESTS PASSED")

    def test_02_mt5_executor_and_trailing(self):
        """Verify MT5 executor handles disconnected state gracefully and trailing methods exist."""
        print("\n[*] 2. Testing MT5 Executor (Disconnected Handling & Trailing Protection)...")
        broker = mt5_executor.MT5LiveBroker()
        self.assertFalse(broker.is_connected)

        # Account data when disconnected
        acc = broker.get_live_account_data()
        self.assertIsNone(acc)

        # Order execution when disconnected
        res = broker.execute_live_sniper_order("GOLD", "BUY", 2740.0, 2735.0, 2746.0, 0.05)
        self.assertFalse(res["success"])
        self.assertIn("disconnected", res["error"].lower())

        # Positions when disconnected
        positions = broker.get_open_positions()
        self.assertEqual(positions, [])

        # Close all when disconnected
        close_res = broker.close_all_positions()
        self.assertFalse(close_res["success"])

        # Trailing positions when disconnected
        self.assertIn("SCALP", broker.TRAIL_PROFILES)
        self.assertIn("SWING", broker.TRAIL_PROFILES)
        self.assertIn("BALANCE", broker.TRAIL_PROFILES)
        self.assertIn("SWAP", broker.TRAIL_PROFILES)
        trail_events = broker.trail_positions(default_strategy="SWING")
        self.assertEqual(trail_events, [])

        # Position modification when disconnected
        mod_res = broker.modify_position_sltp(ticket=12345, new_sl=2740.0, new_tp=2755.0)
        self.assertFalse(mod_res["success"])

        # Swap rates when disconnected
        swaps = broker.get_swap_rates("GOLD")
        self.assertFalse(swaps["available"])

        print("    ✅ MT5 Executor Disconnected Handling & Trailing: ALL TESTS PASSED")

    def test_03_chart_generation(self):
        """Verify MT5-style Candlestick Chart generation."""
        print("\n[*] 3. Testing Visual MT5 Candlestick Chart Generation...")
        btc_buf = chart_generator.generate_mt5_chart("BTC-USD", "BITCOIN (BTC-USD)", lookback_bars=30)
        self.assertIsNotNone(btc_buf)
        self.assertGreater(len(btc_buf.getvalue()), 10000)

        gold_buf = chart_generator.generate_mt5_chart("GC=F", "GOLD (XAU/USD)", lookback_bars=30)
        self.assertIsNotNone(gold_buf)
        self.assertGreater(len(gold_buf.getvalue()), 10000)
        print("    ✅ Chart Generator (BTC & Gold PNGs): ALL TESTS PASSED")

    def test_04_pipeline_and_learning_engine(self):
        """Verify deterministic pipeline and self-learning engine integration."""
        print("\n[*] 4. Testing Pipeline & Self-Learning Engine...")
        data = telegram_bot.run_full_pipeline()
        self.assertIsNotNone(data)
        self.assertIn("macro", data)
        self.assertIn("btc", data)
        self.assertIn("gold", data)

        btc = data["btc"]
        self.assertIn("price", btc)
        self.assertIn("levels", btc)
        self.assertIn("lot_info", btc)
        self.assertIn("verdict", btc)

        gold = data["gold"]
        self.assertIn("price", gold)
        self.assertIn("levels", gold)
        self.assertIn("lot_info", gold)
        self.assertIn("verdict", gold)
        print(f"    ✅ Pipeline Data: BTC=${btc['price']:,.2f} | Gold=${gold['price']:,.2f}")

    def test_05_all_telegram_commands_and_hubs(self):
        """Simulate sending each Telegram command directly to process_telegram_command and verify responses."""
        print("\n[*] 5. Testing All Modern Command Hubs & Shortcuts...")
        token = "MOCK_TOKEN"
        sender_id = "12345678"
        sender_name = "TestTrader"

        # Comprehensive test matrix of modern hubs + subcommands + shortcuts
        test_commands = [
            # Welcome & Help
            "/start",
            "/help",
            "/menu",

            # Modern Market Hub & Subcommands
            "/market",
            "/market all",
            "/market btc",
            "/market gold",
            "/market macro",
            "/market levels",
            "/market traps",
            "/market debate",

            # Market Shortcuts
            "/scan",
            "/btc",
            "/gold",
            "/macro",
            "/levels",
            "/traps",
            "/debate",

            # Modern Trade Hub & Subcommands
            "/trade",
            "/trade buy gold",
            "/trade sell gold",
            "/trade buy btc",
            "/trade sell btc",
            "/trade close",
            "/trade auto gold",
            "/trade auto btc",
            "/trade auto both",
            "/trade auto off",

            # Trade Shortcuts
            "/buy_gold",
            "/sell_gold",
            "/buy_btc",
            "/sell_btc",
            "/close_all",
            "/auto_trade",
            "/auto_trade on",
            "/auto_trade off",

            # Modern Strategy Hub
            "/strategy",
            "/strategy scalp",
            "/strategy swing",
            "/strategy balance",
            "/strategy swap",

            # Modern Portfolio Hub & Shortcuts
            "/portfolio",
            "/account",
            "/positions",

            # Modern Trailing Hub
            "/trail",
            "/trail on",
            "/trail off",

            # Self-Learning Hub
            "/learn",
            "/learn train",
            "/train",

            # Risk Hub
            "/risk",
            "/risk 25000",

            # Status Hub
            "/status"
        ]

        for cmd in test_commands:
            self.mock_tg.sent_messages.clear()
            self.mock_tg.sent_charts.clear()

            # Execute via actual production dispatcher
            telegram_bot.process_telegram_command(token, sender_id, sender_name, cmd)

            self.assertGreater(len(self.mock_tg.sent_messages), 0, f"Command '{cmd}' produced no Telegram message!")
            resp_len = len(self.mock_tg.sent_messages[0][1])
            self.assertGreater(resp_len, 10, f"Response for '{cmd}' too short ({resp_len} chars)!")
            print(f"    • Command '{cmd:<22}' ──► Handled successfully ({resp_len} chars)")

        # Verify state persistence from commands
        # 1. Watchlist mode
        telegram_bot.process_telegram_command(token, sender_id, sender_name, "/trade auto gold")
        self.assertEqual(telegram_bot.AUTO_TRADE_MODE, "GOLD")
        self.assertTrue(telegram_bot.AUTO_TRADE_LIVE)

        telegram_bot.process_telegram_command(token, sender_id, sender_name, "/trade auto btc")
        self.assertEqual(telegram_bot.AUTO_TRADE_MODE, "BTC")
        self.assertTrue(telegram_bot.AUTO_TRADE_LIVE)

        telegram_bot.process_telegram_command(token, sender_id, sender_name, "/trade auto both")
        self.assertEqual(telegram_bot.AUTO_TRADE_MODE, "BOTH")
        self.assertTrue(telegram_bot.AUTO_TRADE_LIVE)

        telegram_bot.process_telegram_command(token, sender_id, sender_name, "/trade auto off")
        self.assertEqual(telegram_bot.AUTO_TRADE_MODE, "OFF")
        self.assertFalse(telegram_bot.AUTO_TRADE_LIVE)

        # 2. Trailing stop toggle
        telegram_bot.process_telegram_command(token, sender_id, sender_name, "/trail off")
        self.assertFalse(telegram_bot.TRAILING_STOP_ENABLED)
        telegram_bot.process_telegram_command(token, sender_id, sender_name, "/trail on")
        self.assertTrue(telegram_bot.TRAILING_STOP_ENABLED)

        # 3. Strategy switcher
        telegram_bot.process_telegram_command(token, sender_id, sender_name, "/strategy swing")
        self.assertEqual(risk_engine.get_active_strategy()["code"], "SWING")
        telegram_bot.process_telegram_command(token, sender_id, sender_name, "/strategy scalp")
        self.assertEqual(risk_engine.get_active_strategy()["code"], "SCALP")

        print("    ✅ All Modern Hubs, Subcommands, Shortcuts & State Transitions Verified!")


if __name__ == "__main__":
    unittest.main()
