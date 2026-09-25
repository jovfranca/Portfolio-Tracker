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
    display_currency: Annotated[str, Field(min_length=3, max_length=3, pattern=r'^[A-Za-z]{3}$')] = 'BRL'

    @field_validator('display_currency')
    @classmethod
    def normalize_display_currency(cls, value):
        return value.upper()


class TransactionInput(Input):
    trade_date: date
    settlement_date: date
    type: Literal['Buy', 'Sell']
    asset: Annotated[str, Field(min_length=1, max_length=40, pattern=r'^[A-Za-z0-9.^=:/_-]+$')]
    broker: Name
    allocation_class: Name = 'Sem classe'
    quantity: PositiveDecimalAmount
    price: DecimalAmount
    transaction_currency: Annotated[str, Field(min_length=3, max_length=3, pattern=r'^[A-Za-z]{3}$')] | None = None
    fx_rate: PositiveDecimalAmount | None = None
    brokerage_fee: DecimalAmount = Decimal('0')
    other_fees: DecimalAmount = Decimal('0')
    notes: Annotated[str, Field(max_length=5000)] = ''

    @field_validator('asset')
    @classmethod
    def normalize_ticker(cls, value):
        return value.upper()

    @field_validator('transaction_currency')
    @classmethod
    def normalize_currency(cls, value):
        return value.upper() if value else value

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
        if self.transaction_currency == 'BRL':
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


class CorporateEventInput(Input):
    event_type: Literal['STOCK_SPLIT', 'REVERSE_SPLIT', 'DIVIDEND', 'JCP', 'AMORTIZATION']
    effective_date: date
    payment_date: date | None = None
    amount_per_unit: DecimalAmount | None = None
    conversion_factor: PositiveDecimalAmount | None = None
    currency: Annotated[str, Field(min_length=3, max_length=3, pattern=r'^[A-Za-z]{3}$')] | None = None
    notes: Annotated[str, Field(max_length=5000)] = ''

    @field_validator('event_type', mode='before')
    @classmethod
    def normalize_event_type(cls, value):
        return str(value).strip().upper().replace(' ', '_').replace('-', '_')

    @field_validator('currency')
    @classmethod
    def normalize_event_currency(cls, value):
        return value.upper() if value else value

    @model_validator(mode='after')
    def valid_event_values(self):
        if self.effective_date > date.today():
            raise ValueError('A data efetiva não pode estar no futuro.')
        if self.payment_date is not None and self.payment_date < self.effective_date:
            raise ValueError('A data de pagamento não pode preceder a data efetiva.')
        if self.event_type in {'STOCK_SPLIT', 'REVERSE_SPLIT'}:
            if self.conversion_factor is None or self.conversion_factor == 1:
                raise ValueError('Informe um fator de conversão positivo e diferente de 1.')
            if self.event_type == 'STOCK_SPLIT' and self.conversion_factor < 1:
                raise ValueError('Um desdobramento deve ter fator maior que 1.')
            if self.event_type == 'REVERSE_SPLIT' and self.conversion_factor > 1:
                raise ValueError('Um grupamento deve ter fator menor que 1.')
            if self.amount_per_unit is not None or self.currency is not None:
                raise ValueError('Desdobramentos usam somente o fator de conversão.')
        else:
            if self.amount_per_unit is None or not self.currency:
                raise ValueError('Eventos de renda exigem valor por unidade e moeda.')
            if self.conversion_factor is not None:
                raise ValueError('Eventos de renda não usam fator de conversão.')
        return self


class CorporateEventOutput(CorporateEventInput):
    model_config = ConfigDict(from_attributes=True)
    id: int
    asset_id: int
    source: str


class TransactionSelectionInput(TransactionInput):
    instrument_id: int | None = Field(default=None, gt=0)


class TransactionOutput(TransactionInput):
    model_config = ConfigDict(from_attributes=True)
    id: int
    portfolio_id: int
    instrument_id: int
    transaction_currency_locked: bool


class CustomInstrumentInput(Input):
    symbol: Annotated[str, Field(min_length=1, max_length=40, pattern=r'^[A-Za-z0-9.^=:/_-]+$')]
    name: Annotated[str, Field(min_length=1, max_length=200)]
    asset_type: Literal['STOCK', 'ETF', 'CRYPTO', 'OTHER'] = 'OTHER'
    currency: Annotated[str, Field(min_length=3, max_length=3, pattern=r'^[A-Za-z]{3}$')]

    @field_validator('symbol', 'asset_type', 'currency')
    @classmethod
    def normalize_custom_codes(cls, value):
        return value.upper()


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
