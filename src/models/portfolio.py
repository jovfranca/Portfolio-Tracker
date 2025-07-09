from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import Integer, String, ForeignKey

from src.models.asset import Asset
from src.models.position import Position
from src.models.transaction import Transaction

class Base(DeclarativeBase):
    pass

class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)  # e.g. "Retirement", "Speculative"

    # Relationships to positions, transactions, assets
    positions: Mapped[list["Position"]] = relationship(
        back_populates="portfolio",
        cascade="all, delete-orphan"
    )
    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="portfolio",
        cascade="all, delete-orphan"
    )
    assets: Mapped[list["Asset"]] = relationship(
        back_populates="portfolio",
        cascade="all, delete-orphan"
    )