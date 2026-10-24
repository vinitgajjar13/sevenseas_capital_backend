from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import String, Integer, BigInteger, Float, Boolean, DateTime, Date, ForeignKey, UniqueConstraint, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase): pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50), default="Senior Pro Trader")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Sector(Base):
    __tablename__ = "sectors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Stock(Base):
    __tablename__ = "stocks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    sector_id: Mapped[int] = mapped_column(ForeignKey("sectors.id"), index=True)
    exchange: Mapped[str] = mapped_column(String(20), default="NSE")
    instrument_token: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    
    groww_exchange_token: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        index=True
    )
    groww_symbol: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class MarketSession(Base):
    __tablename__ = "market_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"), index=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    pd_325_high: Mapped[float | None] = mapped_column(Float)
    pd_325_low: Mapped[float | None] = mapped_column(Float)
    open_915: Mapped[float | None] = mapped_column(Float)
    high_915: Mapped[float | None] = mapped_column(Float)
    low_915: Mapped[float | None] = mapped_column(Float)
    close_915: Mapped[float | None] = mapped_column(Float)
    current_close: Mapped[float | None] = mapped_column(Float)
    change_pct: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[int | None] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("stock_id", "trading_date"),)

class Candle(Base):
    __tablename__ = "candles"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"), index=True)
    interval: Mapped[str] = mapped_column(String(10), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(BigInteger, default=0)

class SignalEvent(Base):
    __tablename__ = "signal_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"), index=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    previous_state: Mapped[str | None] = mapped_column(String(30))
    new_state: Mapped[str] = mapped_column(String(30))
    event_type: Mapped[str] = mapped_column(String(30))
    score: Mapped[float | None] = mapped_column(Float)
    rank: Mapped[int | None] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text)

class SectorSnapshot(Base):
    __tablename__ = "sector_snapshots"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    sector_id: Mapped[int] = mapped_column(ForeignKey("sectors.id"), index=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    total_stocks: Mapped[int] = mapped_column(Integer, default=0)
    avg_change: Mapped[float] = mapped_column(Float, default=0)
    positive_stocks: Mapped[int] = mapped_column(Integer, default=0)
    negative_stocks: Mapped[int] = mapped_column(Integer, default=0)
    bullish_pct: Mapped[float] = mapped_column(Float, default=0)
    bearish_pct: Mapped[float] = mapped_column(Float, default=0)
    live_volume: Mapped[int] = mapped_column(BigInteger, default=0)
    volume_per_stock: Mapped[float] = mapped_column(Float, default=0)
    bullish_volume: Mapped[int] = mapped_column(BigInteger, default=0)
    bearish_volume: Mapped[int] = mapped_column(BigInteger, default=0)
    bullish_volume_pct: Mapped[float] = mapped_column(Float, default=0)
    bearish_volume_pct: Mapped[float] = mapped_column(Float, default=0)
    direction: Mapped[str] = mapped_column(String(20), default="NEUTRAL")
    score: Mapped[float] = mapped_column(Float, default=0)
    bullish_rank: Mapped[int | None] = mapped_column(Integer)
    bearish_rank: Mapped[int | None] = mapped_column(Integer)
