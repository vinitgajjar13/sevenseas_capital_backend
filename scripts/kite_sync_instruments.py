import asyncio, csv, io
from kiteconnect import KiteConnect
from sqlalchemy import select
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.db.models import Stock

async def main():
    s=get_settings(); kite=KiteConnect(api_key=s.kite_api_key); kite.set_access_token(s.kite_access_token)
    data=kite.instruments("NSE")
    by={x["tradingsymbol"]:x["instrument_token"] for x in data}
    async with SessionLocal() as db:
        stocks=(await db.scalars(select(Stock))).all()
        for stock in stocks:
            stock.instrument_token=by.get(stock.symbol)
        await db.commit()
    print("Instrument tokens synchronized")
asyncio.run(main())
