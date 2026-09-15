from datetime import datetime
from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.database import Base


class Transaction(Base):
    __tablename__ = 'transactions'
    __table_args__ = (
        CheckConstraint("type IN ('Buy', 'Sell')", name='type'),
        CheckConstraint('quantity > 0 AND price >= 0 AND brokerage_fee >= 0 AND other_fees >= 0', name='amounts'),
        Index('ix_transactions_portfolio_date', 'portfolio_id', 'date_time', 'id'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey('portfolios.id', ondelete='CASCADE'))
    date_time: Mapped[datetime] = mapped_column(DateTime)
    type: Mapped[str] = mapped_column(String(4))
    asset: Mapped[str] = mapped_column(String(40))
    broker: Mapped[str] = mapped_column(String(120))
    allocation_class: Mapped[str] = mapped_column(String(120))
    quantity: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    brokerage_fee: Mapped[float] = mapped_column(Float, default=0)
    other_fees: Mapped[float] = mapped_column(Float, default=0)
    notes: Mapped[str] = mapped_column(Text, default='')
    portfolio: Mapped['Portfolio'] = relationship(back_populates='transactions')
