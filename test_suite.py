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

        # Scalp: Candle body < 35% (indecision doji) should fail
        scalp_doji = risk_engine.validate_strategy_accuracy("SCALP", "GOLD", 2740.0, atr=28.0, rsi=52.0, adx=24.0, levels=mock_levels, trap_type="CLEAN", upper_wick_pct=10.0, candle_body_pct=25.0)
        self.assertFalse(scalp_doji["passed"])
        self.assertIn("Indecision Candle Body", scalp_doji["veto_reasons"][0])

        scalp_good = risk_engine.validate_strategy_accuracy("SCALP", "GOLD", 2740.0, atr=28.0, rsi=52.0, adx=24.0, levels=mock_levels, trap_type="CLEAN", upper_wick_pct=10.0, candle_body_pct=60.0)
        self.assertTrue(scalp_good["passed"])

        # Swing: Directional flow alignment (+DI vs -DI)
        swing_bear_di = risk_engine.validate_strategy_accuracy("SWING", "GOLD", 2740.0, atr=28.0, rsi=52.0, adx=28.0, levels=mock_levels, trap_type="CLEAN", plus_di=15.0, minus_di=30.0, action="BUY")
        self.assertFalse(swing_bear_di["passed"])
        self.assertIn("Bearish Directional Flow", swing_bear_di["veto_reasons"][0])

        # Session & Rollover intelligence
        from datetime import datetime
        dt_rollover = datetime(2026, 10, 28, 22, 5)
        dt_overlap = datetime(2026, 10, 28, 14, 0)
        sess_roll = risk_engine.get_market_session(dt_rollover)
        sess_over = risk_engine.get_market_session(dt_overlap)
        self.assertTrue(sess_roll["is_rollover"])
        self.assertEqual(sess_roll["badge"], "🚨")
        self.assertTrue(sess_over["is_golden_overlap"])
        self.assertEqual(sess_over["badge"], "🌟")

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
        orig_mode = risk_engine.safety_manager.get_trading_mode()
        risk_engine.safety_manager.set_trading_mode("DEMO")  # Routes to MT5 to verify broker disconnected behavior
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

        risk_engine.safety_manager.set_trading_mode(orig_mode)
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

            # Quantitative Backtest Hub
            "/backtest",
            "/backtest gold scalp 90",

            # Priority 1 Safety & Trading Mode Hubs
            "/mode",
            "/mode paper",
            "/mode demo",
            "/mode live",
            "/enable_live CONFIRM",
            "/confirm_trade YES",
            "/safety",
            "/kill",
            "/kill_reset CONFIRM",

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

    def test_06_safety_modes_and_confirmations(self):
        """Verify strict PAPER | DEMO | LIVE modes and double confirmation."""
        print("\n[*] 6. Testing Strict Trading Modes & Confirmations...")
        sm = risk_engine.safety_manager

        # Mode switching
        ok, msg = sm.set_trading_mode("PAPER")
        self.assertTrue(ok)
        self.assertEqual(sm.get_trading_mode(), "PAPER")

        ok, msg = sm.set_trading_mode("DEMO")
        self.assertTrue(ok)
        self.assertEqual(sm.get_trading_mode(), "DEMO")

        # LIVE without confirmation MUST fail
        ok, msg = sm.set_trading_mode("LIVE", "")
        self.assertFalse(ok)
        self.assertIn("confirmation", msg.lower())

        # LIVE with CONFIRM succeeds
        ok, msg = sm.set_trading_mode("LIVE", "CONFIRM")
        self.assertTrue(ok)
        self.assertEqual(sm.get_trading_mode(), "LIVE")

        # In LIVE mode, first trade of day requires confirmation
        sm.state["first_trade_confirmed_date"] = ""
        self.assertFalse(sm.is_first_trade_confirmed_today())
        ok, msg = sm.confirm_first_trade_today()
        self.assertTrue(ok)
        self.assertTrue(sm.is_first_trade_confirmed_today())

        # Reset back to PAPER mode for test safety
        sm.set_trading_mode("PAPER")
        print("    ✅ Strict Trading Modes & Confirmations: ALL PASSED")

    def test_07_circuit_breakers_and_kill_switch(self):
        """Verify daily loss limit, max concurrent positions, max risk, and hard kill-switch."""
        print("\n[*] 7. Testing Multi-Layer Circuit Breakers & Kill-Switch...")
        sm = risk_engine.safety_manager

        # 1. Kill-Switch
        sm.trigger_kill_switch("Test Kill Switch")
        is_active, reason = sm.is_kill_switch_active()
        self.assertTrue(is_active)
        self.assertIn("Test Kill Switch", reason)

        # Trade check while kill-switch is active MUST fail
        safe, msg = sm.check_trade_safety("GOLD", proposed_risk_pct=0.5)
        self.assertFalse(safe)
        self.assertIn("Kill-Switch", msg)

        # Reset kill-switch without CONFIRM fails
        ok, msg = sm.reset_kill_switch("")
        self.assertFalse(ok)
        ok, msg = sm.reset_kill_switch("CONFIRM")
        self.assertTrue(ok)
        is_active, _ = sm.is_kill_switch_active()
        self.assertFalse(is_active)

        # 2. Max Concurrent Open Positions (limit: 2)
        mock_positions = [{"symbol": "XAUUSD", "risk_pct": 0.5}, {"symbol": "BTCUSD", "risk_pct": 0.5}]
        safe, msg = sm.check_trade_safety("GOLD", proposed_risk_pct=0.5, open_positions=mock_positions)
        self.assertFalse(safe)
        self.assertIn("Max Concurrent Open Positions", msg)

        # 3. Max Total Open Risk (limit: 2.5%)
        mock_heavy_risk = [{"symbol": "XAUUSD", "risk_pct": 2.2}]
        safe, msg = sm.check_trade_safety("BTC", proposed_risk_pct=0.5, open_positions=mock_heavy_risk)
        self.assertFalse(safe)
        self.assertIn("Max Combined Portfolio Risk", msg)

        # 4. Daily Loss Circuit Breaker (-2.0% halt)
        sm.state["daily_circuit_breaker_tripped"] = False
        sm.state["realized_daily_pnl"] = 0.0
        sm.state["starting_daily_equity"] = 10000.0
        sm.record_pnl(-250.0)  # -2.5% loss > 2.0% limit
        self.assertTrue(sm.state["daily_circuit_breaker_tripped"])
        safe, msg = sm.check_trade_safety("GOLD", proposed_risk_pct=0.5, open_positions=[])
        self.assertFalse(safe)
        self.assertIn("Daily Loss Circuit Breaker", msg)

        # Reset for subsequent tests
        sm.state["daily_circuit_breaker_tripped"] = False
        sm.state["realized_daily_pnl"] = 0.0
        print("    ✅ Multi-Layer Circuit Breakers & Kill-Switch: ALL PASSED")

    def test_08_stale_data_spread_slippage_and_audit(self):
        """Verify stale data protection, spread/slippage guards, paper execution, and audit logger."""
        print("\n[*] 8. Testing Stale Data, Spread/Slippage Guards & Paper Trading...")
        sm = risk_engine.safety_manager
        import time

        # 1. Stale Data Guard (>15 minutes old quote)
        stale_time = time.time() - 1000  # >900s
        safe, msg = sm.check_trade_safety("GOLD", proposed_risk_pct=0.5, open_positions=[], data_timestamp=stale_time)
        self.assertFalse(safe)
        self.assertIn("Stale Market Data", msg)

        # Fresh data succeeds
        fresh_time = time.time() - 30
        safe, msg = sm.check_trade_safety("GOLD", proposed_risk_pct=0.5, open_positions=[], data_timestamp=fresh_time)
        self.assertTrue(safe)

        # 2. Spread Guard: excessive spread (e.g. $1.50 for Gold > $0.60 limit)
        safe, msg = sm.check_trade_safety("GOLD", proposed_risk_pct=0.5, open_positions=[], spread_val=1.50, sl_dist=4.0)
        self.assertFalse(safe)
        self.assertIn("Excessive Broker Spread", msg)

        # 3. Slippage Guard:
        is_ok, slip, msg = sm.verify_fill_slippage("GOLD", requested_price=2740.0, fill_price=2740.20)
        self.assertTrue(is_ok)
        self.assertEqual(slip, 0.20)

        is_ok, slip, msg = sm.verify_fill_slippage("GOLD", requested_price=2740.0, fill_price=2742.00)  # $2.00 > $0.80
        self.assertFalse(is_ok)
        self.assertEqual(slip, 2.00)

        # 4. Paper Trading Execution & Audit Logging
        paper_order = sm.execute_paper_order(
            asset="GOLD", action="BUY", price=2740.0,
            stop_loss=2736.0, tp1=2745.0, tp2=2748.0,
            lots=0.10, risk_usd=40.0, risk_pct=0.50,
            strategy="SCALP", score=8
        )
        self.assertTrue(paper_order["success"])
        self.assertIn("PAPER-", paper_order["ticket"])

        # Check paper positions
        paper_positions = sm.get_paper_positions()
        self.assertGreaterEqual(len(paper_positions), 1)

        # Close paper position
        close_res = sm.close_paper_position(paper_order["ticket"], exit_price=2744.0)
        self.assertTrue(close_res["success"])
        self.assertGreater(close_res["closed_pnl"], 0.0)

        # Check audit log file exists and has records
        self.assertTrue(os.path.exists(sm.audit_file))
        with open(sm.audit_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        self.assertGreater(len(lines), 0)
        self.assertIn("ORDER_PLACED", lines[-2] if len(lines) >= 2 else lines[-1])

        # 5. Dashboard text
        dash = sm.get_safety_dashboard_text()
        self.assertIn("SAFETY & RISK CONTROLLER DASHBOARD", dash)
        self.assertIn("Trading Mode", dash)
        self.assertIn("Kill-Switch", dash)
        print("    ✅ Stale Data, Spread/Slippage Guards & Paper Audit: ALL PASSED")


if __name__ == "__main__":
    unittest.main()
