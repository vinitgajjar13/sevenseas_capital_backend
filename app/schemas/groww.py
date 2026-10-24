from datetime import datetime
from typing import Any, Optional, Dict
from pydantic import BaseModel, Field


class GrowwAuthResponse(BaseModel):
    status: str
    message: str
    ucc: Optional[str] = None
    vendor_user_id: Optional[str] = None
    authenticated_at: datetime
    active_segments: Optional[list[str]] = None


class GrowwAuthStatusResponse(BaseModel):
    authenticated: bool
    authenticated_at: Optional[datetime] = None
    ucc: Optional[str] = None
    vendor_user_id: Optional[str] = None


class GrowwProfileResponse(BaseModel):
    vendor_user_id: Optional[str] = None
    ucc: Optional[str] = None
    nse_enabled: Optional[bool] = None
    bse_enabled: Optional[bool] = None
    ddpi_enabled: Optional[bool] = None
    active_segments: Optional[list[str]] = None


class GrowwMarginResponse(BaseModel):
    clear_cash: Optional[float] = 0.0
    net_margin_used: Optional[float] = 0.0
    brokerage_and_charges: Optional[float] = 0.0
    collateral_used: Optional[float] = 0.0
    collateral_available: Optional[float] = 0.0
    equity_margin_details: Optional[dict[str, Any]] = None
    fno_margin_details: Optional[dict[str, Any]] = None
    commodity_margin_details: Optional[dict[str, Any]] = None


class GrowwHoldingItem(BaseModel):
    isin: Optional[str] = None
    trading_symbol: str
    quantity: float
    average_price: float
    pledge_quantity: Optional[float] = 0.0
    demat_free_quantity: Optional[float] = 0.0
    tradable_exchanges: Optional[list[str]] = None


class GrowwHoldingsResponse(BaseModel):
    holdings: list[GrowwHoldingItem] = []


class GrowwPositionsResponse(BaseModel):
    positions: list[dict[str, Any]] = []


class GrowwOrdersResponse(BaseModel):
    order_list: list[dict[str, Any]] = []


class GrowwQuoteResponse(BaseModel):
    trading_symbol: str
    exchange: str
    segment: str
    last_price: Optional[float] = None
    price: Optional[float] = None
    previousClose: Optional[float] = None
    day_change: Optional[float] = None
    day_change_perc: Optional[float] = None
    marketStatus: Optional[str] = "CLOSED"
    priceType: Optional[str] = "LAST_CLOSE"
    lastUpdated: Optional[str] = None
    ohlc: Optional[dict[str, Any]] = None
    depth: Optional[dict[str, Any]] = None
    volume: Optional[int] = None
    week_52_high: Optional[float] = None
    week_52_low: Optional[float] = None
    isStale: Optional[bool] = False
    staleReason: Optional[str] = None
    raw: Optional[dict[str, Any]] = None


class StockPriceItem(BaseModel):
    symbol: str
    price: Optional[float] = None
    previousClose: Optional[float] = None
    change: Optional[float] = None
    changePercent: Optional[float] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    volume: Optional[int] = None
    lastUpdated: Optional[str] = None
    marketStatus: str = "CLOSED"
    priceType: str = "LAST_CLOSE"
    isStale: Optional[bool] = False
    staleReason: Optional[str] = None


class GrowwLtpResponse(BaseModel):
    ltp: dict[str, float]
    marketStatus: Optional[str] = "CLOSED"
    priceType: Optional[str] = "LAST_CLOSE"
    lastUpdated: Optional[str] = None
    isStale: Optional[bool] = False
    staleReason: Optional[str] = None
    quotes: Optional[Dict[str, StockPriceItem]] = None


class MarketPricesResponse(BaseModel):
    marketStatus: str
    priceType: str
    lastUpdated: str
    isStale: Optional[bool] = False
    staleReason: Optional[str] = None
    prices: Dict[str, StockPriceItem]
    quotes: Optional[Dict[str, StockPriceItem]] = None
    ltp: Optional[Dict[str, float]] = None


class GrowwOhlcResponse(BaseModel):
    ohlc: dict[str, dict[str, Any]]
    isStale: Optional[bool] = False
    staleReason: Optional[str] = None


class GrowwHistoricalResponse(BaseModel):
    symbol: str
    candle_interval: str
    isStale: Optional[bool] = False
    staleReason: Optional[str] = None
    candles: list[Any] = []


class GrowwPlaceOrderRequest(BaseModel):
    trading_symbol: str
    quantity: int = Field(gt=0)
    transaction_type: str = Field(description="BUY or SELL")
    order_type: str = Field(default="MARKET", description="MARKET or LIMIT")
    product: str = Field(default="CNC", description="CNC, MIS, or NRML")
    price: Optional[float] = 0.0
    trigger_price: Optional[float] = None
    validity: str = Field(default="DAY", description="DAY, IOC, etc.")
    exchange: str = Field(default="NSE", description="NSE or BSE")
    segment: str = Field(default="CASH", description="CASH or FNO")


class GrowwPlaceOrderResponse(BaseModel):
    status: str
    data: dict[str, Any]


class MarketTradingHours(BaseModel):
    open: str = "09:15:00"
    close: str = "15:30:00"
    timezone: str = "Asia/Kolkata"
    exchange: str = "NSE/BSE"


class MarketStatusResponse(BaseModel):
    marketStatus: str
    priceType: str
    reason: str
    currentTime: str
    isTradingDay: bool
    holidayName: Optional[str] = None
    lastTradingSessionDate: str
    previousTradingSessionDate: str
    nextTradingSessionTime: Optional[str] = None
    tradingHours: MarketTradingHours = MarketTradingHours()


class MarketIndexQuote(BaseModel):
    name: str
    symbol: str
    price: Optional[float] = None
    previousClose: Optional[float] = None
    change: Optional[float] = None
    changePercent: Optional[float] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    week52High: Optional[float] = None
    week52Low: Optional[float] = None
    marketStatus: str = "CLOSED"
    priceType: str = "LAST_CLOSE"
    lastUpdated: Optional[str] = None
    isStale: Optional[bool] = False
    staleReason: Optional[str] = None
    constituents: Optional[list[dict[str, Any]]] = None


class MarketIndicesResponse(BaseModel):
    marketStatus: str
    priceType: str
    lastUpdated: str
    isStale: Optional[bool] = False
    staleReason: Optional[str] = None
    indices: Dict[str, MarketIndexQuote]


class CacheMetricsResponse(BaseModel):
    hits: int
    misses: int
    stale_hits: int
    redis_errors: int
    api_calls_saved: int
    hit_ratio: float
    redis_available: bool
    redis_memory_used: Optional[str] = None
    uptime_seconds: float
    keys_count: Optional[int] = None
