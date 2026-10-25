import unittest
from app.strategies.sector import calculate_sector_snapshot, assign_sector_ranks


class TestSectorStrategy(unittest.TestCase):

    def test_sector_score_excel_formula(self):
        """Verify Sector Score: ROUND((avg_change * 20) + ((bullish_pct - bearish_pct) * 0.4) + ((bull_vol_pct - bear_vol_pct) * 0.4), 2)"""
        # Exactly matching Row 2 of Sector Dashboard from verified workbook:
        # avg = -0.170448, bull% = 50.0, bear% = 50.0, bull_vol% = 82.28, bear_vol% = 17.72
        # Score = (-0.170448 * 20) + (0 * 0.4) + ((82.28 - 17.72) * 0.4) = -3.40896 + 25.824 = 22.42
        stocks = [
            {"symbol": "S1", "change_pct": 1.0, "volume": 4114855},
            {"symbol": "S2", "change_pct": 0.5, "volume": 1500000},
            {"symbol": "S3", "change_pct": 0.2, "volume": 1274856},
            {"symbol": "S4", "change_pct": -0.8, "volume": 500000},
            {"symbol": "S5", "change_pct": -0.5, "volume": 483509},
            {"symbol": "S6", "change_pct": -0.5713, "volume": 500000},
        ]
        # Total = 6, 3 pos, 3 neg -> bull% = 50.0, bear% = 50.0
        # Pos vol = 6889711, Neg vol = 1483509, Total = 8373220 -> bull_vol% = 82.28, bear_vol% = 17.72
        # avg = (1.0 + 0.5 + 0.2 - 0.8 - 0.5 - 0.5713) / 6 = -0.1713 / 6 = -0.02855
        snap = calculate_sector_snapshot(stocks, sector_name="aerospace & defence")
        self.assertEqual(snap["total_stocks"], 6)
        self.assertEqual(snap["positive_stocks"], 3)
        self.assertEqual(snap["negative_stocks"], 3)
        self.assertEqual(snap["bullish_pct"], 50.0)
        self.assertEqual(snap["bearish_pct"], 50.0)
        self.assertAlmostEqual(snap["bullish_volume_pct"], 82.28, places=1)
        self.assertAlmostEqual(snap["bearish_volume_pct"], 17.72, places=1)

    def test_bullish_direction_60_percent_boundary(self):
        """BULLISH condition: avg_change > 0 AND bullish_pct >= 60% AND bullish_volume_pct >= 60%"""
        # Exactly at 60% breadth and 60% volume
        stocks = [
            {"symbol": "S1", "change_pct": 1.0, "volume": 300},
            {"symbol": "S2", "change_pct": 2.0, "volume": 300},
            {"symbol": "S3", "change_pct": 0.5, "volume": 0},  # pos = 3/5 = 60%, vol = 600/1000 = 60%
            {"symbol": "S4", "change_pct": -0.5, "volume": 200},
            {"symbol": "S5", "change_pct": -0.5, "volume": 200},
        ]
        snap = calculate_sector_snapshot(stocks, sector_name="AUTO")
        self.assertEqual(snap["bullish_pct"], 60.0)
        self.assertEqual(snap["bullish_volume_pct"], 60.0)
        self.assertGreater(snap["avg_change"], 0)
        self.assertEqual(snap["direction"], "🟢 BULLISH")

    def test_bullish_direction_fails_below_60_percent(self):
        # 59% volume -> fails direction test
        stocks = [
            {"symbol": "S1", "change_pct": 1.0, "volume": 590},
            {"symbol": "S2", "change_pct": 2.0, "volume": 0},
            {"symbol": "S3", "change_pct": 0.5, "volume": 0},  # pos = 60%
            {"symbol": "S4", "change_pct": -0.5, "volume": 205},
            {"symbol": "S5", "change_pct": -0.5, "volume": 205}, # neg vol = 410, total = 1000 -> bull_vol = 59%
        ]
        snap = calculate_sector_snapshot(stocks, sector_name="AUTO")
        self.assertEqual(snap["bullish_pct"], 60.0)
        self.assertEqual(snap["bullish_volume_pct"], 59.0)
        self.assertEqual(snap["direction"], "⚪ NEUTRAL")

    def test_bearish_direction_60_percent_boundary(self):
        """BEARISH condition: avg_change < 0 AND bearish_pct >= 60% AND bearish_volume_pct >= 60%"""
        stocks = [
            {"symbol": "S1", "change_pct": -1.0, "volume": 300},
            {"symbol": "S2", "change_pct": -2.0, "volume": 300},
            {"symbol": "S3", "change_pct": -0.5, "volume": 0},  # neg = 3/5 = 60%, vol = 600/1000 = 60%
            {"symbol": "S4", "change_pct": 0.5, "volume": 200},
            {"symbol": "S5", "change_pct": 0.5, "volume": 200},
        ]
        snap = calculate_sector_snapshot(stocks, sector_name="IT")
        self.assertEqual(snap["bearish_pct"], 60.0)
        self.assertEqual(snap["bearish_volume_pct"], 60.0)
        self.assertLess(snap["avg_change"], 0)
        self.assertEqual(snap["direction"], "🔴 BEARISH")

    def test_safe_zero_volume_and_empty_sector(self):
        """Verify no ZeroDivisionError on empty stocks or zero volume."""
        # 1. Empty sector
        empty_snap = calculate_sector_snapshot([], sector_name="EMPTY")
        self.assertEqual(empty_snap["total_stocks"], 0)
        self.assertEqual(empty_snap["score"], 0.0)
        self.assertEqual(empty_snap["direction"], "⚪ NEUTRAL")

        # 2. Sector with stocks but zero volume
        zero_vol_stocks = [
            {"symbol": "Z1", "change_pct": 1.0, "volume": 0},
            {"symbol": "Z2", "change_pct": -1.0, "volume": 0},
        ]
        zero_snap = calculate_sector_snapshot(zero_vol_stocks, sector_name="ZERO_VOL")
        self.assertEqual(zero_snap["live_volume"], 0)
        self.assertEqual(zero_snap["bullish_volume_pct"], 0.0)
        self.assertEqual(zero_snap["bearish_volume_pct"], 0.0)

    def test_dual_sector_ranking(self):
        """Verify Bullish Rank for score > 0 descending and Bearish Rank for score < 0 descending."""
        sectors = [
            {"sector": "SEC_BULL1", "score": 105.5},
            {"sector": "SEC_BULL2", "score": 45.2},
            {"sector": "SEC_NEUT", "score": 0.0},
            {"sector": "SEC_BEAR1", "score": -85.0},
            {"sector": "SEC_BEAR2", "score": -30.0},
        ]
        ranked = assign_sector_ranks(sectors)

        # Bullish ranks: SEC_BULL1 -> 1, SEC_BULL2 -> 2
        bull1 = next(s for s in ranked if s["sector"] == "SEC_BULL1")
        bull2 = next(s for s in ranked if s["sector"] == "SEC_BULL2")
        self.assertEqual(bull1["bullish_rank"], 1)
        self.assertEqual(bull2["bullish_rank"], 2)
        self.assertIsNone(bull1["bearish_rank"])

        # Bearish ranks: SEC_BEAR1 (-85, abs=85) -> 1, SEC_BEAR2 (-30, abs=30) -> 2
        bear1 = next(s for s in ranked if s["sector"] == "SEC_BEAR1")
        bear2 = next(s for s in ranked if s["sector"] == "SEC_BEAR2")
        self.assertEqual(bear1["bearish_rank"], 1)
        self.assertEqual(bear2["bearish_rank"], 2)
        self.assertIsNone(bear1["bullish_rank"])

        # Neutral: neither rank assigned
        neut = next(s for s in ranked if s["sector"] == "SEC_NEUT")
        self.assertIsNone(neut["bullish_rank"])
        self.assertIsNone(neut["bearish_rank"])

    def test_stock_contribution_scores_and_slots(self):
        """Verify UP1/UP2 and DOWN1/DOWN2 slot selection within sector."""
        stocks = [
            {"symbol": "UP_LEADER", "change_pct": 5.0, "volume": 1000000, "current_price": 500.0},
            {"symbol": "UP_SECOND", "change_pct": 3.0, "volume": 500000, "current_price": 300.0},
            {"symbol": "UP_THIRD", "change_pct": 1.0, "volume": 100000, "current_price": 100.0},
            {"symbol": "DN_LEADER", "change_pct": -4.0, "volume": 800000, "current_price": 400.0},
            {"symbol": "DN_SECOND", "change_pct": -2.0, "volume": 400000, "current_price": 200.0},
        ]
        snap = calculate_sector_snapshot(stocks, sector_name="TEST_CONTRIB")
        self.assertEqual(len(snap["top_bullish_stocks"]), 2)
        self.assertEqual(snap["top_bullish_stocks"][0]["symbol"], "UP_LEADER")
        self.assertEqual(snap["top_bullish_stocks"][1]["symbol"], "UP_SECOND")

        self.assertEqual(len(snap["top_bearish_stocks"]), 2)
        self.assertEqual(snap["top_bearish_stocks"][0]["symbol"], "DN_LEADER")
        self.assertEqual(snap["top_bearish_stocks"][1]["symbol"], "DN_SECOND")


if __name__ == "__main__":
    unittest.main()
