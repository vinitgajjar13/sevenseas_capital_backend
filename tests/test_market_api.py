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

if __name__ == "__main__":
    unittest.main()
