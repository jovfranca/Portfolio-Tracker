"""Per-position accounting checkpoints; source activity, quotes and FX remain authoritative."""
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, JSON, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base


class PositionSnapshot(Base):
    __tablename__ = 'position_snapshots'
    __table_args__ = (UniqueConstraint('portfolio_id', 'instrument_id', 'date'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey('portfolios.id', ondelete='CASCADE'))
    instrument_id: Mapped[int] = mapped_column(ForeignKey('instruments.id', ondelete='RESTRICT'))
    date: Mapped[date] = mapped_column(Date)
    quote_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # For this canonical series, reporting_currency is the position's accounting currency.
    reporting_currency: Mapped[str] = mapped_column(String(3))
    quantity: Mapped[Decimal] = mapped_column(Numeric(38, 12))
    remaining_acquisition_cost: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    average_cost: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    market_value: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    realized_gain: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    unrealized_gain: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    gross_income: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    total_gain: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    net_flow: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    purchases: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    daily_income: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    daily_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    cumulative_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    status: Mapped[str] = mapped_column(String(32))
    ledger_state: Mapped[dict] = mapped_column(JSON)


class PortfolioSnapshot(Base):
    """Legacy derived reporting cache, no longer written by consolidation."""
    __tablename__ = 'portfolio_snapshots'
    __table_args__ = (UniqueConstraint('portfolio_id', 'date'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey('portfolios.id', ondelete='CASCADE'))
    date: Mapped[date] = mapped_column(Date)
    reporting_currency: Mapped[str] = mapped_column(String(3))
    remaining_acquisition_cost: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    market_value: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    realized_gain: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    unrealized_gain: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    gross_income: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    total_gain: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    daily_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    cumulative_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    status: Mapped[str] = mapped_column(String(32))
    return_factor: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))


class PositionInvalidation(Base):
    """Earliest unprocessed source change for one position."""
    __tablename__ = 'position_invalidations'
    __table_args__ = (UniqueConstraint('portfolio_id', 'instrument_id'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey('portfolios.id', ondelete='CASCADE'))
    instrument_id: Mapped[int] = mapped_column(ForeignKey('instruments.id', ondelete='RESTRICT'))
    dirty_from: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(32))


class FixedIncomeSnapshot(Base):
    """Canonical contractual lot state, retained through pending source deletion."""
    __tablename__ = 'fixed_income_snapshots'
    __table_args__ = (UniqueConstraint('portfolio_id', 'lot_id', 'date'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey('portfolios.id', ondelete='CASCADE'))
    instrument_id: Mapped[int] = mapped_column(ForeignKey('instruments.id', ondelete='RESTRICT'))
    # No source-lot FK: deleting a lot must preserve its last consolidated values.
    lot_id: Mapped[int] = mapped_column(index=True)
    date: Mapped[date] = mapped_column(Date)
    accounting_currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(32))
    valuation: Mapped[dict] = mapped_column(JSON)
    ledger_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    lot_metadata: Mapped[dict] = mapped_column(JSON)
    net_flow: Mapped[Decimal] = mapped_column(Numeric(38, 12))
    purchases: Mapped[Decimal] = mapped_column(Numeric(38, 12))


class FixedIncomeInvalidation(Base):
    """Lot-specific dirty boundary, including a deleted lot's tombstone."""
    __tablename__ = 'fixed_income_invalidations'
    __table_args__ = (UniqueConstraint('portfolio_id', 'lot_id'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey('portfolios.id', ondelete='CASCADE'))
    instrument_id: Mapped[int] = mapped_column(ForeignKey('instruments.id', ondelete='RESTRICT'))
    lot_id: Mapped[int] = mapped_column(index=True)
    dirty_from: Mapped[date] = mapped_column(Date)
