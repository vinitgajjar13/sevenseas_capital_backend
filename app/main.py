from app.services.market_calendar import get_market_status, is_market_open, now_ist
import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import get_settings
from app.db.session import engine, get_db, SessionLocal
from app.db.models import Base, Stock, Sector
from app.schemas.api import StockOut
from app.services.live_state import LiveState
from app.market_data.groww import GrowwService
from app.routers.groww import router as groww_router, set_groww_service
from app.routers.auth import router as auth_router

logger = logging.getLogger(__name__)


def _normalize_ohlc(value):
    """Normalize Groww SDK OHLC responses, which may be dicts or serialized strings."""
    parsed = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            parsed = {}
            for field in ("open", "high", "low", "close", "volume"):
                match = re.search(
                    rf"{field}\s*:\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))",
                    value,
                    re.IGNORECASE,
                )
                if match:
                    parsed[field] = match.group(1)
    if not isinstance(parsed, dict):
        return {}
    normalized = {}
    for field in ("open", "high", "low", "close", "volume"):
        raw = parsed.get(field)
        try:
            normalized[field] = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            normalized[field] = None
    return normalized


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Sevenseas Capital Backend API with full Groww API & TOTP integration",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

live = LiveState()
groww = GrowwService(live)
set_groww_service(groww)

# Register Groww Router
app.include_router(groww_router, prefix="/api/v1/groww", tags=["Groww API"])
app.include_router(auth_router, prefix="/api/v1")


async def background_market_poller():
    """
    Background worker that continuously pulls real-time quotes or official closing prices
    from Groww API and broadcasts them into LiveState so all connected WebSocket clients
    receive verified market prices with clear priceType (LIVE vs LAST_CLOSE) indicators.
    """
    await asyncio.sleep(2)
    logger.info("Starting background Groww market poller with market status awareness...")
    
    while True:
        try:
            # Only poll if there are connected WebSocket clients
            if live.subscriber_count > 0:
                status_info = get_market_status()
                is_open = status_info["marketStatus"] == "OPEN"

                async with SessionLocal() as db:
                    stocks = (
                        await db.scalars(
                            select(Stock).where(Stock.active == True).limit(50)
                        )
                    ).all()

                if stocks:
                    symbols = [s.groww_symbol.replace("NSE-", "") if s.groww_symbol else s.symbol for s in stocks]
                    token_map = {s.symbol.upper(): (s.groww_exchange_token or s.instrument_token or s.symbol) for s in stocks}

                    try:
                        batch_res = await groww.get_batch_prices_cached(symbols=symbols, exchange="NSE", segment="CASH")
                        ltp_map = batch_res.get("ltp", {})
                        for raw_key, price in ltp_map.items():
                            sym = raw_key.replace("NSE_", "").upper()
                            token = token_map.get(sym, sym)
                            await live.publish_tick({
                                "instrument_token": token,
                                "exchange_token": token,
                                "symbol": sym,
                                "last_price": price,
                                "ltp": price,
                                "marketStatus": status_info["marketStatus"],
                                "priceType": status_info["priceType"],
                            })
                    except Exception as e:
                        logger.debug(f"Background LTP poll error: {e}")

                # If market is closed, sleep longer (20s) to avoid unnecessary polling; if open, 5s
                sleep_sec = 5 if is_open else 20
                await asyncio.sleep(sleep_sec)
            else:
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug(f"Error in background poller: {e}")
            await asyncio.sleep(5)


@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Start background poller task
    asyncio.create_task(background_market_poller())


@app.get("/api/v1/market/status")
async def market_status():
    """Get market trading calendar status (live vs last close)."""
    return get_market_status()


@app.get("/api/v1/market/indices")
async def market_indices():
    """Get NIFTY 50, BANK NIFTY, SENSEX with official closing/live prices using Redis cache."""
    return await groww.get_indices_cached()


@app.get("/api/v1/market/cache/metrics")
async def market_cache_metrics():
    """Get cache performance telemetry and hit ratio."""
    return await groww.cache.get_metrics()


@app.get("/health")
async def health():
    return {"status": "ok", "service": "sevenseas-api"}


@app.get("/api/v1/stocks", response_model=list[StockOut])
async def stocks(db: AsyncSession = Depends(get_db)):
    return (
        await db.scalars(
            select(Stock).where(Stock.active == True).order_by(Stock.symbol)
        )
    ).all()


@app.get("/api/v1/market/overview")
async def market_overview(
    limit: int = Query(250, ge=1, le=500, description="Maximum active stocks to include"),
    db: AsyncSession = Depends(get_db),
):
    """Return real Groww LTP/OHLC data joined to the configured stock and sector universe.

    Strategy scores and signals are intentionally not fabricated here; this endpoint
    only returns values supplied by Groww plus simple change calculations from OHLC.
    """
    from app.db.models import Sector

    stocks = (
        await db.scalars(
            select(Stock).where(Stock.active == True).order_by(Stock.symbol).limit(limit)
        )
    ).all()
    if not stocks:
        return {
            "source": "groww",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "total_stocks": 0,
            "advances": 0,
            "declines": 0,
            "unchanged": 0,
            "stocks": [],
            "sectors": [],
        }

    symbols = [
        (s.groww_symbol or s.symbol).replace("NSE-", "").replace("BSE-", "").strip().upper()
        for s in stocks
    ]
    try:
        batch_res = await groww.get_batch_prices_cached(symbols=symbols, exchange="NSE", segment="CASH")
        ltp_map = batch_res.get("ltp", {})
        ohlc_map = await groww.get_ohlc_cached(symbols=symbols, exchange="NSE", segment="CASH")
    except Exception as exc:
        logger.warning("Groww market overview request failed: %s", exc)
        raise HTTPException(status_code=502, detail="Groww market data is unavailable; check Groww authentication and instrument symbols.")

    sectors = (await db.scalars(select(Sector).where(Sector.active == True))).all()
    sector_names = {sector.id: sector.name for sector in sectors}
    items = []
    advances = declines = unchanged = 0
    sector_stats = {}

    for stock in stocks:
        symbol = (stock.groww_symbol or stock.symbol).replace("NSE-", "").replace("BSE-", "").strip().upper()
        key = f"NSE_{symbol}"
        ltp = ltp_map.get(key, ltp_map.get(symbol))
        bar = _normalize_ohlc(ohlc_map.get(key, ohlc_map.get(symbol, {})) or {})
        close = bar.get("close")
        change = round(float(ltp) - float(close), 4) if ltp is not None and close not in (None, 0) else None
        change_pct = round(change / float(close) * 100, 4) if change is not None and close not in (None, 0) else None
        if change_pct is not None and change_pct > 0:
            advances += 1
        elif change_pct is not None and change_pct < 0:
            declines += 1
        elif change_pct == 0:
            unchanged += 1

        sector_name = sector_names.get(stock.sector_id, "Unclassified")
        item = {
            "id": stock.id,
            "symbol": stock.symbol,
            "name": stock.name,
            "sector_id": stock.sector_id,
            "sector": sector_name,
            "exchange": stock.exchange or "NSE",
            "groww_symbol": stock.groww_symbol,
            "groww_exchange_token": stock.groww_exchange_token,
            "ltp": float(ltp) if ltp is not None else None,
            "change": change,
            "change_percent": change_pct,
            "open": bar.get("open"),
            "high": bar.get("high"),
            "low": bar.get("low"),
            "previous_close": close,
            "volume": bar.get("volume"),
            "data_source": "groww" if ltp is not None else "unavailable",
        }
        items.append(item)

        stat = sector_stats.setdefault(sector_name, {"sector": sector_name, "total": 0, "advances": 0, "declines": 0, "unchanged": 0, "average_change_percent": 0.0, "_changes": []})
        stat["total"] += 1
        if change_pct is not None:
            stat["_changes"].append(change_pct)
            if change_pct > 0:
                stat["advances"] += 1
            elif change_pct < 0:
                stat["declines"] += 1
            else:
                stat["unchanged"] += 1

    sector_list = []
    for stat in sector_stats.values():
        changes = stat.pop("_changes")
        stat["average_change_percent"] = round(sum(changes) / len(changes), 4) if changes else None
        sector_list.append(stat)
    sector_list.sort(key=lambda item: (item["average_change_percent"] is not None, item["average_change_percent"] or 0), reverse=True)

    return {
        "source": "groww",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total_stocks": len(items),
        "advances": advances,
        "declines": declines,
        "unchanged": unchanged,
        "sectors": sector_list,
        "stocks": items,
    }





@app.get("/api/v1/stocks/{symbol}")
async def stock(symbol: str, db: AsyncSession = Depends(get_db)):
    s = await db.scalar(select(Stock).where(Stock.symbol == symbol.upper()))
    if not s:
        raise HTTPException(404, "Stock not found")
    token = s.groww_exchange_token or s.instrument_token
    tick = await live.get_tick(token) if token else None
    return {"stock": StockOut.model_validate(s), "tick": tick}


@app.post("/api/v1/market/connect")
async def market_connect(db: AsyncSession = Depends(get_db)):
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
            400, "No instrument tokens. Run Groww instrument sync first."
        )

    asyncio.create_task(groww.connect(instruments))
    return {"status": "connecting", "instrument_count": len(instruments)}


@app.websocket("/ws/market")
async def market_ws(ws: WebSocket):
    await ws.accept()
    q = live.subscribe()
    try:
        status_info = get_market_status()
        # Send initial connection handshake with market status & priceType metadata
        await ws.send_text(json.dumps({
            "type": "connected",
            "service": "sevenseas-market-feed",
            "marketStatus": status_info["marketStatus"],
            "priceType": status_info["priceType"],
            "reason": status_info["reason"],
            "lastTradingSessionDate": status_info["lastTradingSessionDate"],
        }))
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=20.0)
                await ws.send_text(msg)
            except asyncio.TimeoutError:
                # Heartbeat to maintain active connection
                await ws.send_text(json.dumps({"type": "heartbeat", "timestamp": datetime.now(timezone.utc).isoformat()}))
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception as e:
        logger.debug(f"WebSocket disconnected: {e}")
    finally:
        live.unsubscribe(q)


# Backward-compatible convenience endpoints
@app.post("/api/v1/auth/groww/connect")
async def legacy_groww_connect():
    try:
        return groww.authenticate()
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/v1/auth/groww/profile")
async def legacy_groww_profile():
    try:
        return groww.get_profile()
    except Exception as e:
        raise HTTPException(400, str(e))
