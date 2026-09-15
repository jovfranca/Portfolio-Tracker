from datetime import date, datetime
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

Name = Annotated[str, Field(min_length=1, max_length=120)]
Amount = Annotated[float, Field(ge=0, le=1e15, allow_inf_nan=False)]


class Input(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')


class PortfolioInput(Input):
    name: Name


class TransactionInput(Input):
    date_time: datetime
    type: Literal['Buy', 'Sell']
    asset: Annotated[str, Field(min_length=1, max_length=40, pattern=r'^[A-Za-z0-9.^=:/_-]+$')]
    broker: Name
    allocation_class: Name
    quantity: Annotated[float, Field(gt=0, le=1e15, allow_inf_nan=False)]
    price: Amount
    brokerage_fee: Amount = 0
    other_fees: Amount = 0
    notes: Annotated[str, Field(max_length=5000)] = ''

    @field_validator('asset')
    @classmethod
    def normalize_ticker(cls, value):
        return value.upper()

    @field_validator('date_time')
    @classmethod
    def local_datetime(cls, value):
        if value.tzinfo is not None:
            raise ValueError('Use data/hora local sem fuso, como no histórico original.')
        if value.date() > date.today():
            raise ValueError('A data da operação não pode estar no futuro.')
        return value


class QuoteInput(Input):
    date: date
    close: Amount
    dividends: Amount = 0
    stock_splits: Amount = 0

    @field_validator('date')
    @classmethod
    def not_future(cls, value):
        if value > date.today():
            raise ValueError('A cotação não pode estar no futuro.')
        return value


class TransactionOutput(TransactionInput):
    model_config = ConfigDict(from_attributes=True)
    id: int
    portfolio_id: int
