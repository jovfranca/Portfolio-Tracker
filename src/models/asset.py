from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.database import Base


class Asset(Base):
    __tablename__ = 'assets'
    __table_args__ = (UniqueConstraint('portfolio_id', 'instrument_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey('portfolios.id', ondelete='CASCADE'))
    instrument_id: Mapped[int] = mapped_column(ForeignKey('instruments.id', ondelete='RESTRICT'))
    ticker: Mapped[str] = mapped_column(String(40))
    asset_class: Mapped[str] = mapped_column(String(120), default='')
    sector: Mapped[str] = mapped_column(String(120), default='')
    sub_sector: Mapped[str] = mapped_column(String(120), default='')
    portfolio: Mapped['Portfolio'] = relationship(back_populates='assets')
    instrument: Mapped['Instrument'] = relationship()
    manual_prices: Mapped[list['UserDefinedPrice']] = relationship(
        back_populates='asset', cascade='all, delete-orphan',
        order_by='UserDefinedPrice.reference_date')
    corporate_events: Mapped[list['UserCorporateEvent']] = relationship(
        back_populates='asset', cascade='all, delete-orphan',
        order_by='(UserCorporateEvent.effective_date, UserCorporateEvent.id)')
