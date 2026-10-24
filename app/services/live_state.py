import json
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Set
import redis.asyncio as redis
from app.core.config import get_settings

logger = logging.getLogger(__name__)

class LiveState:
    def __init__(self):
        self.settings = get_settings()
        self.channel = 'market:ticks'
        self.r = None
        self._redis_available = True
        self._subscribers: Set[asyncio.Queue] = set()
        self._latest_ticks: dict[str, dict] = {}

        try:
            self.r = redis.from_url(self.settings.redis_url, decode_responses=True)
        except Exception as e:
            logger.warning(f'Redis connection failed: {e}. Falling back to in-memory pubsub.')
            self._redis_available = False

    async def publish_tick(self, tick: dict):
        token = str(tick.get('instrument_token', ''))
        data = {
            'instrument_token': tick.get('instrument_token'),
            'exchange_token': tick.get('exchange_token') or tick.get('instrument_token'),
            'symbol': tick.get('symbol'),
            'last_price': tick.get('last_price') or tick.get('ltp'),
            'ltp': tick.get('last_price') or tick.get('ltp'),
            'volume': tick.get('volume_traded') or tick.get('volume'),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        raw = json.dumps(data)
        if token:
            self._latest_ticks[token] = data

        # 1. In-memory broadcast to all connected WebSocket subscribers
        dead_queues = []
        for q in list(self._subscribers):
            try:
                if q.full():
                    try:
                        q.get_nowait()
                    except Exception:
                        pass
                q.put_nowait(raw)
            except Exception:
                dead_queues.append(q)

        for dq in dead_queues:
            self._subscribers.discard(dq)

        # 2. Redis broadcast if available
        if self._redis_available and self.r:
            try:
                await self.r.set(f'tick:{data["instrument_token"]}', raw, ex=86400)
                await self.r.publish(self.channel, raw)
            except Exception as e:
                # Silently mark redis unavailable on error without throwing
                self._redis_available = False
                logger.debug(f'Redis publish failed, continuing in-memory: {e}')

    async def get_tick(self, token: any) -> Optional[dict]:
        token_str = str(token)
        if token_str in self._latest_ticks:
            return self._latest_ticks[token_str]

        if self._redis_available and self.r:
            try:
                raw = await self.r.get(f'tick:{token}')
                if raw:
                    parsed = json.loads(raw)
                    self._latest_ticks[token_str] = parsed
                    return parsed
            except Exception:
                self._redis_available = False

        return None

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        self._subscribers.discard(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
