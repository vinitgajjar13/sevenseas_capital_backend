import asyncio
import json
import logging
from datetime import datetime, timezone
from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
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

logger = logging.getLogger(__name__)

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


async def background_market_poller():
    """
    Background worker that continuously pulls real-time LTP quotes from Groww API
    and broadcasts them into LiveState so all connected WebSocket clients receive
    live market prices.
    """
    await asyncio.sleep(2)
    logger.info("Starting background Groww market poller...")
    
    while True:
        try:
            # Only poll if there are connected WebSocket clients
            if live.subscriber_count > 0:
                async with SessionLocal() as db:
                    stocks = (
                        await db.scalars(
                            select(Stock).where(Stock.active == True).limit(40)
                        )
                    ).all()

                if stocks:
                    symbols = [s.groww_symbol.replace("NSE-", "") if s.groww_symbol else s.symbol for s in stocks]
                    token_map = {s.symbol.upper(): (s.groww_exchange_token or s.instrument_token or s.symbol) for s in stocks}

                    try:
                        ltp_map = await asyncio.to_thread(groww.get_ltp, symbols=symbols, exchange="NSE", segment="CASH")
                        for raw_key, price in ltp_map.items():
                            sym = raw_key.replace("NSE_", "").upper()
                            token = token_map.get(sym, sym)
                            await live.publish_tick({
                                "instrument_token": token,
                                "exchange_token": token,
                                "symbol": sym,
                                "last_price": price,
                                "ltp": price,
                            })
                    except Exception as e:
                        logger.debug(f"Background LTP poll error: {e}")

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
        # Send initial connection handshake
        await ws.send_text(json.dumps({"type": "connected", "service": "sevenseas-market-feed"}))
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
