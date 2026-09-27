"""Contractual fixed-income lots and their monetary source ledger."""
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base


class FixedIncomeLot(Base):
    __tablename__ = 'fixed_income_lots'
    __table_args__ = (
        CheckConstraint('maturity_date IS NULL OR maturity_date >= start_date', name='valid_dates'),
        CheckConstraint("yield_structure IN ('FIXED_RATE', 'BENCHMARK_MULTIPLE', 'BENCHMARK_SPREAD')",
                        name='yield_structure'),
        CheckConstraint('benchmark_multiplier IS NULL OR benchmark_multiplier >= 0',
                        name='nonnegative_multiplier'),
        CheckConstraint('benchmark_lag_months BETWEEN 0 AND 24', name='valid_benchmark_lag'),
        CheckConstraint("yield_structure <> 'FIXED_RATE' OR "
                        '(fixed_rate IS NOT NULL AND benchmark_id IS NULL AND benchmark_multiplier IS NULL AND benchmark_spread IS NULL)',
                        name='fixed_terms'),
        CheckConstraint("yield_structure <> 'BENCHMARK_MULTIPLE' OR "
                        '(fixed_rate IS NULL AND benchmark_id IS NOT NULL AND benchmark_multiplier IS NOT NULL AND benchmark_spread IS NULL)',
                        name='multiple_terms'),
        CheckConstraint("yield_structure <> 'BENCHMARK_SPREAD' OR "
                        '(fixed_rate IS NULL AND benchmark_id IS NOT NULL AND benchmark_multiplier IS NULL AND benchmark_spread IS NOT NULL)',
                        name='spread_terms'),
        Index('ix_fixed_income_lots_asset', 'asset_id'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey('assets.id', ondelete='RESTRICT'))
    product_type: Mapped[str] = mapped_column(String(40))
    issuer: Mapped[str] = mapped_column(String(200))
    broker_id: Mapped[int] = mapped_column(ForeignKey('brokers.id', ondelete='RESTRICT'))
    currency: Mapped[str] = mapped_column(String(3))
    start_date: Mapped[date] = mapped_column(Date)
    maturity_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    yield_structure: Mapped[str] = mapped_column(String(32))
    # Fractions: 0.12 = 12% per annum; 1.10 = 110% of benchmark.
    fixed_rate: Mapped[Decimal | None] = mapped_column(Numeric(28, 12), nullable=True)
    benchmark_id: Mapped[int | None] = mapped_column(ForeignKey('benchmarks.id', ondelete='RESTRICT'), nullable=True)
    benchmark_multiplier: Mapped[Decimal | None] = mapped_column(Numeric(28, 12), nullable=True)
    benchmark_spread: Mapped[Decimal | None] = mapped_column(Numeric(28, 12), nullable=True)
    day_count_basis: Mapped[str] = mapped_column(String(20))
    compounding: Mapped[str] = mapped_column(String(20))
    business_day_calendar: Mapped[str] = mapped_column(String(40))
    benchmark_lag_months: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str] = mapped_column(String(5000), default='')
    status: Mapped[str] = mapped_column(String(20), default='RECORDED')
    asset: Mapped['Asset'] = relationship()
    broker: Mapped['Broker'] = relationship()
    benchmark: Mapped['Benchmark | None'] = relationship()
    movements: Mapped[list['FixedIncomeMovement']] = relationship(
        back_populates='lot', order_by='(FixedIncomeMovement.effective_date, FixedIncomeMovement.id)')


class FixedIncomeMovement(Base):
    __tablename__ = 'fixed_income_movements'
    __table_args__ = (
        CheckConstraint('amount > 0', name='positive_amount'),
        Index('ix_fixed_income_movements_lot_date', 'lot_id', 'effective_date'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey('fixed_income_lots.id', ondelete='RESTRICT'))
    movement_type: Mapped[str] = mapped_column(String(40))
    effective_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    currency: Mapped[str] = mapped_column(String(3))
    notes: Mapped[str] = mapped_column(String(5000), default='')
    lot: Mapped[FixedIncomeLot] = relationship(back_populates='movements')
