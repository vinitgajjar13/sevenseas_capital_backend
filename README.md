# Sevenseas Capital — FastAPI Backend

Backend foundation for the existing Sevenseas Capital React frontend.

## Stack
- Python 3.12
- FastAPI
- SQLAlchemy async + PostgreSQL
- Redis
- Zerodha Kite Connect WebSocket
- Pydantic Settings
- JWT auth

## Quick start
```bash
cp .env.example .env
# fill KITE_API_KEY, KITE_API_SECRET
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Or:
```bash
docker compose up --build
```

Swagger: http://localhost:8000/docs

## Zerodha flow
1. Register the backend callback URL in Kite developer console.
2. `GET /api/v1/auth/kite/login` returns the Kite login URL.
3. After login Kite redirects to `/api/v1/auth/kite/callback?request_token=...`.
4. The backend exchanges the request token for an access token.
5. Start `POST /api/v1/market/connect` after authentication.

Kite credentials belong only on the backend. Never expose API secret/access token to React.

## Important
The uploaded workbook is the source of truth for the stock/sector universe and strategy vocabulary. The backend intentionally isolates strategy rules in `app/strategies/` so each workbook formula can be translated and regression-tested without changing the API contract.
