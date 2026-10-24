import asyncio
import os
import sys

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.db.models import Stock
from app.market_data.groww import GrowwService

# Known symbol variations between NSE and Groww
SYMBOL_ALIASES = {
    "ICICIPRULI": "ICICILIFE",
}


async def main():
    settings = get_settings()

    groww = GrowwService(None)
    groww.authenticate()

    print("Groww authentication successful")

    # Groww SDK instrument lookup
    instruments = groww.groww.get_instrument_by_groww_symbol

    async with SessionLocal() as db:
        stocks = (
            await db.scalars(
                select(Stock).where(Stock.active == True)
            )
        ).all()

        updated = 0
        not_found = 0

        for stock in stocks:
            lookup_symbol = SYMBOL_ALIASES.get(stock.symbol, stock.symbol)
            groww_symbol = f"{stock.exchange}-{lookup_symbol}"

            try:
                instrument = instruments(groww_symbol)

                if instrument:
                    stock.groww_exchange_token = int(instrument["exchange_token"])
                    stock.groww_symbol = instrument["groww_symbol"]
                    stock.instrument_token = stock.groww_exchange_token
                    updated += 1
                else:
                    not_found += 1
                    print(f"{stock.symbol} -> NOT FOUND")

            except Exception as e:
                not_found += 1
                print(f"{stock.symbol} -> NOT FOUND ({e})")

        await db.commit()

    print()
    print(f"Total Stocks: {len(stocks)}")
    print(f"Updated: {updated}")
    print(f"Not found: {not_found}")


if __name__ == "__main__":
    asyncio.run(main())