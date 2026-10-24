"""
Sevenseas Capital - High-Performance Redis Market Data Cache Service

Implements the Cache-Aside pattern with:
1. Short-lived live price caching (1-3s for live stock prices, 5-10s for indices).
2. Extended market-closed caching (5-10m) to eliminate redundant calls when markets are shut.
3. Single-Flight / Mutex coalescing per cache key to prevent concurrent dog-piling on Groww APIs.
4. Independent persistent storage for last-known valid prices (sq:last_known:*) retained for 7 days.
5. Automatic graceful fallback to in-memory TTL caching if Redis becomes unreachable (never crashes).
6. Stale data detection and explicit `isStale: True` tagging when serving fallback data.
7. Telemetry metrics (hits, misses, stale hits, hit ratio, saved Groww calls) without credential logging.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, TypeVar

import redis.asyncio as aioredis
from app.core.config import get_settings
from app.services.market_calendar import is_market_open, get_market_status, now_ist

logger = logging.getLogger(__name__)
T = TypeVar("T")


class MarketCache:
    """
    Enterprise-grade Market Data Cache implementing Cache-Aside with Single-Flight
    concurrency protection, multi-tier fallback, and market-hours-aware dynamic TTLs.
    """

    def __init__(self, redis_url: Optional[str] = None):
        self.settings = get_settings()
        self.redis_url = redis_url or self.settings.redis_url
        self._redis_client: Optional[aioredis.Redis] = None
        self._redis_available: bool = True
        self._last_reconnect_attempt: float = 0.0

        # In-memory fallback cache: {key: (data_json_or_obj, expire_at_timestamp)}
        self._memory_cache: Dict[str, Tuple[Any, float]] = {}

        # Single-Flight Mutex locks per cache key to coalesce concurrent in-flight requests
        self._locks: Dict[str, asyncio.Lock] = {}
        self._locks_lock = asyncio.Lock()

        # Telemetry metrics
        self._start_time = time.time()
        self._metrics = {
            "hits": 0,
            "misses": 0,
            "stale_hits": 0,
            "redis_errors": 0,
            "api_calls_saved": 0,
        }

        self._init_redis()

    def _init_redis(self):
        """Initialize Redis connection pool."""
        try:
            self._redis_client = aioredis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_timeout=2.0,
                socket_connect_timeout=2.0,
                retry_on_timeout=True,
            )
            self._redis_available = True
            logger.info("MarketCache initialized with Redis at %s", self.redis_url.split("@")[-1])
        except Exception as e:
            logger.warning("MarketCache failed to connect to Redis: %s. Using in-memory fallback.", e)
            self._redis_available = False
            self._redis_client = None

    async def _ensure_redis(self) -> Optional[aioredis.Redis]:
        """Check and return Redis client, attempting periodic reconnection if previously down."""
        if self._redis_available and self._redis_client is not None:
            return self._redis_client

        now = time.time()
        # Retry connection at most once every 15 seconds
        if now - self._last_reconnect_attempt > 15.0:
            self._last_reconnect_attempt = now
            try:
                if self._redis_client:
                    await self._redis_client.aclose()
                self._init_redis()
                if self._redis_client:
                    await self._redis_client.ping()
                    self._redis_available = True
                    logger.info("MarketCache successfully reconnected to Redis.")
                    return self._redis_client
            except Exception as e:
                self._redis_available = False
                logger.debug("Redis reconnection attempt failed: %s", e)

        return None

    def _get_lock(self, key: str) -> asyncio.Lock:
        """Get or create an asyncio.Lock for a specific cache key."""
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def _cleanup_locks(self):
        """Clean up unlocked locks periodically to avoid memory leak."""
        if len(self._locks) > 500:
            async with self._locks_lock:
                to_delete = [k for k, lock in self._locks.items() if not lock.locked()]
                for k in to_delete:
                    del self._locks[k]

    # --- Low-Level Cache Get / Set with Multi-Tier Fallback ---

    async def get(self, key: str) -> Optional[Any]:
        """Retrieve value from Redis or in-memory fallback."""
        if not self.settings.cache_enabled:
            return None

        # 1. Try Redis
        client = await self._ensure_redis()
        if client:
            try:
                raw = await client.get(key)
                if raw is not None:
                    try:
                        return json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        return raw
            except Exception as e:
                self._metrics["redis_errors"] += 1
                self._redis_available = False
                logger.warning("Redis GET error on key %s: %s. Switching to in-memory fallback.", key, e)

        # 2. In-memory fallback
        item = self._memory_cache.get(key)
        if item:
            val, expire_at = item
            if time.time() < expire_at:
                return val
            else:
                del self._memory_cache[key]

        return None

    async def set(self, key: str, value: Any, ttl: int) -> bool:
        """Store value in Redis and in-memory fallback with TTL."""
        if not self.settings.cache_enabled:
            return False

        serialized = json.dumps(value) if not isinstance(value, str) else value

        # 1. Always write to in-memory fallback
        self._memory_cache[key] = (value, time.time() + ttl)

        # 2. Try Redis
        client = await self._ensure_redis()
        if client:
            try:
                await client.set(key, serialized, ex=max(1, ttl))
                return True
            except Exception as e:
                self._metrics["redis_errors"] += 1
                self._redis_available = False
                logger.warning("Redis SET error on key %s: %s. Stored in memory.", key, e)

        return False

    async def delete(self, key: str) -> bool:
        """Delete key from Redis and in-memory cache."""
        self._memory_cache.pop(key, None)
        client = await self._ensure_redis()
        if client:
            try:
                await client.delete(key)
                return True
            except Exception:
                pass
        return False

    async def clear(self, pattern: str = "sq:*") -> int:
        """Clear matching keys from cache."""
        self._memory_cache.clear()
        client = await self._ensure_redis()
        deleted = 0
        if client:
            try:
                keys = await client.keys(pattern)
                if keys:
                    deleted = await client.delete(*keys)
            except Exception as e:
                logger.warning("Redis CLEAR error: %s", e)
        return deleted

    # --- Cache-Aside with Single-Flight Concurrency Protection ---

    async def get_or_fetch(
        self,
        key: str,
        fetcher: Callable[[], Awaitable[T]],
        ttl: int,
        fallback_key: Optional[str] = None,
        enrich_stale: bool = True,
    ) -> Tuple[T, bool]:
        """
        Execute Cache-Aside pattern with single-flight coalescing and stale-data fallback.

        Returns:
            Tuple[data, is_stale]
        """
        start_t = time.perf_counter()

        # Step 1: Fast cache check (Hot path)
        cached = await self.get(key)
        if cached is not None:
            self._metrics["hits"] += 1
            self._metrics["api_calls_saved"] += 1
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            logger.debug("Cache HIT [%s] (%.2f ms)", key, elapsed_ms)
            if isinstance(cached, dict) and "isStale" not in cached:
                cached["isStale"] = False
            return cached, False

        # Step 2: Cache Miss -> Single-Flight Mutex per Key
        lock = self._get_lock(key)
        async with lock:
            # Double-check cache inside lock: another concurrent coroutine may have populated it
            cached = await self.get(key)
            if cached is not None:
                self._metrics["hits"] += 1
                self._metrics["api_calls_saved"] += 1
                elapsed_ms = (time.perf_counter() - start_t) * 1000.0
                logger.debug("Cache HIT (coalesced) [%s] (%.2f ms)", key, elapsed_ms)
                if isinstance(cached, dict) and "isStale" not in cached:
                    cached["isStale"] = False
                return cached, False

            # Step 3: Still a miss -> Fetch from external Groww API
            self._metrics["misses"] += 1
            try:
                fresh_data = await fetcher()
                elapsed_ms = (time.perf_counter() - start_t) * 1000.0
                logger.info("Cache MISS [%s] -> fetched fresh data in %.2f ms (TTL: %ds)", key, elapsed_ms, ttl)

                if fresh_data is not None:
                    # Save in primary cache with configured TTL
                    await self.set(key, fresh_data, ttl=ttl)

                    # Also update persistent long-lived fallback key (retained for 7 days)
                    if fallback_key:
                        await self.set(fallback_key, fresh_data, ttl=self.settings.cache_stale_retention)

                    if isinstance(fresh_data, dict):
                        fresh_data["isStale"] = False

                return fresh_data, False

            except Exception as exc:
                # Step 4: Groww API failed! Attempt Stale Fallback
                if fallback_key:
                    stale_data = await self.get(fallback_key)
                    if stale_data is not None:
                        self._metrics["stale_hits"] += 1
                        logger.warning(
                            "Groww API call failed for [%s]: %s. Serving STALE fallback from [%s].",
                            key,
                            exc,
                            fallback_key,
                        )
                        if enrich_stale and isinstance(stale_data, dict):
                            stale_data["isStale"] = True
                            stale_data["staleReason"] = f"Groww API temporarily unavailable: {type(exc).__name__}"
                        return stale_data, True

                # If no stale fallback available, re-raise the exception
                logger.error("Groww API call failed for [%s]: %s (no stale data available)", key, exc)
                raise exc
            finally:
                await self._cleanup_locks()

    # --- High-Level Market Data Cache Methods ---

    def _determine_ttl(self, base_live_ttl: int) -> int:
        """
        Dynamically determine TTL based on Indian market calendar status:
        - When market is open: use fast responsive live TTL (e.g. 1-5s).
        - When market is closed (weekend, holiday, night): use extended TTL (e.g. 300s)
          to eliminate redundant broker API calls completely.
        """
        if is_market_open():
            return base_live_ttl
        return max(self.settings.cache_ttl_market_closed, base_live_ttl)

    async def get_quote_cached(
        self,
        symbol: str,
        exchange: str,
        segment: str,
        fetcher: Callable[[], Awaitable[dict]],
    ) -> dict:
        """Cache-aside for single stock quote."""
        clean_symbol = symbol.strip().upper()
        clean_exchange = exchange.strip().upper()
        clean_segment = segment.strip().upper()

        key = f"sq:quote:{clean_exchange}:{clean_symbol}:{clean_segment}"
        fallback_key = f"sq:last_known:quote:{clean_exchange}:{clean_symbol}:{clean_segment}"

        ttl = self._determine_ttl(self.settings.cache_ttl_live_price)
        data, is_stale = await self.get_or_fetch(
            key=key,
            fetcher=fetcher,
            ttl=ttl,
            fallback_key=fallback_key,
            enrich_stale=True,
        )

        if isinstance(data, dict):
            status = get_market_status()
            data.setdefault("marketStatus", status["marketStatus"])
            data.setdefault("priceType", status["priceType"])
            data["isStale"] = is_stale

        return data

    async def get_indices_cached(
        self,
        fetcher: Callable[[], Awaitable[dict]],
    ) -> dict:
        """Cache-aside for benchmark market indices (NIFTY 50, BANK NIFTY, SENSEX)."""
        key = "sq:indices"
        fallback_key = "sq:last_known:indices"

        ttl = self._determine_ttl(self.settings.cache_ttl_indices)
        data, is_stale = await self.get_or_fetch(
            key=key,
            fetcher=fetcher,
            ttl=ttl,
            fallback_key=fallback_key,
            enrich_stale=True,
        )

        if isinstance(data, dict):
            status = get_market_status()
            data.setdefault("marketStatus", status["marketStatus"])
            data.setdefault("priceType", status["priceType"])
            data["isStale"] = is_stale
            if "indices" in data and isinstance(data["indices"], dict):
                for idx in data["indices"].values():
                    if isinstance(idx, dict):
                        idx["isStale"] = is_stale

        return data

    async def get_batch_prices_cached(
        self,
        symbols: List[str],
        exchange: str,
        segment: str,
        fetcher: Callable[[List[str]], Awaitable[dict]],
    ) -> dict:
        """
        Cache-aside for batch stock prices / quotes.
        Checks individual symbol cache entries and only fetches missing symbols from Groww.
        """
        clean_symbols = list(dict.fromkeys(s.strip().upper() for s in symbols if s and s.strip()))
        if not clean_symbols:
            status = get_market_status()
            return {
                "marketStatus": status["marketStatus"],
                "priceType": status["priceType"],
                "lastUpdated": now_ist().isoformat(),
                "prices": {},
                "quotes": {},
                "ltp": {},
                "isStale": False,
            }

        clean_exchange = exchange.strip().upper()
        clean_segment = segment.strip().upper()
        ttl = self._determine_ttl(self.settings.cache_ttl_live_price)

        cached_quotes = {}
        missing_symbols = []

        # 1. Check cache for each symbol
        for sym in clean_symbols:
            key = f"sq:price:{clean_exchange}:{sym}:{clean_segment}"
            cached_item = await self.get(key)
            if cached_item is not None:
                cached_quotes[sym] = cached_item
            else:
                missing_symbols.append(sym)

        self._metrics["hits"] += len(cached_quotes)
        self._metrics["api_calls_saved"] += len(cached_quotes)

        # 2. Fetch missing symbols in batch
        newly_fetched = {}
        batch_is_stale = False

        if missing_symbols:
            self._metrics["misses"] += len(missing_symbols)
            # Use lock for missing batch to prevent simultaneous multi-symbol spam
            batch_key = f"sq:batch:{clean_exchange}:{','.join(sorted(missing_symbols))}"
            lock = self._get_lock(batch_key)
            async with lock:
                try:
                    fetch_res = await fetcher(missing_symbols)
                    new_quotes = fetch_res.get("prices") or fetch_res.get("quotes") or {}
                    for sym, quote_data in new_quotes.items():
                        clean_sym = sym.strip().upper()
                        newly_fetched[clean_sym] = quote_data
                        # Store in primary cache
                        item_key = f"sq:price:{clean_exchange}:{clean_sym}:{clean_segment}"
                        await self.set(item_key, quote_data, ttl=ttl)
                        # Store in long-lived fallback cache
                        fallback_key = f"sq:last_known:price:{clean_exchange}:{clean_sym}:{clean_segment}"
                        await self.set(fallback_key, quote_data, ttl=self.settings.cache_stale_retention)

                except Exception as exc:
                    # Groww failed for missing symbols -> fallback to last-known
                    logger.warning("Batch fetch failed for %d symbols: %s. Using stale fallback.", len(missing_symbols), exc)
                    batch_is_stale = True
                    for sym in missing_symbols:
                        fallback_key = f"sq:last_known:price:{clean_exchange}:{sym}:{clean_segment}"
                        stale_quote = await self.get(fallback_key)
                        if stale_quote:
                            self._metrics["stale_hits"] += 1
                            if isinstance(stale_quote, dict):
                                stale_quote["isStale"] = True
                            newly_fetched[sym] = stale_quote

        # 3. Merge cached + newly fetched quotes
        all_quotes = {}
        ltp_map = {}
        for sym in clean_symbols:
            q = newly_fetched.get(sym) or cached_quotes.get(sym)
            if q:
                all_quotes[sym] = q
                price = q.get("price") or q.get("ltp")
                if price is not None:
                    ltp_map[f"{clean_exchange}_{sym}"] = price

        status = get_market_status()
        last_updated = (
            now_ist().isoformat()
            if status["marketStatus"] == "OPEN"
            else f"{status['lastTradingSessionDate']}T15:30:00+05:30"
        )

        return {
            "marketStatus": status["marketStatus"],
            "priceType": status["priceType"],
            "lastUpdated": last_updated,
            "isStale": batch_is_stale,
            "prices": all_quotes,
            "quotes": all_quotes,
            "ltp": ltp_map,
        }

    async def get_ohlc_cached(
        self,
        symbols: List[str],
        exchange: str,
        segment: str,
        fetcher: Callable[[List[str]], Awaitable[dict]],
    ) -> dict:
        """Cache-aside for day's OHLC."""
        clean_symbols = sorted(list(dict.fromkeys(s.strip().upper() for s in symbols if s and s.strip())))
        key = f"sq:ohlc:{exchange.upper()}:{','.join(clean_symbols)}:{segment.upper()}"
        fallback_key = f"sq:last_known:ohlc:{exchange.upper()}:{','.join(clean_symbols)}:{segment.upper()}"

        ttl = self._determine_ttl(self.settings.cache_ttl_ohlc)
        data, is_stale = await self.get_or_fetch(
            key=key,
            fetcher=lambda: fetcher(clean_symbols),
            ttl=ttl,
            fallback_key=fallback_key,
            enrich_stale=True,
        )
        return data

    async def historical_cached(
        self,
        symbol: str,
        start_time: str,
        end_time: str,
        candle_interval: str,
        exchange: str,
        segment: str,
        fetcher: Callable[[], Awaitable[dict]],
    ) -> dict:
        """Cache-aside for historical candles."""
        clean_symbol = symbol.strip().upper()
        key = f"sq:hist:{exchange.upper()}:{clean_symbol}:{candle_interval}:{start_time}:{end_time}:{segment.upper()}"
        fallback_key = f"sq:last_known:hist:{exchange.upper()}:{clean_symbol}:{candle_interval}:{segment.upper()}"

        ttl = self.settings.cache_ttl_historical
        data, is_stale = await self.get_or_fetch(
            key=key,
            fetcher=fetcher,
            ttl=ttl,
            fallback_key=fallback_key,
            enrich_stale=True,
        )
        return data

    # --- Telemetry & Metrics ---

    async def get_metrics(self) -> Dict[str, Any]:
        """Collect cache performance telemetry and hit/miss ratios."""
        total_requests = self._metrics["hits"] + self._metrics["misses"]
        hit_ratio = round((self._metrics["hits"] / total_requests), 4) if total_requests > 0 else 0.0

        mem_used = None
        keys_count = None
        client = await self._ensure_redis()
        if client:
            try:
                info = await client.info("memory")
                mem_used = info.get("used_memory_human")
                keyspace = await client.info("keyspace")
                db0 = keyspace.get("db0", {})
                keys_count = db0.get("keys") if isinstance(db0, dict) else None
            except Exception:
                pass

        return {
            "hits": self._metrics["hits"],
            "misses": self._metrics["misses"],
            "stale_hits": self._metrics["stale_hits"],
            "redis_errors": self._metrics["redis_errors"],
            "api_calls_saved": self._metrics["api_calls_saved"],
            "hit_ratio": hit_ratio,
            "redis_available": self._redis_available,
            "redis_memory_used": mem_used,
            "keys_count": keys_count or len(self._memory_cache),
            "uptime_seconds": round(time.time() - self._start_time, 2),
        }


# Global singleton instance
_cache_instance: Optional[MarketCache] = None


def get_market_cache() -> MarketCache:
    """Retrieve shared MarketCache singleton."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = MarketCache()
    return _cache_instance
