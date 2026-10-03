import asyncio

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.db.models import Stock
from app.market_data.groww import GrowwService


async def main():
    settings = get_settings()

    groww = GrowwService(None)
    groww.authenticate()

    print("Groww authentication successful")

    # Groww SDK instrument data
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
            groww_symbol = f"{stock.exchange}-{stock.symbol}"

            try:
                instrument = instruments(groww_symbol)

                if instrument:
                    stock.groww_exchange_token = int(
                        instrument["exchange_token"]
                    )
                    stock.groww_symbol = instrument["groww_symbol"]
                    updated += 1

                    print(
                        f"{stock.symbol} -> "
                        f"{stock.groww_exchange_token} -> "
                        f"{stock.groww_symbol}"
                    )

                else:
                    not_found += 1

            except Exception as e:
                not_found += 1
                print(f"{stock.symbol} -> NOT FOUND ({e})")

        await db.commit()

    print()
    print(f"Updated: {updated}")
    print(f"Not found: {not_found}")


if __name__ == "__main__":
    asyncio.run(main())