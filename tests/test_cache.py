import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.market_cache import MarketCache
from app.market_data.groww import GrowwService


class TestMarketCache(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        # Create a fresh MarketCache instance with memory fallback for test isolation
        self.cache = MarketCache()
        # Clear test keys
        await self.cache.clear("sq:test:*")

    async def asyncTearDown(self):
        await self.cache.clear("sq:test:*")

    async def test_cache_miss_and_hit(self):
        """Verify cache miss invokes fetcher, and subsequent call hits cache without calling fetcher."""
        fetcher = AsyncMock(return_value={"symbol": "WIPRO", "price": 189.84})
        key = "sq:test:quote:WIPRO"

        # 1. First call -> Cache MISS
        data1, is_stale1 = await self.cache.get_or_fetch(key, fetcher, ttl=10)
        self.assertEqual(data1["price"], 189.84)
        self.assertFalse(is_stale1)
        self.assertEqual(fetcher.call_count, 1)

        # 2. Second call -> Cache HIT
        data2, is_stale2 = await self.cache.get_or_fetch(key, fetcher, ttl=10)
        self.assertEqual(data2["price"], 189.84)
        self.assertFalse(is_stale2)
        # Fetcher was NOT called again!
        self.assertEqual(fetcher.call_count, 1)

        metrics = await self.cache.get_metrics()
        self.assertEqual(metrics["hits"], 1)
        self.assertEqual(metrics["misses"], 1)
        self.assertEqual(metrics["api_calls_saved"], 1)
        self.assertAlmostEqual(metrics["hit_ratio"], 0.5, places=2)

    async def test_ttl_expiration(self):
        """Verify cached item expires after its TTL duration."""
        fetcher = AsyncMock(side_effect=[
            {"price": 100.0},
            {"price": 101.5},
        ])
        key = "sq:test:ttl:TCS"

        # 1. Fetch with short TTL of 1 second
        data1, _ = await self.cache.get_or_fetch(key, fetcher, ttl=1)
        self.assertEqual(data1["price"], 100.0)
        self.assertEqual(fetcher.call_count, 1)

        # Immediate check -> Cache HIT
        data_cached, _ = await self.cache.get_or_fetch(key, fetcher, ttl=1)
        self.assertEqual(data_cached["price"], 100.0)
        self.assertEqual(fetcher.call_count, 1)

        # Wait for TTL to expire (1.1 seconds)
        await asyncio.sleep(1.1)

        # Post-TTL check -> Cache MISS, re-invokes fetcher
        data2, _ = await self.cache.get_or_fetch(key, fetcher, ttl=1)
        self.assertEqual(data2["price"], 101.5)
        self.assertEqual(fetcher.call_count, 2)

    async def test_groww_api_failure_stale_fallback(self):
        """Verify that when Groww API fails, stale fallback data is returned with isStale=True."""
        key = "sq:test:live:RELIANCE"
        fallback_key = "sq:test:last_known:RELIANCE"

        # 1. Successful initial fetch populates both primary and fallback cache
        good_fetcher = AsyncMock(return_value={"symbol": "RELIANCE", "price": 1190.0, "lastUpdated": "2026-10-23T15:30:00+05:30"})
        data1, is_stale1 = await self.cache.get_or_fetch(key, good_fetcher, ttl=1, fallback_key=fallback_key)
        self.assertEqual(data1["price"], 1190.0)
        self.assertFalse(is_stale1)

        # Wait for primary live cache to expire
        await asyncio.sleep(1.1)

        # 2. Next call: Groww API fails (e.g. rate limit, 502, network failure)
        bad_fetcher = AsyncMock(side_effect=Exception("Groww 503 Service Unavailable"))
        data2, is_stale2 = await self.cache.get_or_fetch(key, bad_fetcher, ttl=1, fallback_key=fallback_key)

        # Stale fallback should be returned gracefully without raising an exception!
        self.assertTrue(is_stale2)
        self.assertEqual(data2["price"], 1190.0)
        self.assertTrue(data2["isStale"])
        self.assertIn("Groww API temporarily unavailable", data2["staleReason"])
        self.assertEqual(data2["lastUpdated"], "2026-10-23T15:30:00+05:30")

        metrics = await self.cache.get_metrics()
        self.assertGreaterEqual(metrics["stale_hits"], 1)

    async def test_redis_unavailable_graceful_fallback(self):
        """Verify cache continues to function seamlessly in in-memory mode when Redis is offline."""
        key = "sq:test:inmem:INFY"
        fetcher = AsyncMock(return_value={"symbol": "INFY", "price": 1920.0})

        # Simulate Redis becoming completely unreachable
        self.cache._redis_available = False
        self.cache._redis_client = None

        # 1. First call -> Cache MISS, stored in memory
        data1, is_stale1 = await self.cache.get_or_fetch(key, fetcher, ttl=5)
        self.assertEqual(data1["price"], 1920.0)
        self.assertEqual(fetcher.call_count, 1)

        # 2. Second call -> Cache HIT from in-memory fallback
        data2, is_stale2 = await self.cache.get_or_fetch(key, fetcher, ttl=5)
        self.assertEqual(data2["price"], 1920.0)
        self.assertEqual(fetcher.call_count, 1)

        # Application did not crash and served correctly!
        self.assertIn(key, self.cache._memory_cache)

    async def test_concurrent_requests_single_flight(self):
        """
        Verify Single-Flight coalescing: 20 simultaneous concurrent requests
        for the same cache key result in EXACTLY ONE broker API call.
        """
        key = "sq:test:concurrent:HDFCBANK"
        call_count = 0

        async def slow_fetcher():
            nonlocal call_count
            call_count += 1
            # Simulate 50ms network round-trip to Groww
            await asyncio.sleep(0.05)
            return {"symbol": "HDFCBANK", "price": 1650.0}

        # Fire 20 simultaneous requests at the exact same instant
        tasks = [self.cache.get_or_fetch(key, slow_fetcher, ttl=5) for _ in range(20)]
        results = await asyncio.gather(*tasks)

        # Every single caller received the correct data
        for data, is_stale in results:
            self.assertEqual(data["price"], 1650.0)
            self.assertFalse(is_stale)

        # The fetcher was called EXACTLY ONCE! (19 calls saved)
        self.assertEqual(call_count, 1)

        metrics = await self.cache.get_metrics()
        self.assertGreaterEqual(metrics["api_calls_saved"], 19)

    async def test_market_closed_ttl_and_metadata(self):
        """Verify that when Indian market is closed, extended TTL is applied and metadata is marked."""
        with patch("app.services.market_cache.is_market_open", return_value=False):
            ttl = self.cache._determine_ttl(base_live_ttl=2)
            # Market closed TTL should be at least 300s (5 minutes)
            self.assertGreaterEqual(ttl, 300)

        with patch("app.services.market_cache.is_market_open", return_value=True):
            ttl = self.cache._determine_ttl(base_live_ttl=2)
            # Market open TTL should be 2s
            self.assertEqual(ttl, 2)

    async def test_batch_prices_partial_cache_miss(self):
        """Verify batch prices fetches only missing symbols and combines cached ones."""
        symbols = ["TEST_WIPRO", "TEST_TCS", "TEST_INFY"]
        for s in symbols:
            await self.cache.delete(f"sq:price:NSE:{s}:CASH")
            await self.cache.delete(f"sq:last_known:price:NSE:{s}:CASH")

        # Pre-cache TEST_WIPRO
        wipro_key = "sq:price:NSE:TEST_WIPRO:CASH"
        await self.cache.set(wipro_key, {"symbol": "TEST_WIPRO", "price": 190.0, "previousClose": 190.41}, ttl=10)

        # Fetcher should only receive missing symbols (TEST_TCS, TEST_INFY)
        received_missing = []

        async def mock_batch_fetcher(missing_symbols):
            nonlocal received_missing
            received_missing = list(missing_symbols)
            return {
                "prices": {
                    "TEST_TCS": {"symbol": "TEST_TCS", "price": 2530.0, "previousClose": 2506.9},
                    "TEST_INFY": {"symbol": "TEST_INFY", "price": 1850.0, "previousClose": 1840.0},
                }
            }

        res = await self.cache.get_batch_prices_cached(
            symbols=symbols,
            exchange="NSE",
            segment="CASH",
            fetcher=mock_batch_fetcher,
        )

        # TEST_WIPRO was not in missing list
        self.assertNotIn("TEST_WIPRO", received_missing)
        self.assertIn("TEST_TCS", received_missing)
        self.assertIn("TEST_INFY", received_missing)

        # Result contains all 3 symbols!
        self.assertEqual(len(res["prices"]), 3)
        self.assertEqual(res["prices"]["TEST_WIPRO"]["price"], 190.0)
        self.assertEqual(res["prices"]["TEST_TCS"]["price"], 2530.0)
        self.assertEqual(res["prices"]["TEST_INFY"]["price"], 1850.0)

    async def test_groww_service_integration(self):
        """Verify GrowwService.get_quote_cached and get_indices_cached use MarketCache."""
        sym = "TEST_INTEG_STOCK"
        await self.cache.delete(f"sq:quote:NSE:{sym}:CASH")
        await self.cache.delete(f"sq:last_known:quote:NSE:{sym}:CASH")

        service = GrowwService(None, cache=self.cache)
        service.ensure_authenticated = MagicMock()
        mock_groww = MagicMock()
        mock_groww.get_quote.return_value = {
            "last_price": 2500.0,
            "ohlc": {"open": 2480.0, "high": 2520.0, "low": 2470.0, "close": 2490.0},
            "volume": 123456,
        }
        service.groww = mock_groww

        # 1. First call -> Cache MISS
        q1 = await service.get_quote_cached(sym)
        self.assertEqual(q1["price"], 2500.0)
        self.assertEqual(mock_groww.get_quote.call_count, 1)

        # 2. Second call -> Cache HIT
        q2 = await service.get_quote_cached(sym)
        self.assertEqual(q2["price"], 2500.0)
        self.assertEqual(mock_groww.get_quote.call_count, 1)


if __name__ == "__main__":
    unittest.main()
