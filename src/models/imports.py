from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.database import Base


class LegacyImport(Base):
    __tablename__ = 'legacy_imports'
    __table_args__ = (UniqueConstraint('portfolio_id', 'digest'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey('portfolios.id', ondelete='CASCADE'))
    digest: Mapped[str] = mapped_column(String(64))
    records: Mapped[int]


class TransactionImport(Base):
    __tablename__ = 'transaction_imports'
    __table_args__ = (UniqueConstraint('portfolio_id', 'digest'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey('portfolios.id', ondelete='CASCADE'))
    digest: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(255))
    records: Mapped[int]
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
