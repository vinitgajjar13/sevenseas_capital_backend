from app.market_data.groww import GrowwService
from fastapi import FastAPI, Depends, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import get_settings
from app.db.session import engine, get_db
from app.db.models import Base, Stock, Sector
from app.schemas.api import StockOut
from app.market_data.kite import KiteService
from app.services.live_state import LiveState
from app.market_data.groww import GrowwService
import pyotp

settings=get_settings(); app=FastAPI(title=settings.app_name, version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
live=LiveState(); kite=KiteService(live)
groww=GrowwService(live)

@app.on_event("startup")
async def startup():
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)

@app.get("/health")
async def health(): return {"status":"ok","service":"sevenseas-api"}

@app.get("/api/v1/auth/kite/login")
async def kite_login():
    if not settings.kite_api_key: raise HTTPException(500,"KITE_API_KEY not configured")
    return {"login_url":kite.login_url()}

@app.get("/api/v1/auth/kite/callback")
async def kite_callback(request_token: str):
    try: return kite.exchange_request_token(request_token)
    except Exception as e: raise HTTPException(400,str(e))

@app.get("/api/v1/stocks", response_model=list[StockOut])
async def stocks(db:AsyncSession=Depends(get_db)):
    return (await db.scalars(select(Stock).where(Stock.active==True).order_by(Stock.symbol))).all()

@app.get("/api/v1/stocks/{symbol}")
async def stock(symbol:str, db:AsyncSession=Depends(get_db)):
    s=await db.scalar(select(Stock).where(Stock.symbol==symbol.upper()))
    if not s: raise HTTPException(404,"Stock not found")
    tick=await live.get_tick(s.instrument_token) if s.instrument_token else None
    return {"stock":StockOut.model_validate(s),"tick":tick}

@app.post("/api/v1/market/connect")
async def market_connect(db:AsyncSession=Depends(get_db)):
    stocks=(await db.scalars(select(Stock).where(Stock.instrument_token.is_not(None),Stock.active==True))).all()
    tokens=[s.instrument_token for s in stocks]
    if not tokens: raise HTTPException(400,"No instrument tokens. Run instrument sync first.")
    # KiteTicker owns a background websocket; connect in the current service process.
    import asyncio; asyncio.create_task(kite.connect(tokens))
    return {"status":"connecting","instrument_count":len(tokens)}

@app.websocket("/ws/market")
async def market_ws(ws:WebSocket):
    await ws.accept(); pub=live.r.pubsub(); await pub.subscribe(live.channel)
    try:
        while True:
            msg=await pub.get_message(ignore_subscribe_messages=True, timeout=30)
            if msg: await ws.send_text(msg["data"])
    finally: await pub.unsubscribe(live.channel)

@app.post("/api/v1/auth/groww/connect")
async def groww_connect():
    try:
        return groww.authenticate()
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/v1/auth/groww/profile")
async def groww_profile():
    try:
        return groww.get_profile()
    except Exception as e:
        raise HTTPException(400, str(e))