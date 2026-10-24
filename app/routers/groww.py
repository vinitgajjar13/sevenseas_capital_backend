from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Stock
from app.db.session import get_db
from app.market_data.groww import GrowwService
from app.services.market_calendar import get_market_status, now_ist
from app.services.market_cache import get_market_cache
from app.schemas.groww import (
    GrowwAuthResponse,
    GrowwAuthStatusResponse,
    GrowwProfileResponse,
    GrowwMarginResponse,
    GrowwHoldingsResponse,
    GrowwPositionsResponse,
    GrowwOrdersResponse,
    GrowwQuoteResponse,
    GrowwLtpResponse,
    GrowwOhlcResponse,
    GrowwHistoricalResponse,
    GrowwPlaceOrderRequest,
    GrowwPlaceOrderResponse,
    MarketStatusResponse,
    MarketIndicesResponse,
    MarketPricesResponse,
    CacheMetricsResponse,
)

router = APIRouter()

# Dependency to provide shared groww service instance
_groww_instance: Optional[GrowwService] = None


def get_groww_service() -> GrowwService:
    global _groww_instance
    if _groww_instance is None:
        raise HTTPException(status_code=500, detail="GrowwService has not been initialized")
    return _groww_instance


def set_groww_service(instance: GrowwService):
    global _groww_instance
    _groww_instance = instance


# --- 1. Authentication Endpoints ---

@router.post("/auth/connect", response_model=GrowwAuthResponse, summary="Authenticate Groww session using TOTP")
async def groww_connect(
    force: bool = Query(False, description="Force re-authentication even if already connected"),
    groww: GrowwService = Depends(get_groww_service),
):
    try:
        res = groww.authenticate(force=force)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/auth/status", response_model=GrowwAuthStatusResponse, summary="Check Groww authentication status")
async def groww_status(groww: GrowwService = Depends(get_groww_service)):
    is_auth = groww.groww is not None and groww.authenticated_at is not None
    return {
        "authenticated": is_auth,
        "authenticated_at": groww.authenticated_at,
        "ucc": groww.user_profile.get("ucc") if groww.user_profile else None,
        "vendor_user_id": groww.user_profile.get("vendor_user_id") if groww.user_profile else None,
    }


# --- 2. User & Margins Endpoints ---

@router.get("/user/profile", response_model=GrowwProfileResponse, summary="Get Groww user account profile")
async def groww_profile(groww: GrowwService = Depends(get_groww_service)):
    try:
        return groww.get_profile()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/user/margins", response_model=GrowwMarginResponse, summary="Get available trading margins")
async def groww_margins(groww: GrowwService = Depends(get_groww_service)):
    try:
        return groww.get_margins()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- 3. Portfolio & Orders Endpoints ---

@router.get("/portfolio/holdings", response_model=GrowwHoldingsResponse, summary="Get user stock holdings")
async def groww_holdings(groww: GrowwService = Depends(get_groww_service)):
    try:
        return groww.get_holdings()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/portfolio/positions", response_model=GrowwPositionsResponse, summary="Get user positions")
async def groww_positions(groww: GrowwService = Depends(get_groww_service)):
    try:
        return groww.get_positions()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/orders", response_model=GrowwOrdersResponse, summary="Get order list")
async def groww_orders(
    segment: str = Query("CASH", description="Segment: CASH or FNO"),
    groww: GrowwService = Depends(get_groww_service),
):
    try:
        return groww.get_orders(segment=segment)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/orders/{order_id}", summary="Get order details by order ID")
async def groww_order_detail(
    order_id: str,
    segment: str = Query("CASH", description="Segment: CASH or FNO"),
    groww: GrowwService = Depends(get_groww_service),
):
    try:
        return groww.get_order_detail(groww_order_id=order_id, segment=segment)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/orders", response_model=GrowwPlaceOrderResponse, summary="Place order")
async def groww_place_order(
    req: GrowwPlaceOrderRequest,
    groww: GrowwService = Depends(get_groww_service),
):
    try:
        res = groww.place_order(
            trading_symbol=req.trading_symbol,
            quantity=req.quantity,
            transaction_type=req.transaction_type,
            order_type=req.order_type,
            product=req.product,
            price=req.price or 0.0,
            trigger_price=req.trigger_price,
            validity=req.validity,
            exchange=req.exchange,
            segment=req.segment,
        )
        return {"status": "success", "data": res}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/orders/{order_id}", summary="Cancel pending order")
async def groww_cancel_order(
    order_id: str,
    segment: str = Query("CASH", description="Segment: CASH or FNO"),
    groww: GrowwService = Depends(get_groww_service),
):
    try:
        res = groww.cancel_order(groww_order_id=order_id, segment=segment)
        return {"status": "success", "data": res}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- 4. Market Data Endpoints ---

@router.get("/market/status", response_model=MarketStatusResponse, summary="Get Indian exchange trading hours and calendar status")
async def groww_market_status():
    """
    Determine whether the Indian stock market is currently OPEN (regular trading hours 09:15-15:30 IST)
    or CLOSED (weekend, trading holiday, pre-market, or after-hours), indicating whether live quotes
    or official last session closing prices apply.
    """
    return get_market_status()


@router.get("/market/indices", response_model=MarketIndicesResponse, summary="Get NIFTY 50, BANK NIFTY, SENSEX benchmarks")
async def groww_market_indices(groww: GrowwService = Depends(get_groww_service)):
    """
    Get real benchmark indices from Groww (NIFTY 50, BANK NIFTY, SENSEX) displaying official closing prices
    when market is closed or live prices during market hours.
    """
    try:
        return await groww.get_indices_cached()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch market indices: {e}")


@router.get("/market/prices", response_model=MarketPricesResponse, summary="Get structured batch quotes with live vs closing price metadata")
async def groww_market_prices(
    symbols: str = Query(..., description="Comma-separated trading symbols (e.g. WIPRO,INFY,RELIANCE)"),
    exchange: str = Query("NSE", description="Exchange: NSE or BSE"),
    segment: str = Query("CASH", description="Segment: CASH or FNO"),
    groww: GrowwService = Depends(get_groww_service),
):
    """
    Get batch stock quotes with clear price, previousClose, priceType (LIVE or LAST_CLOSE),
    marketStatus, and lastUpdated metadata.
    """
    try:
        sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
        if not sym_list:
            raise HTTPException(status_code=400, detail="No symbols provided")
        return await groww.get_batch_prices_cached(symbols=sym_list, exchange=exchange, segment=segment)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/market/quote/{symbol}", response_model=GrowwQuoteResponse, summary="Get full real-time quote for a symbol")
async def groww_market_quote(
    symbol: str,
    exchange: str = Query("NSE", description="Exchange: NSE or BSE"),
    segment: str = Query("CASH", description="Segment: CASH or FNO"),
    groww: GrowwService = Depends(get_groww_service),
):
    try:
        return await groww.get_quote_cached(symbol=symbol, exchange=exchange, segment=segment)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/market/ltp", response_model=GrowwLtpResponse, summary="Get real-time Last Traded Price (LTP) for symbols")
async def groww_market_ltp(
    symbols: str = Query(..., description="Comma-separated trading symbols (e.g. WIPRO,INFY,RELIANCE)"),
    exchange: str = Query("NSE", description="Exchange: NSE or BSE"),
    segment: str = Query("CASH", description="Segment: CASH or FNO"),
    groww: GrowwService = Depends(get_groww_service),
):
    try:
        sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
        if not sym_list:
            raise HTTPException(status_code=400, detail="No symbols provided")
        return await groww.get_batch_prices_cached(symbols=sym_list, exchange=exchange, segment=segment)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/market/ohlc", response_model=GrowwOhlcResponse, summary="Get day's OHLC for symbols")
async def groww_market_ohlc(
    symbols: str = Query(..., description="Comma-separated trading symbols (e.g. WIPRO,INFY)"),
    exchange: str = Query("NSE", description="Exchange: NSE or BSE"),
    segment: str = Query("CASH", description="Segment: CASH or FNO"),
    groww: GrowwService = Depends(get_groww_service),
):
    try:
        sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
        if not sym_list:
            raise HTTPException(status_code=400, detail="No symbols provided")
        res = await groww.get_ohlc_cached(symbols=sym_list, exchange=exchange, segment=segment)
        return {"ohlc": res}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/market/historical/{symbol}", response_model=GrowwHistoricalResponse, summary="Get historical candles")
async def groww_market_historical(
    symbol: str,
    start_time: str = Query(..., description="Start time (YYYY-MM-DD HH:mm:ss)"),
    end_time: str = Query(..., description="End time (YYYY-MM-DD HH:mm:ss)"),
    candle_interval: str = Query(
        "1day",
        description="Interval: 1minute, 2minute, 3minute, 5minute, 10minute, 15minute, 30minute, 1hour, 4hour, 1day, 1week, 1month",
    ),
    exchange: str = Query("NSE", description="Exchange: NSE or BSE"),
    segment: str = Query("CASH", description="Segment: CASH or FNO"),
    groww: GrowwService = Depends(get_groww_service),
):
    try:
        res = await groww.historical_cached(
            groww_symbol=symbol,
            start_time=start_time,
            end_time=end_time,
            candle_interval=candle_interval,
            exchange=exchange,
            segment=segment,
        )
        return {
            "symbol": symbol,
            "candle_interval": candle_interval,
            "candles": res.get("candles", []),
            "isStale": res.get("isStale", False),
            "staleReason": res.get("staleReason"),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- 5. Market Stream Connect ---

@router.post("/market/stream/connect", summary="Connect live market feed for universe tokens")
async def groww_stream_connect(
    db: AsyncSession = Depends(get_db),
    groww: GrowwService = Depends(get_groww_service),
):
    stocks = (
        await db.scalars(
            select(Stock).where(
                (Stock.groww_exchange_token.is_not(None))
                | (Stock.instrument_token.is_not(None)),
                Stock.active == True,
            )
        )
    ).all()
    instruments = []
    for s in stocks:
        token = s.groww_exchange_token or s.instrument_token
        if token:
            instruments.append(
                {
                    "exchange": s.exchange or "NSE",
                    "segment": "CASH",
                    "exchange_token": str(token),
                }
            )
    if not instruments:
        raise HTTPException(
            status_code=400,
            detail="No instrument tokens found. Please run scripts/groww_sync_instruments.py first.",
        )
    import asyncio
    asyncio.create_task(groww.connect(instruments))
    return {"status": "connecting", "instrument_count": len(instruments)}


# --- 6. Sectors & Stocks Overview ---

@router.get("/sectors/overview", summary="Get all sectors with their stocks and live Groww market data")
async def groww_sectors_overview(
    include_ltp: bool = Query(True, description="Fetch real-time LTP from Groww for each stock"),
    db: AsyncSession = Depends(get_db),
    groww: GrowwService = Depends(get_groww_service),
):
    from collections import defaultdict
    from app.db.models import Sector

    sectors = (await db.scalars(select(Sector).where(Sector.active == True).order_by(Sector.name))).all()
    stocks = (await db.scalars(select(Stock).where(Stock.active == True).order_by(Stock.symbol))).all()

    sector_map = {s.id: {"id": s.id, "name": s.name, "stocks": []} for s in sectors}

    for st in stocks:
        if st.sector_id in sector_map:
            sector_map[st.sector_id]["stocks"].append(st)

    result = []
    for sec_id, data in sector_map.items():
        sec_stocks = data["stocks"]
        stock_items = []
        ltp_map = {}

        if include_ltp and sec_stocks:
            try:
                symbols = [st.groww_symbol.replace("NSE-", "") if st.groww_symbol else st.symbol for st in sec_stocks]
                batch_res = await groww.get_batch_prices_cached(symbols=symbols, exchange="NSE", segment="CASH")
                ltp_map = batch_res.get("ltp", {})
            except Exception:
                ltp_map = {}

        status_info = get_market_status()
        last_updated = now_ist().isoformat() if status_info["marketStatus"] == "OPEN" else f"{status_info['lastTradingSessionDate']}T15:30:00+05:30"

        for st in sec_stocks:
            sym_key = st.groww_symbol.replace("NSE-", "") if st.groww_symbol else st.symbol
            price = ltp_map.get(f"NSE_{sym_key}") or ltp_map.get(sym_key)
            stock_items.append({
                "id": st.id,
                "symbol": st.symbol,
                "name": st.name,
                "groww_symbol": st.groww_symbol,
                "groww_exchange_token": st.groww_exchange_token,
                "exchange": st.exchange,
                "ltp": price,
                "price": price,
                "priceType": status_info["priceType"],
                "marketStatus": status_info["marketStatus"],
                "lastUpdated": last_updated,
            })

        result.append({
            "sector_id": data["id"],
            "sector_name": data["name"],
            "stock_count": len(sec_stocks),
            "stocks": stock_items,
        })

    return {
        "total_sectors": len(sectors),
        "total_stocks": len(stocks),
        "sectors": result,
    }



# --- 7. Cache Metrics & Maintenance Endpoints ---

@router.get("/cache/metrics", response_model=CacheMetricsResponse, summary="Get market cache metrics, hit ratio, and Redis telemetry")
async def groww_cache_metrics():
    """Retrieve cache performance metrics, hit ratio, saved broker API calls, and Redis health."""
    cache = get_market_cache()
    return await cache.get_metrics()


@router.post("/cache/clear", summary="Clear market cache keys by pattern")
async def groww_cache_clear(pattern: str = Query("sq:*", description="Redis key pattern to clear")):
    """Clear keys from Redis and in-memory cache."""
    cache = get_market_cache()
    deleted = await cache.clear(pattern=pattern)
    return {"status": "success", "cleared_keys": deleted, "pattern": pattern}
