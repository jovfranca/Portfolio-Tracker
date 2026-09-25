"""Derived daily reporting views; transactions, events, prices and FX remain authoritative."""
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
