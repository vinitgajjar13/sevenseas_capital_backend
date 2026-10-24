import asyncio
import pyotp
from datetime import datetime, timezone
from typing import Any, Optional
from growwapi import GrowwAPI, GrowwFeed
from growwapi.groww.feed import get_data_dict
from app.core.config import get_settings

FeedConstants = GrowwFeed._get_topics.__globals__["FeedConstants"]


class GrowwService:
    def __init__(self, publisher=None):
        self.settings = get_settings()
        self.publisher = publisher
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
        """Get complete real-time market quote (LTP, OHLC, 52w high/low, depth, volume)."""
        self.ensure_authenticated()
        clean_symbol = symbol.upper()
        if clean_symbol.startswith(f"{exchange.upper()}_"):
            clean_symbol = clean_symbol.replace(f"{exchange.upper()}_", "")
        if clean_symbol.startswith(f"{exchange.upper()}-"):
            clean_symbol = clean_symbol.replace(f"{exchange.upper()}-", "")

        quote = self.groww.get_quote(trading_symbol=clean_symbol, exchange=exchange.upper(), segment=segment.upper())
        return {
            "trading_symbol": clean_symbol,
            "exchange": exchange.upper(),
            "segment": segment.upper(),
            "last_price": quote.get("last_price"),
            "day_change": quote.get("day_change"),
            "day_change_perc": quote.get("day_change_perc"),
            "ohlc": quote.get("ohlc"),
            "depth": quote.get("depth"),
            "volume": quote.get("volume"),
            "week_52_high": quote.get("week_52_high"),
            "week_52_low": quote.get("week_52_low"),
            "raw": quote,
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
