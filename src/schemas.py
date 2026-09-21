from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Name = Annotated[str, Field(min_length=1, max_length=120)]
Amount = Annotated[float, Field(ge=0, le=1e15, allow_inf_nan=False)]
DecimalAmount = Annotated[Decimal, Field(ge=0, le=Decimal('1e15'), allow_inf_nan=False, max_digits=28, decimal_places=12)]
PositiveDecimalAmount = Annotated[Decimal, Field(gt=0, le=Decimal('1e15'), allow_inf_nan=False, max_digits=28, decimal_places=12)]


class Input(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')


class PortfolioInput(Input):
    name: Name


class TransactionInput(Input):
    trade_date: date
    settlement_date: date
    type: Literal['Buy', 'Sell']
    asset: Annotated[str, Field(min_length=1, max_length=40, pattern=r'^[A-Za-z0-9.^=:/_-]+$')]
    broker: Name
    allocation_class: Name = 'Sem classe'
    quantity: PositiveDecimalAmount
    price: DecimalAmount
    asset_currency: Annotated[str, Field(min_length=3, max_length=3, pattern=r'^[A-Za-z]{3}$')] = 'BRL'
    fx_rate: PositiveDecimalAmount | None = None
    brokerage_fee: DecimalAmount = Decimal('0')
    other_fees: DecimalAmount = Decimal('0')
    notes: Annotated[str, Field(max_length=5000)] = ''

    @field_validator('asset')
    @classmethod
    def normalize_ticker(cls, value):
        return value.upper()

    @field_validator('asset_currency')
    @classmethod
    def normalize_currency(cls, value):
        return value.upper()

    @field_validator('type', mode='before')
    @classmethod
    def normalize_type(cls, value):
        normalized = str(value).strip().casefold()
        return {'buy': 'Buy', 'compra': 'Buy', 'sell': 'Sell', 'venda': 'Sell'}.get(
            normalized, value
        )

    @model_validator(mode='after')
    def valid_dates_and_brl_rate(self):
        if self.trade_date > date.today():
            raise ValueError('A data de negociação não pode estar no futuro.')
        if self.settlement_date < self.trade_date:
            raise ValueError('A data de liquidação deve ser igual ou posterior à negociação.')
        if self.asset_currency == 'BRL':
            self.fx_rate = Decimal('1')
        return self


class QuoteInput(Input):
    date: date
    close: DecimalAmount
    currency: Annotated[str, Field(min_length=3, max_length=3, pattern=r'^[A-Za-z]{3}$')] | None = None
    dividends: Amount = 0
    stock_splits: Amount = 0

    @field_validator('currency')
    @classmethod
    def normalize_optional_currency(cls, value):
        return value.upper() if value else value

    @field_validator('date')
    @classmethod
    def not_future(cls, value):
        if value > date.today():
            raise ValueError('A cotação não pode estar no futuro.')
        return value


class TransactionSelectionInput(TransactionInput):
    instrument_id: int | None = Field(default=None, gt=0)


class TransactionOutput(TransactionInput):
    model_config = ConfigDict(from_attributes=True)
    id: int
    portfolio_id: int
    instrument_id: int


class InstrumentSelection(Input):
    instrument_id: int | None = Field(default=None, gt=0)
    provider_currency_confirmed: bool = False
    quote_currency: Annotated[str, Field(min_length=3, max_length=3, pattern=r'^[A-Za-z]{3}$')] | None = None
    symbol: Annotated[str, Field(min_length=1, max_length=40)]
    name: Annotated[str, Field(max_length=200)] = ''
    asset_type: Literal['STOCK', 'ETF', 'CRYPTO', 'OTHER'] = 'OTHER'
    exchange: Annotated[str, Field(max_length=40)] | None = None
    currency: Annotated[str, Field(min_length=3, max_length=3, pattern=r'^[A-Za-z]{3}$')] | None = None
    status: Literal['ACTIVE', 'INACTIVE', 'DELISTED'] = 'ACTIVE'
    isin: Annotated[str, Field(min_length=12, max_length=12)] | None = None
    provider: Annotated[str, Field(max_length=80)] | None = None
    provider_symbol: Annotated[str, Field(max_length=80)] | None = None
    provider_exchange: Annotated[str, Field(max_length=80)] | None = None
    aliases: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(
        default_factory=list, max_length=20
    )

    @field_validator('symbol', 'currency', 'quote_currency', 'status', 'asset_type')
    @classmethod
    def normalize_instrument_codes(cls, value):
        return value.upper() if value else None


class TransactionImportConfirm(Input):
    digest: Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]
    filename: Annotated[str, Field(min_length=1, max_length=255)]
    rows: Annotated[list[TransactionSelectionInput], Field(min_length=1, max_length=5000)]


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
