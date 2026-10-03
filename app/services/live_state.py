import json
from datetime import datetime, timezone
import redis.asyncio as redis
from app.core.config import get_settings

class LiveState:
    def __init__(self): self.r = redis.from_url(get_settings().redis_url, decode_responses=True); self.channel="market:ticks"
    async def publish_tick(self, tick):
        data={"instrument_token":tick.get("instrument_token"),"last_price":tick.get("last_price"),"volume":tick.get("volume_traded"),"timestamp":datetime.now(timezone.utc).isoformat()}
        await self.r.set(f"tick:{data['instrument_token']}", json.dumps(data), ex=86400)
        await self.r.publish(self.channel, json.dumps(data))
    async def get_tick(self, token):
        raw=await self.r.get(f"tick:{token}"); return json.loads(raw) if raw else None
