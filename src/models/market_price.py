"""Shared provider prices and portfolio-owned manual overrides."""
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base


class Instrument(Base):
    __tablename__ = 'instruments'
    __table_args__ = (UniqueConstraint('symbol', 'currency'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(40))
    currency: Mapped[str] = mapped_column(String(3))


class MarketPrice(Base):
    """Immutable shared market observation (daily bars in the first release)."""

    __tablename__ = 'market_prices'
    __table_args__ = (
        UniqueConstraint('instrument_id', 'interval', 'reference_at', 'source'),
        CheckConstraint('price > 0', name='positive_price'),
        Index('ix_market_prices_lookup', 'instrument_id', 'interval', 'reference_at'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey('instruments.id', ondelete='CASCADE'))
    interval: Mapped[str] = mapped_column(String(12), default='1d')
    reference_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    price: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    open: Mapped[Decimal | None] = mapped_column(Numeric(28, 12), nullable=True)
    high: Mapped[Decimal | None] = mapped_column(Numeric(28, 12), nullable=True)
    low: Mapped[Decimal | None] = mapped_column(Numeric(28, 12), nullable=True)
    volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    dividends: Mapped[Decimal] = mapped_column(Numeric(28, 12), default=Decimal('0'))
    stock_splits: Mapped[Decimal] = mapped_column(Numeric(28, 12), default=Decimal('0'))
    currency: Mapped[str] = mapped_column(String(3))
    source: Mapped[str] = mapped_column(String(80))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MarketPriceCoverage(Base):
    """A successfully queried range, including dates where the market was closed."""

    __tablename__ = 'market_price_coverage'
    __table_args__ = (
        UniqueConstraint('instrument_id', 'interval', 'source', 'start_date', 'end_date'),
        CheckConstraint('end_date >= start_date', name='valid_range'),
        Index('ix_market_price_coverage_lookup', 'instrument_id', 'interval', 'source'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey('instruments.id', ondelete='CASCADE'))
    interval: Mapped[str] = mapped_column(String(12), default='1d')
    source: Mapped[str] = mapped_column(String(80))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LatestMarketQuote(Base):
    """One refreshable quote per instrument/provider instead of an intraday tick log."""

    __tablename__ = 'latest_market_quotes'
    __table_args__ = (
        UniqueConstraint('instrument_id', 'source'),
        CheckConstraint('price > 0', name='positive_price'),
        Index('ix_latest_market_quotes_lookup', 'instrument_id', 'retrieved_at'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey('instruments.id', ondelete='CASCADE'))
    price: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    currency: Mapped[str] = mapped_column(String(3))
    source: Mapped[str] = mapped_column(String(80))
    market_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reference_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UserDefinedPrice(Base):
    """Private manual or migrated observations owned through a portfolio asset."""

    __tablename__ = 'user_defined_prices'
    __table_args__ = (
        UniqueConstraint('asset_id', 'reference_date'),
        CheckConstraint('price >= 0', name='nonnegative_price'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey('assets.id', ondelete='CASCADE'))
    reference_date: Mapped[date] = mapped_column(Date)
    price: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    dividends: Mapped[Decimal] = mapped_column(Numeric(28, 12), default=Decimal('0'))
    stock_splits: Mapped[Decimal] = mapped_column(Numeric(28, 12), default=Decimal('0'))
    currency: Mapped[str] = mapped_column(String(3))
    source: Mapped[str] = mapped_column(String(80), default='manual')
    retrieved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    asset: Mapped['Asset'] = relationship(back_populates='manual_prices')
