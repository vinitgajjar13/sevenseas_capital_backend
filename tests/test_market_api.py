import unittest
from unittest.mock import MagicMock
from app.market_data.groww import GrowwService

class TestMarketAPI(unittest.TestCase):

    def test_quote_enrichment_when_closed(self):
        service = GrowwService(None)
        service.ensure_authenticated = MagicMock()
        mock_groww = MagicMock()
        mock_groww.get_quote.return_value = {
            "last_price": 189.84,
            "day_change": -0.57,
            "day_change_perc": -0.30,
            "ohlc": {"open": 194.5, "high": 197.25, "low": 188.63, "close": 190.41},
            "volume": 27680351,
            "week_52_high": 273.1,
            "week_52_low": 156.79,
        }
        service.groww = mock_groww

        res = service.get_quote("WIPRO")
        self.assertEqual(res["trading_symbol"], "WIPRO")
        self.assertEqual(res["price"], 189.84)
        self.assertEqual(res["previousClose"], 190.41)
        self.assertIn(res["marketStatus"], ["OPEN", "CLOSED"])
        self.assertIn(res["priceType"], ["LIVE", "LAST_CLOSE"])
        self.assertIsNotNone(res["lastUpdated"])

    def test_indices_structure(self):
        service = GrowwService(None)
        service.ensure_authenticated = MagicMock()
        mock_groww = MagicMock()
        mock_groww.get_quote.side_effect = [
            # NIFTY
            {"last_price": 22600.0, "ohlc": {"close": 22687.65, "open": 22742.2, "high": 22787.25, "low": 22372.0}},
            # BANKNIFTY
            {"last_price": 54287.35, "ohlc": {"close": 54925.7, "open": 54965.75, "high": 54990.5, "low": 53942.35}},
            # SENSEX
            {"last_price": 73123.83, "ohlc": {"close": 73249.39, "open": 73665.64, "high": 73766.51, "low": 72452.37}},
        ]
        service.groww = mock_groww

        indices = service.get_indices()
        self.assertIn("nifty50", indices["indices"])
        self.assertIn("bankNifty", indices["indices"])
        self.assertIn("sensex", indices["indices"])

        nifty = indices["indices"]["nifty50"]
        self.assertEqual(nifty["price"], 22600.0)
        self.assertEqual(nifty["previousClose"], 22687.65)
        self.assertAlmostEqual(nifty["change"], -87.65, places=2)

    def test_unavailable_data_does_not_fabricate_zero(self):
        service = GrowwService(None)
        service.ensure_authenticated = MagicMock()
        mock_groww = MagicMock()
        # Symbol fails or returns None
        mock_groww.get_quote.side_effect = Exception("Symbol not found on exchange")
        service.groww = mock_groww

        indices = service.get_indices()
        # When an index fails, its price must be None, NOT 0.0 or fabricated!
        for k, v in indices["indices"].items():
            self.assertIsNone(v["price"])
            self.assertIsNone(v["previousClose"])

    def test_market_overview_and_radar_compatibility(self):
        """Verify /api/v1/market/overview and /api/v1/market/radar responses have all required strategy fields."""
        from unittest.mock import patch, AsyncMock
        from fastapi.testclient import TestClient
        from app.main import app

        with patch("app.main.groww.get_batch_prices_cached", new_callable=AsyncMock) as mock_batch, \
             patch("app.main.groww.get_ohlc_cached", new_callable=AsyncMock) as mock_ohlc:

            mock_batch.return_value = {
                "ltp": {"NSE_BHEL": 425.0, "NSE_MFSL": 1450.0}
            }
            mock_ohlc.return_value = {
                "NSE_BHEL": {"open": 418.0, "high": 426.0, "low": 417.0, "close": 415.0, "volume": 500000},
                "NSE_MFSL": {"open": 1400.0, "high": 1460.0, "low": 1395.0, "close": 1410.0, "volume": 300000},
            }

            with TestClient(app) as client:
                # 1. Test /api/v1/market/overview
                res = client.get("/api/v1/market/overview?limit=5")
                self.assertEqual(res.status_code, 200)
                data = res.json()

                # Verify top-level structure
                for expected_key in ("source", "updated_at", "total_stocks", "advances", "declines", "sectors", "stocks"):
                    self.assertIn(expected_key, data)

                # Verify strategy summary keys
                self.assertIn("bullish_watch_count", data)
                self.assertIn("bearish_watch_count", data)
                self.assertIn("spike_count", data)
                self.assertIn("dump_count", data)

                # Verify stock item strategy fields
                if data["stocks"]:
                    stock = data["stocks"][0]
                    # Preserved backward-compatible fields
                    for field in ("id", "symbol", "name", "sector", "ltp", "change", "change_percent", "volume"):
                        self.assertIn(field, stock)
                    # New strategy fields
                    for field in ("bullish_watch", "bearish_watch", "signal", "action", "strategy_state", "has_reference_data"):
                        self.assertIn(field, stock)

                # Verify sector item strategy fields
                if data["sectors"]:
                    sector = data["sectors"][0]
                    for field in ("sector", "total", "advances", "declines", "average_change_percent", "direction", "score", "top_bullish_stocks", "top_bearish_stocks"):
                        self.assertIn(field, sector)

                # 2. Test /api/v1/market/radar
                radar_res = client.get("/api/v1/market/radar")
                self.assertEqual(radar_res.status_code, 200)
                radar_data = radar_res.json()
                for key in ("market_status", "price_type", "summary", "top_bullish_sectors", "top_bearish_sectors", "sectors", "watch_stocks", "spike_dump_stocks", "teacher_guidance"):
                    self.assertIn(key, radar_data)


if __name__ == "__main__":
    unittest.main()

