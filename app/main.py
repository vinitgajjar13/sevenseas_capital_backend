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
from app.db.models import Base, Stock, Sector, MarketSession
from app.schemas.api import StockOut
from app.services.live_state import LiveState
from app.market_data.groww import GrowwService
from app.routers.groww import router as groww_router, set_groww_service
from app.routers.auth import router as auth_router
from app.strategies.engine import StrategyEngine, StockContext
from app.strategies.sector import calculate_sector_snapshot, assign_sector_ranks

logger = logging.getLogger(__name__)
strategy_engine = StrategyEngine()



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
                            select(Stock).where(Stock.active == True).order_by(Stock.symbol)
                        )
                    ).all()

                if stocks:
                    symbols = [s.groww_symbol.replace("NSE-", "") if s.groww_symbol else s.symbol for s in stocks]
                    token_map = {s.symbol.upper(): (s.groww_exchange_token or s.instrument_token or s.symbol) for s in stocks}

                    try:
                        # Batch in 50-symbol chunks compliant with Groww API limits
                        for offset in range(0, len(symbols), 50):
                            batch_syms = symbols[offset : offset + 50]
                            batch_res = await groww.get_batch_prices_cached(symbols=batch_syms, exchange="NSE", segment="CASH")
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
    """Return real Groww LTP/OHLC data joined to the configured stock and sector universe,

    evaluated through the exact Excel trading strategy rules (WATCH setups, SPIKE/DUMP signals,
    and sector strength/breadth).
    """
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
            "bullish_watch_count": 0,
            "bearish_watch_count": 0,
            "spike_count": 0,
            "dump_count": 0,
            "stocks": [],
            "sectors": [],
        }

    # Query latest MarketSession reference data (PD-3:25 levels & 9:15 AM OHLC)
    stock_ids = [s.id for s in stocks]
    session_rows = (
        await db.scalars(
            select(MarketSession)
            .where(MarketSession.stock_id.in_(stock_ids))
            .order_by(MarketSession.trading_date.desc())
        )
    ).all()
    session_map = {}
    for s_row in session_rows:
        if s_row.stock_id not in session_map:
            session_map[s_row.stock_id] = s_row

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
    bullish_watch_count = bearish_watch_count = 0
    spike_count = dump_count = 0
    sector_grouped_stocks = {}

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
        ms = session_map.get(stock.id)

        # Build StockContext with verified Excel reference levels
        ctx = StockContext(
            symbol=stock.symbol,
            current=float(ltp) if ltp is not None else None,
            change_pct=change_pct,
            volume=int(bar.get("volume")) if bar.get("volume") is not None else (ms.volume if ms else 0),
            pd_high=ms.pd_325_high if ms else None,
            pd_low=ms.pd_325_low if ms else None,
            open_915=ms.open_915 if ms else None,
            high_915=ms.high_915 if ms else None,
            low_915=ms.low_915 if ms else None,
            close_915=ms.close_915 if ms else None,
            prev_close=float(close) if close is not None else None,
        )
        strat = strategy_engine.evaluate(ctx)

        if strat["bullish_watch"]:
            bullish_watch_count += 1
        if strat["bearish_watch"]:
            bearish_watch_count += 1
        if strat["signal"] == "🔥 SPIKE":
            spike_count += 1
        elif strat["signal"] == "🚨 DUMP":
            dump_count += 1

        item = {
            # Preserved backward-compatible fields
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
            "volume": bar.get("volume") if bar.get("volume") is not None else (ms.volume if ms else None),
            "data_source": "groww" if ltp is not None else "unavailable",
            # Excel Strategy Fields
            "change_percent_915": strat["change_pct_915"],
            "bullish_watch": strat["bullish_watch"],
            "bearish_watch": strat["bearish_watch"],
            "watch_status": strat["watch_status"],
            "signal": strat["signal"],
            "action": strat["action"],
            "strategy_state": strat["state"],
            "score": strat["score"],
            "special_bullish": strat["special_bullish"],
            "special_bearish": strat["special_bearish"],
            "has_reference_data": strat["has_reference_data"],
            # Reference levels for auditability
            "pd_high": ms.pd_325_high if ms else None,
            "pd_low": ms.pd_325_low if ms else None,
            "open_915": ms.open_915 if ms else None,
            "close_915": ms.close_915 if ms else None,
        }
        items.append(item)

        # Group for sector calculations (use 9:15 change_pct if available, else standard change_pct)
        sec_item = {
            "symbol": stock.symbol,
            "current_price": float(ltp) if ltp is not None else None,
            "change_pct": strat["change_pct_915"] if strat["change_pct_915"] is not None else change_pct,
            "volume": item["volume"] or 0,
        }
        sector_grouped_stocks.setdefault(sector_name, []).append(sec_item)

    # Calculate exact Excel Sector Dashboard metrics & rankings
    sector_list = []
    for s_name, sec_stocks in sector_grouped_stocks.items():
        snap = calculate_sector_snapshot(sec_stocks, sector_name=s_name)
        sector_list.append(snap)

    sector_list = assign_sector_ranks(sector_list)

    return {
        "source": "groww",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total_stocks": len(items),
        "advances": advances,
        "declines": declines,
        "unchanged": unchanged,
        "bullish_watch_count": bullish_watch_count,
        "bearish_watch_count": bearish_watch_count,
        "spike_count": spike_count,
        "dump_count": dump_count,
        "sectors": sector_list,
        "stocks": items,
    }


@app.get("/api/v1/market/radar")
async def market_radar(db: AsyncSession = Depends(get_db)):
    """Dedicated endpoint returning the complete Excel Radar, Sector Ranks, and Live Market Teacher analysis."""
    overview = await market_overview(limit=500, db=db)
    status_info = get_market_status()

    sectors = overview.get("sectors", [])
    stocks = overview.get("stocks", [])

    top_bullish_sectors = [s for s in sectors if s.get("bullish_rank") is not None]
    top_bullish_sectors.sort(key=lambda s: s["bullish_rank"])

    top_bearish_sectors = [s for s in sectors if s.get("bearish_rank") is not None]
    top_bearish_sectors.sort(key=lambda s: s["bearish_rank"])

    watch_stocks = [s for s in stocks if s.get("watch_status")]
    spike_dump_stocks = [s for s in stocks if s.get("signal") in ("🔥 SPIKE", "🚨 DUMP")]
    teacher_stocks = [s for s in stocks if s.get("action") not in (None, "⚪ WATCH / WAIT")]

    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "market_status": status_info["marketStatus"],
        "price_type": status_info["priceType"],
        "summary": {
            "total_stocks": overview.get("total_stocks", 0),
            "advances": overview.get("advances", 0),
            "declines": overview.get("declines", 0),
            "bullish_watch_count": overview.get("bullish_watch_count", 0),
            "bearish_watch_count": overview.get("bearish_watch_count", 0),
            "spike_count": overview.get("spike_count", 0),
            "dump_count": overview.get("dump_count", 0),
        },
        "top_bullish_sectors": top_bullish_sectors[:3],
        "top_bearish_sectors": top_bearish_sectors[:3],
        "sectors": sectors,
        "watch_stocks": watch_stocks,
        "spike_dump_stocks": spike_dump_stocks,
        "teacher_guidance": teacher_stocks,
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
