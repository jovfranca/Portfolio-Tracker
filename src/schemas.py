from datetime import date, datetime
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


class RateBackfillInput(Input):
    currencies: Annotated[list[str], Field(min_length=1, max_length=50)]
    rate_types: Annotated[list[Literal['FX', 'PTAX']], Field(min_length=1)] = Field(
        default_factory=lambda: ['FX', 'PTAX']
    )
    start_date: date
    end_date: date

    @field_validator('currencies')
    @classmethod
    def normalize_currencies(cls, values):
        normalized = []
        for value in values:
            value = value.strip().upper()
            if len(value) != 3 or not value.isalpha():
                raise ValueError('Use códigos de moeda ISO com três letras.')
            if value not in normalized:
                normalized.append(value)
        return normalized

    @model_validator(mode='after')
    def valid_period(self):
        if self.end_date < self.start_date:
            raise ValueError('A data final deve ser igual ou posterior à data inicial.')
        if self.end_date > date.today():
            raise ValueError('A data final não pode estar no futuro.')
        if (self.end_date - self.start_date).days > 3660:
            raise ValueError('O período de backfill não pode exceder dez anos.')
        return self
