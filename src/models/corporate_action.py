"""Shared provider corporate actions and private portfolio events."""
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base


EVENT_TYPES = ('STOCK_SPLIT', 'REVERSE_SPLIT', 'DIVIDEND', 'JCP', 'AMORTIZATION')
EVENT_TYPE_SQL = "event_type IN ('STOCK_SPLIT', 'REVERSE_SPLIT', 'DIVIDEND', 'JCP', 'AMORTIZATION')"
EVENT_VALUES_SQL = """(
    (event_type = 'STOCK_SPLIT' AND conversion_factor > 1
        AND amount_per_unit IS NULL AND currency IS NULL)
    OR (event_type = 'REVERSE_SPLIT' AND conversion_factor > 0 AND conversion_factor < 1
        AND amount_per_unit IS NULL AND currency IS NULL)
    OR (event_type IN ('DIVIDEND', 'JCP', 'AMORTIZATION')
        AND amount_per_unit IS NOT NULL AND currency IS NOT NULL
        AND conversion_factor IS NULL)
)"""


class CorporateAction(Base):
    """Immutable provider-backed action shared by every portfolio."""

    __tablename__ = 'corporate_actions'
    __table_args__ = (
        UniqueConstraint('instrument_id', 'source', 'event_key'),
        CheckConstraint(EVENT_TYPE_SQL, name='event_type'),
        CheckConstraint(EVENT_VALUES_SQL, name='event_values'),
        CheckConstraint('amount_per_unit IS NULL OR amount_per_unit >= 0', name='nonnegative_amount'),
        CheckConstraint('conversion_factor IS NULL OR conversion_factor > 0', name='positive_factor'),
        CheckConstraint("currency IS NULL OR (length(currency) = 3 AND currency = upper(currency))", name='currency'),
        Index('ix_corporate_actions_lookup', 'instrument_id', 'effective_date', 'event_type'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey('instruments.id', ondelete='CASCADE'))
    event_type: Mapped[str] = mapped_column(String(24))
    effective_date: Mapped[date] = mapped_column(Date)
    payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(28, 12), nullable=True)
    conversion_factor: Mapped[Decimal | None] = mapped_column(Numeric(28, 12), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    source: Mapped[str] = mapped_column(String(80))
    provider_event_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    event_key: Mapped[str] = mapped_column(String(64))
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    instrument: Mapped['Instrument'] = relationship()


class CorporateActionCoverage(Base):
    """A successfully queried provider range, including ranges with no events."""

    __tablename__ = 'corporate_action_coverage'
    __table_args__ = (
        UniqueConstraint('instrument_id', 'source', 'start_date', 'end_date'),
        CheckConstraint('end_date >= start_date', name='valid_range'),
        Index('ix_corporate_action_coverage_lookup', 'instrument_id', 'source'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey('instruments.id', ondelete='CASCADE'))
    source: Mapped[str] = mapped_column(String(80))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UserCorporateEvent(Base):
    """Manual event private to the portfolio that owns the asset."""

    __tablename__ = 'user_corporate_events'
    __table_args__ = (
        UniqueConstraint('asset_id', 'event_type', 'effective_date'),
        CheckConstraint(EVENT_TYPE_SQL, name='event_type'),
        CheckConstraint(EVENT_VALUES_SQL, name='event_values'),
        CheckConstraint('amount_per_unit IS NULL OR amount_per_unit >= 0', name='nonnegative_amount'),
        CheckConstraint('conversion_factor IS NULL OR conversion_factor > 0', name='positive_factor'),
        CheckConstraint("currency IS NULL OR (length(currency) = 3 AND currency = upper(currency))", name='currency'),
        Index('ix_user_corporate_events_lookup', 'asset_id', 'effective_date', 'event_type'),
        Index(
            'uq_user_corporate_events_split_date', 'asset_id', 'effective_date',
            unique=True,
            postgresql_where=text("event_type IN ('STOCK_SPLIT', 'REVERSE_SPLIT')"),
            sqlite_where=text("event_type IN ('STOCK_SPLIT', 'REVERSE_SPLIT')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey('assets.id', ondelete='CASCADE'))
    event_type: Mapped[str] = mapped_column(String(24))
    effective_date: Mapped[date] = mapped_column(Date)
    payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(28, 12), nullable=True)
    conversion_factor: Mapped[Decimal | None] = mapped_column(Numeric(28, 12), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    source: Mapped[str] = mapped_column(String(80), default='manual')
    notes: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    asset: Mapped['Asset'] = relationship(back_populates='corporate_events')
