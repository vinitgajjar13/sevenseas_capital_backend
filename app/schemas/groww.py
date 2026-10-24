from datetime import datetime
from typing import Any, Optional
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
    day_change: Optional[float] = None
    day_change_perc: Optional[float] = None
    ohlc: Optional[dict[str, Any]] = None
    depth: Optional[dict[str, Any]] = None
    volume: Optional[int] = None
    week_52_high: Optional[float] = None
    week_52_low: Optional[float] = None
    raw: Optional[dict[str, Any]] = None


class GrowwLtpResponse(BaseModel):
    ltp: dict[str, float]


class GrowwOhlcResponse(BaseModel):
    ohlc: dict[str, dict[str, Any]]


class GrowwHistoricalResponse(BaseModel):
    symbol: str
    candle_interval: str
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
