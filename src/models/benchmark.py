"""Shared canonical benchmark identities and auditable provider observations."""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, Index, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base


class Benchmark(Base):
    __tablename__ = 'benchmarks'

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(40))
    frequency: Mapped[str] = mapped_column(String(20))
    value_type: Mapped[str] = mapped_column(String(40))
    unit: Mapped[str] = mapped_column(String(80))
    reference_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    jurisdiction: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(16))
    provider_mappings: Mapped[list['BenchmarkProviderMapping']] = relationship(back_populates='benchmark')


class BenchmarkProviderMapping(Base):
    __tablename__ = 'benchmark_provider_mappings'
    __table_args__ = (
        UniqueConstraint('provider', 'series_id'),
        UniqueConstraint('id', 'benchmark_id', name='uq_benchmark_provider_mappings_id'),
        Index('uq_benchmark_primary_mapping', 'benchmark_id', unique=True,
              postgresql_where=text('is_primary'), sqlite_where=text('is_primary')),
        CheckConstraint('NOT is_primary OR active', name='primary_mapping_active'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    benchmark_id: Mapped[int] = mapped_column(ForeignKey('benchmarks.id', ondelete='RESTRICT'))
    provider: Mapped[str] = mapped_column(String(80))
    series_id: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    benchmark: Mapped[Benchmark] = relationship(back_populates='provider_mappings')


class BenchmarkObservation(Base):
    __tablename__ = 'benchmark_observations'
    __table_args__ = (
        UniqueConstraint('provider_mapping_id', 'reference_date', 'retrieved_at'),
        ForeignKeyConstraint(
            ['provider_mapping_id', 'benchmark_id'],
            ['benchmark_provider_mappings.id', 'benchmark_provider_mappings.benchmark_id'],
            name='fk_benchmark_observations_mapping_benchmark', ondelete='RESTRICT'),
        Index('ix_benchmark_observations_lookup', 'benchmark_id', 'reference_date'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    benchmark_id: Mapped[int] = mapped_column(ForeignKey('benchmarks.id', ondelete='RESTRICT'))
    provider_mapping_id: Mapped[int] = mapped_column(ForeignKey('benchmark_provider_mappings.id', ondelete='RESTRICT'))
    reference_date: Mapped[date] = mapped_column(Date)
    value: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    source: Mapped[str] = mapped_column(String(80))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BenchmarkCoverage(Base):
    """Successfully queried provider ranges, including unpublished dates."""
    __tablename__ = 'benchmark_coverage'
    __table_args__ = (
        UniqueConstraint('provider_mapping_id', 'start_date', 'end_date'),
        CheckConstraint('end_date >= start_date', name='valid_range'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_mapping_id: Mapped[int] = mapped_column(ForeignKey('benchmark_provider_mappings.id', ondelete='RESTRICT'))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
