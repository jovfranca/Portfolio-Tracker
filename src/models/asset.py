from datetime import date
from sqlalchemy import Date, Float, ForeignKey, String, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.database import Base


class Asset(Base):
    __tablename__ = 'assets'
    __table_args__ = (UniqueConstraint('portfolio_id', 'ticker'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey('portfolios.id', ondelete='CASCADE'))
    ticker: Mapped[str] = mapped_column(String(40))
    asset_class: Mapped[str] = mapped_column(String(120), default='')
    sector: Mapped[str] = mapped_column(String(120), default='')
    sub_sector: Mapped[str] = mapped_column(String(120), default='')
    portfolio: Mapped['Portfolio'] = relationship(back_populates='assets')
    history: Mapped[list['AssetHistory']] = relationship(
        back_populates='asset', cascade='all, delete-orphan', order_by='AssetHistory.date')


class AssetHistory(Base):
    __tablename__ = 'asset_history'
    __table_args__ = (UniqueConstraint('asset_id', 'date'), CheckConstraint('close >= 0', name='close'))
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey('assets.id', ondelete='CASCADE'))
    date: Mapped[date] = mapped_column(Date)
    close: Mapped[float] = mapped_column(Float)
    dividends: Mapped[float] = mapped_column(Float, default=0)
    stock_splits: Mapped[float] = mapped_column(Float, default=0)
    source: Mapped[str] = mapped_column(String(30), default='manual')
    asset: Mapped['Asset'] = relationship(back_populates='history')
