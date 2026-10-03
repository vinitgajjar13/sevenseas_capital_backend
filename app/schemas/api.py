from datetime import datetime
from pydantic import BaseModel, ConfigDict

class StockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int; symbol: str; name: str; sector_id: int; exchange: str; instrument_token: int | None

class TickOut(BaseModel):
    symbol: str; price: float; change_pct: float | None = None; volume: int | None = None; timestamp: datetime

class CandleOut(BaseModel):
    time: datetime; open: float; high: float; low: float; close: float; volume: int

class StrategyOut(BaseModel):
    state: str; special_bullish: str | None = None; special_bearish: str | None = None; score: float; rank: int | None = None; comment: str | None = None
