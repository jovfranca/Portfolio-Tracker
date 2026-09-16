from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.database import Base


class Transaction(Base):
    __tablename__ = 'transactions'
    __table_args__ = (
        CheckConstraint("type IN ('Buy', 'Sell')", name='type'),
        CheckConstraint('quantity > 0 AND price >= 0 AND brokerage_fee >= 0 AND other_fees >= 0', name='amounts'),
        CheckConstraint("asset_currency ~ '^[A-Z]{3}$' AND fx_rate > 0", name='currency'),
        CheckConstraint('settlement_date >= trade_date', name='dates'),
        Index('ix_transactions_portfolio_date', 'portfolio_id', 'date_time', 'id'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey('portfolios.id', ondelete='CASCADE'))
    date_time: Mapped[datetime] = mapped_column(DateTime)
    type: Mapped[str] = mapped_column(String(4))
    asset: Mapped[str] = mapped_column(String(40))
    broker: Mapped[str] = mapped_column(String(120))
    allocation_class: Mapped[str] = mapped_column(String(120))
    trade_date: Mapped[date] = mapped_column(Date)
    settlement_date: Mapped[date] = mapped_column(Date)
    asset_currency: Mapped[str] = mapped_column(String(3))
    fx_rate: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    price: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    brokerage_fee: Mapped[Decimal] = mapped_column(Numeric(28, 12), default=Decimal('0'))
    other_fees: Mapped[Decimal] = mapped_column(Numeric(28, 12), default=Decimal('0'))
    notes: Mapped[str] = mapped_column(Text, default='')
    portfolio: Mapped['Portfolio'] = relationship(back_populates='transactions')
