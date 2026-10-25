import unittest
from app.strategies.engine import StrategyEngine, StockContext


class TestStrategyEngine(unittest.TestCase):

    def setUp(self):
        self.engine = StrategyEngine()

    # --- 1. Bullish WATCH Tests ---

    def test_bullish_watch_true(self):
        """Bullish WATCH condition: 9:15_OPEN < PD_LOW and 9:15_CLOSE >= PD_HIGH * (1 - 0.001)"""
        # PD_HIGH = 500, PD_LOW = 480
        # 9:15_OPEN = 475 (< 480), 9:15_CLOSE = 500 (>= 499.5)
        ctx = StockContext(
            symbol="TEST_BULL_WATCH",
            current=505.0,
            volume=250000,
            pd_high=500.0,
            pd_low=480.0,
            open_915=475.0,
            high_915=502.0,
            low_915=474.0,
            close_915=500.0,
        )
        res = self.engine.evaluate(ctx)
        self.assertTrue(res["bullish_watch"])
        self.assertFalse(res["bearish_watch"])
        self.assertEqual(res["watch_status"], "🟢 WATCH")
        self.assertIn("BULLISH WATCH", res["special_bullish"])

    def test_bullish_watch_false_open_not_below_pd_low(self):
        # 9:15_OPEN = 485 (NOT < 480)
        ctx = StockContext(
            symbol="TEST_FAIL_OPEN",
            current=505.0,
            volume=250000,
            pd_high=500.0,
            pd_low=480.0,
            open_915=485.0,
            high_915=502.0,
            low_915=480.0,
            close_915=500.0,
        )
        res = self.engine.evaluate(ctx)
        self.assertFalse(res["bullish_watch"])
        self.assertIsNone(res["watch_status"])

    def test_bullish_watch_false_close_below_tolerance(self):
        # PD_HIGH = 500.0, threshold is 500 * 0.999 = 499.5
        # 9:15_CLOSE = 499.0 (< 499.5)
        ctx = StockContext(
            symbol="TEST_FAIL_CLOSE",
            current=505.0,
            volume=250000,
            pd_high=500.0,
            pd_low=480.0,
            open_915=475.0,
            high_915=502.0,
            low_915=474.0,
            close_915=499.0,
        )
        res = self.engine.evaluate(ctx)
        self.assertFalse(res["bullish_watch"])

    def test_bullish_watch_tolerance_boundary(self):
        # Exactly at boundary: 1000 * 0.999 = 999.0
        ctx_exact = StockContext(
            pd_high=1000.0, pd_low=950.0, open_915=940.0, close_915=999.0, current=1005.0, volume=150000
        )
        self.assertTrue(self.engine.evaluate(ctx_exact)["bullish_watch"])

        # Just below boundary: 998.99
        ctx_below = StockContext(
            pd_high=1000.0, pd_low=950.0, open_915=940.0, close_915=998.99, current=1005.0, volume=150000
        )
        self.assertFalse(self.engine.evaluate(ctx_below)["bullish_watch"])

    # --- 2. Bearish WATCH Tests ---

    def test_bearish_watch_true(self):
        """Bearish WATCH condition: 9:15_OPEN > PD_HIGH and 9:15_CLOSE <= PD_LOW * (1 + 0.001)"""
        # PD_HIGH = 500, PD_LOW = 480
        # 9:15_OPEN = 510 (> 500), 9:15_CLOSE = 480 (<= 480.48)
        ctx = StockContext(
            symbol="TEST_BEAR_WATCH",
            current=475.0,
            volume=250000,
            pd_high=500.0,
            pd_low=480.0,
            open_915=510.0,
            high_915=512.0,
            low_915=478.0,
            close_915=480.0,
        )
        res = self.engine.evaluate(ctx)
        self.assertTrue(res["bearish_watch"])
        self.assertFalse(res["bullish_watch"])
        self.assertEqual(res["watch_status"], "🔴 WATCH")
        self.assertIn("BEARISH WATCH", res["special_bearish"])

    def test_bearish_watch_false_open_not_above_pd_high(self):
        # 9:15_OPEN = 495 (NOT > 500)
        ctx = StockContext(
            pd_high=500.0, pd_low=480.0, open_915=495.0, close_915=480.0, current=475.0, volume=200000
        )
        res = self.engine.evaluate(ctx)
        self.assertFalse(res["bearish_watch"])

    def test_bearish_watch_false_close_above_tolerance(self):
        # PD_LOW = 1000.0, threshold is 1000 * 1.001 = 1001.0
        # 9:15_CLOSE = 1002.0 (> 1001.0)
        ctx = StockContext(
            pd_high=1100.0, pd_low=1000.0, open_915=1110.0, close_915=1002.0, current=990.0, volume=200000
        )
        res = self.engine.evaluate(ctx)
        self.assertFalse(res["bearish_watch"])

    def test_bearish_watch_tolerance_boundary(self):
        # Exactly at boundary: 1000 * 1.001 = 1001.0
        ctx_exact = StockContext(
            pd_high=1100.0, pd_low=1000.0, open_915=1110.0, close_915=1001.0, current=990.0, volume=200000
        )
        self.assertTrue(self.engine.evaluate(ctx_exact)["bearish_watch"])

        # Just above boundary: 1001.05
        ctx_above = StockContext(
            pd_high=1100.0, pd_low=1000.0, open_915=1110.0, close_915=1001.05, current=990.0, volume=200000
        )
        self.assertFalse(self.engine.evaluate(ctx_above)["bearish_watch"])

    # --- 3. Intraday SPIKE / DUMP Tests ---

    def test_spike_signal(self):
        # SPIKE: CURRENT > HIGH_915 AND CURRENT > PD_HIGH AND PERCENT_CHANGE > 0
        ctx = StockContext(
            current=520.0,
            volume=300000,
            pd_high=500.0,
            pd_low=480.0,
            open_915=490.0,
            high_915=510.0,
            low_915=488.0,
            close_915=505.0,
        )
        res = self.engine.evaluate(ctx)
        self.assertEqual(res["signal"], "🔥 SPIKE")
        self.assertIn("INTRADAY SPIKE", res["special_bullish"])

    def test_dump_signal(self):
        # DUMP: CURRENT < LOW_915 AND CURRENT < PD_LOW AND PERCENT_CHANGE < 0
        ctx = StockContext(
            current=470.0,
            volume=300000,
            pd_high=500.0,
            pd_low=480.0,
            open_915=490.0,
            high_915=510.0,
            low_915=475.0,
            close_915=478.0,
        )
        res = self.engine.evaluate(ctx)
        self.assertEqual(res["signal"], "🚨 DUMP")
        self.assertIn("INTRADAY DUMP", res["special_bearish"])

    def test_no_signal_when_levels_not_broken(self):
        ctx = StockContext(
            current=495.0,  # between PD_LOW (480) and PD_HIGH (500)
            volume=200000,
            pd_high=500.0,
            pd_low=480.0,
            open_915=490.0,
            high_915=502.0,
            low_915=485.0,
            close_915=492.0,
        )
        res = self.engine.evaluate(ctx)
        self.assertEqual(res["signal"], "-")

    # --- 4. Live Market Teacher Action Tests ---

    def test_low_volume_avoid(self):
        ctx = StockContext(current=100.0, volume=50000, open_915=95.0, close_915=98.0)
        res = self.engine.evaluate(ctx)
        self.assertEqual(res["action"], "🟠 LOW VOLUME / AVOID")

    def test_bull_aligned_action(self):
        # Bull side & %chg > 0 & price > close_915
        ctx = StockContext(
            current=105.0, volume=200000, open_915=100.0, close_915=102.0
        )
        res = self.engine.evaluate(ctx)
        self.assertEqual(res["action"], "🟢 BULL ALIGNED")

    def test_bear_aligned_action(self):
        # Bear side & %chg < 0 & price < close_915
        ctx = StockContext(
            current=92.0, volume=200000, open_915=100.0, close_915=95.0
        )
        res = self.engine.evaluate(ctx)
        self.assertEqual(res["action"], "🔴 BEAR ALIGNED")

    def test_bull_conflict_action(self):
        # Bull side but price is below close_915
        ctx = StockContext(
            current=99.0, volume=200000, open_915=98.0, close_915=102.0
        )
        res = self.engine.evaluate(ctx)
        self.assertEqual(res["action"], "⚠️ BULL SIDE CONFLICT")

    # --- 5. Missing / Invalid Reference Data Handling ---

    def test_missing_reference_data_graceful(self):
        ctx = StockContext(current=100.0, volume=200000)
        res = self.engine.evaluate(ctx)
        self.assertFalse(res["has_reference_data"])
        self.assertFalse(res["bullish_watch"])
        self.assertFalse(res["bearish_watch"])
        self.assertIsNone(res["signal"])
        self.assertIsNone(res["watch_status"])


if __name__ == "__main__":
    unittest.main()

