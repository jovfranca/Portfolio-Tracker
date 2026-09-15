from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from src.database import Base


class Broker(Base):
    __tablename__ = 'brokers'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
