import asyncio
from datetime import datetime, timezone
from kiteconnect import KiteConnect, KiteTicker
from app.core.config import get_settings

class KiteService:
    def __init__(self, publisher):
        self.settings = get_settings(); self.publisher = publisher; self.kite=None; self.ticker=None

    def login_url(self):
        self.kite = KiteConnect(api_key=self.settings.kite_api_key)
        return self.kite.login_url()

    def exchange_request_token(self, request_token: str):
        self.kite = KiteConnect(api_key=self.settings.kite_api_key)
        data = self.kite.generate_session(request_token, api_secret=self.settings.kite_api_secret)
        self.settings.kite_access_token = data["access_token"]
        return data

    async def connect(self, tokens: list[int]):
        if not self.settings.kite_api_key or not self.settings.kite_access_token:
            raise RuntimeError("Kite API key/access token is not configured")
        loop = asyncio.get_running_loop()
        self.ticker = KiteTicker(self.settings.kite_api_key, self.settings.kite_access_token)
        def on_ticks(ws, ticks):
            for tick in ticks:
                asyncio.run_coroutine_threadsafe(self.publisher.publish_tick(tick), loop)
        def on_connect(ws, response):
            ws.subscribe(tokens)
            ws.set_mode(ws.MODE_FULL, tokens)
        def on_close(ws, code, reason): pass
        self.ticker.on_ticks = on_ticks
        self.ticker.on_connect = on_connect
        self.ticker.on_close = on_close
        await asyncio.to_thread(self.ticker.connect, True)

    def historical(self, token: int, from_dt, to_dt, interval="5minute"):
        if not self.kite:
            self.kite = KiteConnect(api_key=self.settings.kite_api_key)
            self.kite.set_access_token(self.settings.kite_access_token)
        return self.kite.historical_data(token, from_dt, to_dt, interval)
