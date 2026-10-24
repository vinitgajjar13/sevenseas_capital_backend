from app.services.market_cache import get_market_cache, MarketCache
from app.services.market_calendar import get_market_status, now_ist, is_market_open
import asyncio
import pyotp
from datetime import datetime, timezone
from typing import Any, Optional
from growwapi import GrowwAPI, GrowwFeed
from growwapi.groww.feed import get_data_dict
from app.core.config import get_settings

FeedConstants = GrowwFeed._get_topics.__globals__["FeedConstants"]


class GrowwService:
    def __init__(self, publisher=None, cache: Optional[Any] = None):
        self.settings = get_settings()
        self.publisher = publisher
        self.cache = cache or get_market_cache()
        self.groww: Optional[GrowwAPI] = None
        self.feed: Optional[GrowwFeed] = None
        self.access_token: Optional[str] = None
        self.authenticated_at: Optional[datetime] = None
        self.user_profile: Optional[dict[str, Any]] = None

    def authenticate(self, force: bool = False) -> dict[str, Any]:
        """Authenticate with Groww API using GROWW_TOTP_TOKEN and GROWW_TOTP_SECRET from settings/.env."""
        if self.groww and not force and self.authenticated_at:
            return {
                "status": "connected",
                "message": "Already authenticated",
                "ucc": self.user_profile.get("ucc") if self.user_profile else None,
                "vendor_user_id": self.user_profile.get("vendor_user_id") if self.user_profile else None,
                "authenticated_at": self.authenticated_at,
                "active_segments": self.user_profile.get("active_segments") if self.user_profile else None,
            }

        if not self.settings.groww_totp_token:
            raise RuntimeError("GROWW_TOTP_TOKEN is not configured in .env")

        if not self.settings.groww_totp_secret:
            raise RuntimeError("GROWW_TOTP_SECRET is not configured in .env")

        totp = pyotp.TOTP(self.settings.groww_totp_secret).now()

        self.access_token = GrowwAPI.get_access_token(
            api_key=self.settings.groww_totp_token,
            totp=totp,
        )

        self.groww = GrowwAPI(self.access_token)
        self.authenticated_at = datetime.now(timezone.utc)

        try:
            self.user_profile = self.groww.get_user_profile()
        except Exception:
            self.user_profile = {}

        return {
            "status": "connected",
            "message": "Authentication successful",
            "ucc": self.user_profile.get("ucc"),
            "vendor_user_id": self.user_profile.get("vendor_user_id"),
            "authenticated_at": self.authenticated_at,
            "active_segments": self.user_profile.get("active_segments"),
        }

    def ensure_authenticated(self):
        """Ensure client is authenticated before API calls."""
        if not self.groww:
            self.authenticate()

    def get_profile(self) -> dict[str, Any]:
        """Get user profile details."""
        self.ensure_authenticated()
        profile = self.groww.get_user_profile()
        self.user_profile = profile
        return profile

    def get_margins(self) -> dict[str, Any]:
        """Get available margins (cash, collateral, CNC/MIS, FnO)."""
        self.ensure_authenticated()
        return self.groww.get_available_margin_details()

    def get_holdings(self) -> dict[str, Any]:
        """Get user stock holdings."""
        self.ensure_authenticated()
        return self.groww.get_holdings_for_user()

    def get_positions(self) -> dict[str, Any]:
        """Get user positions."""
        self.ensure_authenticated()
        return self.groww.get_positions_for_user()

    def get_orders(self, segment: str = "CASH") -> dict[str, Any]:
        """Get order history for segment."""
        self.ensure_authenticated()
        return self.groww.get_order_list(segment=segment)

    def get_order_detail(self, groww_order_id: str, segment: str = "CASH") -> dict[str, Any]:
        """Get single order detail."""
        self.ensure_authenticated()
        return self.groww.get_order_detail(segment=segment, groww_order_id=groww_order_id)

    def place_order(
        self,
        trading_symbol: str,
        quantity: int,
        transaction_type: str,
        order_type: str = "MARKET",
        product: str = "CNC",
        price: float = 0.0,
        trigger_price: Optional[float] = None,
        validity: str = "DAY",
        exchange: str = "NSE",
        segment: str = "CASH",
    ) -> dict[str, Any]:
        """Place order via Groww API."""
        self.ensure_authenticated()
        return self.groww.place_order(
            validity=validity.upper(),
            exchange=exchange.upper(),
            order_type=order_type.upper(),
            product=product.upper(),
            quantity=quantity,
            segment=segment.upper(),
            trading_symbol=trading_symbol.upper(),
            transaction_type=transaction_type.upper(),
            price=price,
            trigger_price=trigger_price,
        )

    def cancel_order(self, groww_order_id: str, segment: str = "CASH") -> dict[str, Any]:
        """Cancel pending order."""
        self.ensure_authenticated()
        return self.groww.cancel_order(groww_order_id=groww_order_id, segment=segment)

    def get_quote(self, symbol: str, exchange: str = "NSE", segment: str = "CASH") -> dict[str, Any]:
        """Get complete real-time market quote (LTP, OHLC, 52w high/low, depth, volume) with live vs closing price metadata."""
        self.ensure_authenticated()
        clean_symbol = symbol.upper()
        if clean_symbol.startswith(f"{exchange.upper()}_"):
            clean_symbol = clean_symbol.replace(f"{exchange.upper()}_", "")
        if clean_symbol.startswith(f"{exchange.upper()}-"):
            clean_symbol = clean_symbol.replace(f"{exchange.upper()}-", "")

        quote = self.groww.get_quote(trading_symbol=clean_symbol, exchange=exchange.upper(), segment=segment.upper())
        status_info = get_market_status()

        price = quote.get("last_price")
        ohlc = quote.get("ohlc") or {}
        prev_close = ohlc.get("close")
        day_change = quote.get("day_change")
        if day_change is None and price is not None and prev_close is not None:
            day_change = round(price - prev_close, 2)
        day_change_perc = quote.get("day_change_perc")
        if day_change_perc is None and price is not None and prev_close is not None and prev_close > 0:
            day_change_perc = round(((price - prev_close) / prev_close) * 100, 2)

        last_updated = (
            now_ist().isoformat()
            if status_info["marketStatus"] == "OPEN"
            else f"{status_info['lastTradingSessionDate']}T15:30:00+05:30"
        )

        return {
            "trading_symbol": clean_symbol,
            "exchange": exchange.upper(),
            "segment": segment.upper(),
            "last_price": price,
            "price": price,
            "previousClose": prev_close,
            "day_change": day_change,
            "day_change_perc": day_change_perc,
            "marketStatus": status_info["marketStatus"],
            "priceType": status_info["priceType"],
            "lastUpdated": last_updated,
            "ohlc": ohlc,
            "depth": quote.get("depth"),
            "volume": quote.get("volume"),
            "week_52_high": quote.get("week_52_high"),
            "week_52_low": quote.get("week_52_low"),
            "raw": quote,
        }

    def get_indices(self) -> dict[str, Any]:
        """
        Fetch real benchmarks from Groww (NIFTY 50 on NSE, BANK NIFTY on NSE, SENSEX on BSE).
        Returns official closing prices when market is closed or live prices during market hours.
        """
        self.ensure_authenticated()
        status_info = get_market_status()
        last_updated = (
            now_ist().isoformat()
            if status_info["marketStatus"] == "OPEN"
            else f"{status_info['lastTradingSessionDate']}T15:30:00+05:30"
        )

        index_configs = [
            {"key": "nifty50", "name": "NIFTY 50", "symbol": "NIFTY", "exchange": "NSE"},
            {"key": "bankNifty", "name": "BANK NIFTY", "symbol": "BANKNIFTY", "exchange": "NSE"},
            {"key": "sensex", "name": "SENSEX", "symbol": "SENSEX", "exchange": "BSE"},
        ]

        indices_res = {}
        for cfg in index_configs:
            try:
                q = self.groww.get_quote(trading_symbol=cfg["symbol"], exchange=cfg["exchange"], segment="CASH")
                price = q.get("last_price")
                ohlc = q.get("ohlc") or {}
                prev_close = ohlc.get("close")
                day_change = q.get("day_change")
                if day_change is None and price is not None and prev_close is not None:
                    day_change = round(price - prev_close, 2)
                day_change_perc = q.get("day_change_perc")
                if day_change_perc is None and price is not None and prev_close is not None and prev_close > 0:
                    day_change_perc = round(((price - prev_close) / prev_close) * 100, 2)

                indices_res[cfg["key"]] = {
                    "name": cfg["name"],
                    "symbol": cfg["symbol"],
                    "price": price,
                    "previousClose": prev_close,
                    "change": day_change,
                    "changePercent": day_change_perc,
                    "open": ohlc.get("open"),
                    "high": ohlc.get("high"),
                    "low": ohlc.get("low"),
                    "week52High": q.get("week_52_high"),
                    "week52Low": q.get("week_52_low"),
                    "marketStatus": status_info["marketStatus"],
                    "priceType": status_info["priceType"],
                    "lastUpdated": last_updated,
                }
            except Exception as e:
                indices_res[cfg["key"]] = {
                    "name": cfg["name"],
                    "symbol": cfg["symbol"],
                    "price": None,
                    "previousClose": None,
                    "change": None,
                    "changePercent": None,
                    "marketStatus": status_info["marketStatus"],
                    "priceType": status_info["priceType"],
                    "lastUpdated": last_updated,
                }

        return {
            "marketStatus": status_info["marketStatus"],
            "priceType": status_info["priceType"],
            "lastUpdated": last_updated,
            "indices": indices_res,
        }

    def get_batch_prices(self, symbols: list[str], exchange: str = "NSE", segment: str = "CASH") -> dict[str, Any]:
        """
        Get batch quotes with structured live vs last close price metadata for each symbol.
        Preserves backward compatibility with LTP dictionary while adding quotes structure.
        """
        self.ensure_authenticated()
        status_info = get_market_status()
        last_updated = (
            now_ist().isoformat()
            if status_info["marketStatus"] == "OPEN"
            else f"{status_info['lastTradingSessionDate']}T15:30:00+05:30"
        )

        ltp_map = self.get_ltp(symbols=symbols, exchange=exchange, segment=segment)
        ohlc_map = self.get_ohlc(symbols=symbols, exchange=exchange, segment=segment)

        ex = exchange.upper()
        quotes = {}
        for s in symbols:
            clean_s = s.strip().upper()
            lookup_key = f"{ex}_{clean_s}"
            price = ltp_map.get(lookup_key) or ltp_map.get(clean_s)
            ohlc = ohlc_map.get(lookup_key) or ohlc_map.get(clean_s) or {}
            prev_close = ohlc.get("close")
            change = round(price - prev_close, 2) if price is not None and prev_close is not None else None
            change_perc = round(((price - prev_close) / prev_close) * 100, 2) if price is not None and prev_close is not None and prev_close > 0 else None

            quotes[clean_s] = {
                "symbol": clean_s,
                "price": price,
                "previousClose": prev_close,
                "change": change,
                "changePercent": change_perc,
                "open": ohlc.get("open"),
                "high": ohlc.get("high"),
                "low": ohlc.get("low"),
                "volume": None,
                "marketStatus": status_info["marketStatus"],
                "priceType": status_info["priceType"],
                "lastUpdated": last_updated,
            }

        return {
            "marketStatus": status_info["marketStatus"],
            "priceType": status_info["priceType"],
            "lastUpdated": last_updated,
            "ltp": ltp_map,
            "quotes": quotes,
            "prices": quotes,
        }

    def get_ltp(self, symbols: list[str], exchange: str = "NSE", segment: str = "CASH") -> dict[str, float]:
        """Get Last Traded Price for symbols."""
        self.ensure_authenticated()
        ex = exchange.upper()
        # Groww's LTP endpoint accepts up to 50 symbols per request.
        # Split larger screens into compliant batches and merge the responses.
        unique_symbols = list(dict.fromkeys(s.strip() for s in symbols if s and s.strip()))
        result: dict[str, float] = {}
        for offset in range(0, len(unique_symbols), 50):
            batch = unique_symbols[offset : offset + 50]
            formatted_symbols = tuple(
                f"{ex}_{s.upper()}" if not s.upper().startswith(f"{ex}_") else s.upper()
                for s in batch
            )
            result.update(
                self.groww.get_ltp(
                    exchange_trading_symbols=formatted_symbols,
                    segment=segment.upper(),
                )
            )
        return result

    def get_ohlc(self, symbols: list[str], exchange: str = "NSE", segment: str = "CASH") -> dict[str, Any]:
        """Get Day's OHLC for symbols."""
        self.ensure_authenticated()
        ex = exchange.upper()
        # Keep OHLC requests aligned with Groww's 50-symbol batch limit.
        unique_symbols = list(dict.fromkeys(s.strip() for s in symbols if s and s.strip()))
        result: dict[str, Any] = {}
        for offset in range(0, len(unique_symbols), 50):
            batch = unique_symbols[offset : offset + 50]
            formatted_symbols = tuple(
                f"{ex}_{s.upper()}" if not s.upper().startswith(f"{ex}_") else s.upper()
                for s in batch
            )
            result.update(
                self.groww.get_ohlc(
                    exchange_trading_symbols=formatted_symbols,
                    segment=segment.upper(),
                )
            )
        return result

    def historical(
        self,
        groww_symbol: str,
        start_time: str,
        end_time: str,
        candle_interval: str = "1day",
        exchange: str = "NSE",
        segment: str = "CASH",
    ) -> dict[str, Any]:
        """
        Get historical candles.
        Valid intervals: 1minute, 2minute, 3minute, 5minute, 10minute, 15minute, 30minute, 1hour, 4hour, 1day, 1week, 1month.
        """
        self.ensure_authenticated()
        clean_symbol = groww_symbol.upper()
        if not clean_symbol.startswith(f"{exchange.upper()}-"):
            clean_symbol = f"{exchange.upper()}-{clean_symbol}"

        return self.groww.get_historical_candles(
            exchange=exchange.upper(),
            segment=segment.upper(),
            groww_symbol=clean_symbol,
            start_time=start_time,
            end_time=end_time,
            candle_interval=candle_interval,
        )

    async def connect(self, instruments: list[dict]):
        """
        Connect to GrowwFeed live stream for a list of instruments.

        Groww's SDK creates and runs its own event loop inside GrowwFeed/NatsClient.
        That constructor must not run on FastAPI's active event-loop thread, so the
        complete synchronous feed lifecycle is run on a worker thread.
        """
        self.ensure_authenticated()

        # Both /api/v1/market/connect and the Groww router can request a connection.
        # Do not create multiple SDK feeds for the same service instance.
        if getattr(self, "_feed_started", False):
            return
        self._feed_started = True
        loop = asyncio.get_running_loop()

        def on_data_received(meta=None):
            if not self.publisher or not meta or not self.feed:
                return
            token = meta.get(FeedConstants.EXCHANGE_TOKEN)
            segment = meta.get(FeedConstants.SEGMENT, "CASH")
            exchange = meta.get(FeedConstants.EXCHANGE, "NSE")
            if not token:
                return

            try:
                topic_obj = FeedConstants.get_live_price_topic(segment, exchange, str(token))
                topic = topic_obj.get_topic()
                feed_obj = self.feed._feed_station.get_feed(topic)
                if feed_obj and feed_obj.data is not None:
                    parsed = get_data_dict(feed_obj.data, FeedConstants.LIVE_DATA)
                    if parsed:
                        tick = {
                            "instrument_token": int(token) if str(token).isdigit() else token,
                            "last_price": parsed.get("ltp"),
                            "volume_traded": parsed.get("volume"),
                        }
                        asyncio.run_coroutine_threadsafe(self.publisher.publish_tick(tick), loop)
            except Exception:
                # A malformed individual tick should not terminate the SDK feed.
                return

        def run_feed():
            # Keep construction, subscription, and consume on the same worker thread.
            # GrowwFeed's NATS client runs a private event loop during construction.
            self.feed = GrowwFeed(self.groww)
            self.feed.subscribe_ltp(instruments, on_data_received=on_data_received)
            self.feed.consume()

        try:
            await asyncio.to_thread(run_feed)
        except Exception:
            self.feed = None
            self._feed_started = False
            import logging
            logging.getLogger(__name__).exception("Groww live feed failed to start")

    # --- Cached Async Methods (Cache-Aside Pattern) ---

    async def get_quote_cached(self, symbol: str, exchange: str = "NSE", segment: str = "CASH") -> dict[str, Any]:
        """Fetch quote using cache-aside pattern with Single-Flight concurrency coalescing."""
        return await self.cache.get_quote_cached(
            symbol=symbol,
            exchange=exchange,
            segment=segment,
            fetcher=lambda: asyncio.to_thread(self.get_quote, symbol=symbol, exchange=exchange, segment=segment),
        )

    async def get_indices_cached(self) -> dict[str, Any]:
        """Fetch market indices using cache-aside pattern."""
        return await self.cache.get_indices_cached(
            fetcher=lambda: asyncio.to_thread(self.get_indices),
        )

    async def get_batch_prices_cached(
        self, symbols: list[str], exchange: str = "NSE", segment: str = "CASH"
    ) -> dict[str, Any]:
        """Fetch batch prices using cache-aside pattern."""
        return await self.cache.get_batch_prices_cached(
            symbols=symbols,
            exchange=exchange,
            segment=segment,
            fetcher=lambda missing: asyncio.to_thread(self.get_batch_prices, missing, exchange, segment),
        )

    async def get_ohlc_cached(
        self, symbols: list[str], exchange: str = "NSE", segment: str = "CASH"
    ) -> dict[str, Any]:
        """Fetch batch OHLC using cache-aside pattern."""
        return await self.cache.get_ohlc_cached(
            symbols=symbols,
            exchange=exchange,
            segment=segment,
            fetcher=lambda missing: asyncio.to_thread(self.get_ohlc, missing, exchange, segment),
        )

    async def historical_cached(
        self,
        groww_symbol: str,
        start_time: str,
        end_time: str,
        candle_interval: str = "1day",
        exchange: str = "NSE",
        segment: str = "CASH",
    ) -> dict[str, Any]:
        """Fetch historical candles using cache-aside pattern."""
        return await self.cache.historical_cached(
            symbol=groww_symbol,
            start_time=start_time,
            end_time=end_time,
            candle_interval=candle_interval,
            exchange=exchange,
            segment=segment,
            fetcher=lambda: asyncio.to_thread(
                self.historical,
                groww_symbol=groww_symbol,
                start_time=start_time,
                end_time=end_time,
                candle_interval=candle_interval,
                exchange=exchange,
                segment=segment,
            ),
        )
