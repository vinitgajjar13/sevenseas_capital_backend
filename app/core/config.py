from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings are loaded from environment variables or the local .env file.

    Never place broker credentials in source code. Keep .env out of version control.
    """

    app_name: str = "Sevenseas Capital API"
    environment: str = "development"
    secret_key: str = "change-me"
    database_url: str = "postgresql+asyncpg://sevenseas:sevenseas@localhost:5432/sevenseas"
    redis_url: str = "redis://localhost:6379/0"

    # Broker credentials must be supplied via environment/.env.
    groww_api_key: str = ""
    groww_totp_token: str = ""
    groww_totp_secret: str = ""
    groww_api_secret: str = ""
    groww_redirect_url: str = "http://localhost:8000/api/v1/auth/groww/callback"
    groww_access_token: str = ""

    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    # Cache Configuration & TTLs (in seconds)
    cache_enabled: bool = True
    cache_ttl_live_price: int = 2          # 1-3 seconds for live stock prices and LTP
    cache_ttl_indices: int = 5             # 5-10 seconds for market indices
    cache_ttl_ohlc: int = 60               # 1 minute for intraday OHLC
    cache_ttl_historical: int = 600        # 10 minutes (5-15 min) for historical candles
    cache_ttl_market_closed: int = 300     # 5 minutes when market is closed
    cache_ttl_last_close: int = 86400      # 24 hours for verified session closes
    cache_stale_retention: int = 604800    # 7 days for last-known fallback data

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
