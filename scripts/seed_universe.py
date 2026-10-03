import asyncio, os, openpyxl
from sqlalchemy import select
from app.db.session import engine, SessionLocal
from app.db.models import Base, Sector, Stock

XLSX=os.getenv("WORKBOOK_PATH","/app/F&O LIVE STOCK SHEET.xlsx")
async def main():
    wb=openpyxl.load_workbook(XLSX, data_only=True, read_only=True)
    ws=wb[wb.sheetnames[0]]
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as db:
        sectors={s.name:s for s in (await db.scalars(select(Sector))).all()}
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or not row[2] or not row[3]: continue
            symbol=str(row[2]).strip().upper(); name=str(row[1]).strip(); sector_name=str(row[3]).strip()
            sector=sectors.get(sector_name)
            if not sector:
                sector=Sector(name=sector_name); db.add(sector); await db.flush(); sectors[sector_name]=sector
            stock=await db.scalar(select(Stock).where(Stock.symbol==symbol))
            if not stock: db.add(Stock(symbol=symbol,name=name,sector_id=sector.id,exchange="NSE"))
            else: stock.name=name; stock.sector_id=sector.id
        await db.commit()
    print("Universe seeded")
asyncio.run(main())
