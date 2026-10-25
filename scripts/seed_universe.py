import asyncio
import os
import sys
from datetime import date, datetime

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl
from sqlalchemy import select
from app.db.session import engine, SessionLocal
from app.db.models import Base, Sector, Stock, MarketSession

# Robust file path resolution: environment variable -> local workspace app/ -> Docker /app/
DEFAULT_LOCAL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "F&O LIVE STOCK SHEET.xlsx")
XLSX = os.getenv("WORKBOOK_PATH") or (DEFAULT_LOCAL if os.path.exists(DEFAULT_LOCAL) else "/app/F&O LIVE STOCK SHEET.xlsx")


def _safe_float(val):
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(val):
    if val is None or val == "":
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


async def main():
    print(f"Loading workbook from: {XLSX}")
    wb = openpyxl.load_workbook(XLSX, data_only=True, read_only=True)
    ws = wb[wb.sheetnames[0]]

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    today = date.today()

    async with SessionLocal() as db:
        sectors = {s.name: s for s in (await db.scalars(select(Sector))).all()}
        stock_count = 0
        session_count = 0

        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or not row[2] or not row[3]:
                continue
            symbol = str(row[2]).strip().upper()
            name = str(row[1]).strip()
            sector_name = str(row[3]).strip()

            sector = sectors.get(sector_name)
            if not sector:
                sector = Sector(name=sector_name)
                db.add(sector)
                await db.flush()
                sectors[sector_name] = sector

            stock = await db.scalar(select(Stock).where(Stock.symbol == symbol))
            if not stock:
                stock = Stock(symbol=symbol, name=name, sector_id=sector.id, exchange="NSE")
                db.add(stock)
                await db.flush()
            else:
                stock.name = name
                stock.sector_id = sector.id

            stock_count += 1

            # Seed / update MarketSession reference data from Sheet1
            # Col 4: PD-3:25-HIGH, Col 5: PD-3:25-LOW, Col 6: 9:15-OPEN, Col 7: 9:15-HIGH, Col 8: 9:15-LOW, Col 9: 9:15-CLOSE
            pd_high = _safe_float(row[4]) if len(row) > 4 else None
            pd_low = _safe_float(row[5]) if len(row) > 5 else None
            open_915 = _safe_float(row[6]) if len(row) > 6 else None
            high_915 = _safe_float(row[7]) if len(row) > 7 else None
            low_915 = _safe_float(row[8]) if len(row) > 8 else None
            close_915 = _safe_float(row[9]) if len(row) > 9 else None
            curr_close = _safe_float(row[10]) if len(row) > 10 else None
            change_pct = _safe_float(row[11]) if len(row) > 11 else None
            volume = _safe_int(row[12]) if len(row) > 12 else None

            session = await db.scalar(
                select(MarketSession).where(
                    MarketSession.stock_id == stock.id,
                    MarketSession.trading_date == today,
                )
            )

            if not session:
                session = MarketSession(
                    stock_id=stock.id,
                    trading_date=today,
                    pd_325_high=pd_high,
                    pd_325_low=pd_low,
                    open_915=open_915,
                    high_915=high_915,
                    low_915=low_915,
                    close_915=close_915,
                    current_close=curr_close,
                    change_pct=change_pct,
                    volume=volume,
                )
                db.add(session)
            else:
                session.pd_325_high = pd_high
                session.pd_325_low = pd_low
                session.open_915 = open_915
                session.high_915 = high_915
                session.low_915 = low_915
                session.close_915 = close_915
                session.current_close = curr_close
                session.change_pct = change_pct
                session.volume = volume
                session.updated_at = datetime.utcnow()

            session_count += 1

        await db.commit()

    print(f"Universe seeded: {stock_count} stocks, {session_count} market session reference rows.")


if __name__ == "__main__":
    asyncio.run(main())

