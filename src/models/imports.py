from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.database import Base


class LegacyImport(Base):
    __tablename__ = 'legacy_imports'
    __table_args__ = (UniqueConstraint('portfolio_id', 'digest'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey('portfolios.id', ondelete='CASCADE'))
    digest: Mapped[str] = mapped_column(String(64))
    records: Mapped[int]
