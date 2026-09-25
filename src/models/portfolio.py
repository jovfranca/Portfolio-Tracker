from datetime import date
from sqlalchemy import Date, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.database import Base


class Portfolio(Base):
    __tablename__ = 'portfolios'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    display_currency: Mapped[str] = mapped_column(String(3), default='BRL', server_default='BRL')
    dirty_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    history_built_through: Mapped[date | None] = mapped_column(Date, nullable=True)
    transactions: Mapped[list['Transaction']] = relationship(
        back_populates='portfolio', cascade='all, delete-orphan',
        order_by='(Transaction.trade_date, Transaction.id)')
    assets: Mapped[list['Asset']] = relationship(back_populates='portfolio', cascade='all, delete-orphan')
