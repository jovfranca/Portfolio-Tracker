"""Shared provider prices and portfolio-owned manual overrides."""
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric,
    String, UniqueConstraint, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base


class Instrument(Base):
    __tablename__ = 'instruments'
    __table_args__ = (Index(
        'uq_instruments_crypto_symbol', 'symbol', unique=True,
        postgresql_where=text("asset_type = 'CRYPTO'"),
        sqlite_where=text("asset_type = 'CRYPTO'"),
    ),)

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200), default='')
    asset_type: Mapped[str] = mapped_column(String(40), default='OTHER')
    exchange: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Native/listing currency, never the transaction or provider currency.
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default='ACTIVE')
    # CATALOG is maintained from data/instruments.csv. CUSTOM is explicitly
    # user-created; MIGRATED preserves pre-catalog history without trusting it.
    origin: Mapped[str] = mapped_column(String(16), default='CUSTOM')
    isin: Mapped[str | None] = mapped_column(String(12), nullable=True)
    provider_mappings: Mapped[list['ProviderInstrument']] = relationship(
        back_populates='instrument', cascade='all, delete-orphan'
    )
    aliases: Mapped[list['InstrumentAlias']] = relationship(
        back_populates='instrument', cascade='all, delete-orphan'
    )


class ProviderInstrument(Base):
    __tablename__ = 'provider_instruments'
    __table_args__ = (
        UniqueConstraint('provider', 'provider_symbol', 'quote_currency'),
        Index('ix_provider_instruments_instrument_provider', 'instrument_id', 'provider'),
        Index(
            'uq_provider_instruments_primary', 'instrument_id', 'provider', unique=True,
            postgresql_where=text('is_primary'), sqlite_where=text('is_primary'),
        ),
        CheckConstraint('NOT is_primary OR active', name='primary_mapping_active'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey('instruments.id', ondelete='CASCADE'))
    provider: Mapped[str] = mapped_column(String(80))
    provider_symbol: Mapped[str] = mapped_column(String(80))
    quote_currency: Mapped[str] = mapped_column(String(3))
    provider_exchange: Mapped[str | None] = mapped_column(String(80), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    instrument: Mapped[Instrument] = relationship(back_populates='provider_mappings')


class InstrumentAlias(Base):
    __tablename__ = 'instrument_aliases'
    __table_args__ = (
        UniqueConstraint('instrument_id', 'normalized_alias', 'source'),
        Index('ix_instrument_aliases_normalized_alias', 'normalized_alias'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey('instruments.id', ondelete='CASCADE'))
    alias: Mapped[str] = mapped_column(String(120))
    normalized_alias: Mapped[str] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(80), default='manual')
    instrument: Mapped[Instrument] = relationship(back_populates='aliases')


class MarketPrice(Base):
    """Immutable shared market observation (daily bars in the first release)."""

    __tablename__ = 'market_prices'
    __table_args__ = (
        UniqueConstraint('provider_instrument_id', 'interval', 'reference_at'),
        CheckConstraint('price > 0', name='positive_price'),
        Index('ix_market_prices_lookup', 'provider_instrument_id', 'interval', 'reference_at'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_instrument_id: Mapped[int] = mapped_column(
        ForeignKey('provider_instruments.id', ondelete='CASCADE')
    )
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
        UniqueConstraint('provider_instrument_id', 'interval', 'start_date', 'end_date'),
        CheckConstraint('end_date >= start_date', name='valid_range'),
        Index('ix_market_price_coverage_lookup', 'provider_instrument_id', 'interval'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_instrument_id: Mapped[int] = mapped_column(
        ForeignKey('provider_instruments.id', ondelete='CASCADE')
    )
    interval: Mapped[str] = mapped_column(String(12), default='1d')
    source: Mapped[str] = mapped_column(String(80))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LatestMarketQuote(Base):
    """One refreshable quote per instrument/provider instead of an intraday tick log."""

    __tablename__ = 'latest_market_quotes'
    __table_args__ = (
        UniqueConstraint('provider_instrument_id'),
        CheckConstraint('price > 0', name='positive_price'),
        Index('ix_latest_market_quotes_lookup', 'provider_instrument_id', 'retrieved_at'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_instrument_id: Mapped[int] = mapped_column(
        ForeignKey('provider_instruments.id', ondelete='CASCADE')
    )
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
