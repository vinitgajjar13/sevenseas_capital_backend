# Sevenseas Capital — FastAPI Backend

Backend foundation for the Sevenseas Capital React frontend.

## Stack
- Python 3.12
- FastAPI
- SQLAlchemy async + PostgreSQL
- Redis
- Groww API & Feed (NATS WebSocket)
- Pydantic Settings
- JWT auth

## Quick start
```bash
cp .env.example .env
# fill GROWW_TOTP_TOKEN, GROWW_TOTP_SECRET in .env
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Interactive Swagger Docs: **http://localhost:8000/docs**

---

## Groww API Endpoints (`/api/v1/groww`)

All endpoints leverage the Groww API credentials and automatic TOTP generator configured in `.env`:

### 1. Authentication & Account
- `POST /api/v1/groww/auth/connect` — Authenticates session with Groww using TOTP token & secret from `.env`.
- `GET /api/v1/groww/auth/status` — Returns current authentication state, UCC, and user ID.
- `GET /api/v1/groww/user/profile` — User profile (UCC, enabled exchanges, active segments).
- `GET /api/v1/groww/user/margins` — Real-time margin balances (clear cash, CNC/MIS available, FnO margins).

### 2. Portfolio & Orders
- `GET /api/v1/groww/portfolio/holdings` — User stock holdings with quantity, average price, etc.
- `GET /api/v1/groww/portfolio/positions` — Day's open/closed positions.
- `GET /api/v1/groww/orders` — Order book list (`?segment=CASH|FNO`).
- `GET /api/v1/groww/orders/{order_id}` — Specific order status and details.
- `POST /api/v1/groww/orders` — Place order (MARKET / LIMIT, CNC / MIS / NRML).
- `DELETE /api/v1/groww/orders/{order_id}` — Cancel a pending order.

### 3. Market Data (Real-time & Historical)
- `GET /api/v1/groww/market/quote/{symbol}` — Full quote with LTP, OHLC, 52-week high/low, volume, and bid/ask depth.
- `GET /api/v1/groww/market/ltp?symbols=WIPRO,INFY,TCS` — Real-time LTP for comma-separated symbols.
- `GET /api/v1/groww/market/ohlc?symbols=WIPRO,INFY` — Day's OHLC for symbols.
- `GET /api/v1/groww/market/historical/{symbol}?start_time=...&end_time=...&candle_interval=1day` — Historical candle data.

### 4. Real-time Streaming
- `POST /api/v1/groww/market/stream/connect` — Connects live WebSocket feed for universe tokens.
- `WebSocket /ws/market` — Redis pub/sub real-time tick streaming to frontend.

---

## Important
The uploaded workbook is the source of truth for the stock/sector universe and strategy vocabulary. The backend intentionally isolates strategy rules in `app/strategies/` so each workbook formula can be translated and regression-tested without changing the API contract.
