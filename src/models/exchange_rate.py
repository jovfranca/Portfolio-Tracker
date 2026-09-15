"""Auditable historical exchange-rate persistence."""
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base


class ExchangeRate(Base):
    """BRL value of one unit of ``currency`` on a reference date."""

    __tablename__ = 'exchange_rates'
    __table_args__ = (
        UniqueConstraint('currency', 'rate_type', 'reference_date', 'rate_side'),
        CheckConstraint("rate_type IN ('FX', 'PTAX')", name='rate_type'),
        CheckConstraint("rate_side IN ('MARKET', 'BUY', 'SELL')", name='rate_side'),
        CheckConstraint('rate > 0', name='positive_rate'),
        Index('ix_exchange_rates_lookup', 'currency', 'rate_type', 'reference_date'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    currency: Mapped[str] = mapped_column(String(3))
    rate_type: Mapped[str] = mapped_column(String(4))
    rate_side: Mapped[str] = mapped_column(String(6))
    reference_date: Mapped[date] = mapped_column(Date)
    rate: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    source: Mapped[str] = mapped_column(String(80))
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
