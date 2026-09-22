from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.api.market_data import _fetch_yfinance_rates, _parse_ptax_rows
from src.models import ExchangeRate
from src.rates import backfill_rates, convert_amount, get_rates, store_rates


@pytest.fixture
def session():
    engine = create_engine('sqlite://')
    ExchangeRate.__table__.create(engine)
    with Session(engine) as database_session:
        yield database_session


def row(day, rate='5.00', rate_type='FX', source='test-provider', rate_side=None):
    return {
        'currency': 'USD',
        'rate_type': rate_type,
        'rate_side': rate_side or ('MARKET' if rate_type == 'FX' else 'BUY'),
        'reference_date': day,
        'rate': Decimal(rate),
        'source': source,
        'retrieved_at': datetime(2024, 1, 1, tzinfo=timezone.utc),
    }


def test_exact_local_rate_does_not_call_provider(session):
    store_rates(session, [row(date(2024, 1, 8))])

    def unexpected_fetch(*args):
        pytest.fail('provider called for an exact cached rate')

    result = get_rates(session, 'usd', 'fx', date(2024, 1, 8), unexpected_fetch)
    assert len(result) == 1
    assert result[0].rate == Decimal('5.000000000000')
    assert result[0].source == 'test-provider'


def test_quote_to_display_currency_conversion_is_separate_from_transactions(session):
    store_rates(session, [row(date(2024, 1, 8), '5.00')])
    assert convert_amount(session, Decimal('860'), 'USD', 'BRL', date(2024, 1, 8)) == Decimal('4300')
    assert convert_amount(session, Decimal('4300'), 'BRL', 'USD', date(2024, 1, 8)) == Decimal('860')


def test_missing_business_date_is_fetched_and_stored(session):
    calls = []

    def fetch(currency, rate_type, start, end):
        calls.append((currency, rate_type, start, end))
        return [row(date(2024, 1, 8), '4.91')]

    result = get_rates(session, 'USD', 'FX', date(2024, 1, 8), fetch)
    assert result[0].reference_date == date(2024, 1, 8)
    assert result[0].rate == Decimal('4.910000000000')
    assert len(calls) == 1
    assert session.scalar(select(ExchangeRate)).source == 'test-provider'


def test_weekend_uses_previous_cached_rate_without_provider(session):
    store_rates(session, [row(date(2024, 1, 5), '4.88')])

    def unexpected_fetch(*args):
        pytest.fail('provider called although Friday was cached')

    result = get_rates(session, 'USD', 'FX', date(2024, 1, 7), unexpected_fetch)
    assert result[0].reference_date == date(2024, 1, 5)


def test_future_rate_is_rejected_without_calling_provider(session):
    def unexpected_fetch(*args):
        pytest.fail('provider called for a future date')

    with pytest.raises(ValueError, match='futuro'):
        get_rates(session, 'USD', 'FX', date.today().replace(year=date.today().year + 1), unexpected_fetch)


def test_rate_types_are_separate_and_existing_history_is_not_overwritten(session):
    assert store_rates(session, [
        row(date(2024, 1, 8), '4.90', 'FX', 'first'),
        row(date(2024, 1, 8), '4.85', 'PTAX', 'bcb', 'BUY'),
        row(date(2024, 1, 8), '4.95', 'PTAX', 'bcb', 'SELL'),
    ]) == 3
    assert store_rates(session, [row(date(2024, 1, 8), '9.99', 'FX', 'later')]) == 0

    rates = list(session.scalars(
        select(ExchangeRate).order_by(ExchangeRate.rate_type, ExchangeRate.rate_side)
    ))
    assert [(item.rate_type, item.rate_side, item.rate, item.source) for item in rates] == [
        ('FX', 'MARKET', Decimal('4.900000000000'), 'first'),
        ('PTAX', 'BUY', Decimal('4.850000000000'), 'bcb'),
        ('PTAX', 'SELL', Decimal('4.950000000000'), 'bcb'),
    ]


def test_backfill_fetches_each_series_once_and_only_inserts_missing_rows(session):
    store_rates(session, [row(date(2024, 1, 8), '4.90')])
    calls = []

    def fetch(currency, rate_type, start, end):
        calls.append((currency, rate_type, start, end))
        rows = [
            row(date(2024, 1, 8), '9.99', rate_type),
            row(date(2024, 1, 9), '4.92', rate_type),
        ]
        if rate_type == 'PTAX':
            rows += [
                row(date(2024, 1, 8), '10.01', rate_type, rate_side='SELL'),
                row(date(2024, 1, 9), '4.94', rate_type, rate_side='SELL'),
            ]
        return rows

    result = backfill_rates(
        session, ['USD'], ['FX', 'PTAX'], date(2024, 1, 8), date(2024, 1, 9), fetch
    )
    assert result == {'inserted': 5, 'series': 2}
    assert len(calls) == 2
    fx = session.scalar(select(ExchangeRate).where(ExchangeRate.rate_type == 'FX'))
    assert fx.rate == Decimal('4.900000000000')


@pytest.mark.parametrize('closing_name', ['Fechamento', 'Fechamento PTAX'])
def test_ptax_parser_stores_both_rates_from_closing_bulletin(closing_name):
    rows = _parse_ptax_rows('USD', 'PTAX', [
        {
            'cotacaoCompra': 4.79,
            'cotacaoVenda': 4.80,
            'dataHoraCotacao': '2024-01-08T10:00:00.000',
            'tipoBoletim': 'Abertura',
        },
        {
            'cotacaoCompra': 4.90,
            'cotacaoVenda': 4.91,
            'dataHoraCotacao': '2024-01-08T13:10:00.000',
            'tipoBoletim': closing_name,
        },
        {
            'cotacaoCompra': 4.91,
            'cotacaoVenda': 4.92,
            'dataHoraCotacao': '2024-01-08T13:20:00.000',
            'tipoBoletim': 'Intermediário',
        },
    ])
    assert [(row['rate_side'], row['rate']) for row in rows] == [
        ('BUY', Decimal('4.9')),
        ('SELL', Decimal('4.91')),
    ]
    assert {row['source'] for row in rows} == {'bcb-ptax-closing'}


def test_ptax_lookup_requires_and_returns_both_sides(session):
    store_rates(session, [row(date(2024, 1, 8), '4.90', 'PTAX', rate_side='BUY')])

    def fetch(currency, rate_type, start, end):
        return [
            row(end, '4.90', 'PTAX', rate_side='BUY'),
            row(end, '4.91', 'PTAX', rate_side='SELL'),
        ]

    result = get_rates(session, 'USD', 'PTAX', date(2024, 1, 8), fetch)
    assert [(rate.rate_side, rate.rate) for rate in result] == [
        ('BUY', Decimal('4.900000000000')),
        ('SELL', Decimal('4.910000000000')),
    ]


def test_ptax_parser_rejects_intraday_bulletins():
    with pytest.raises(ValueError):
        _parse_ptax_rows('USD', 'PTAX', [{
            'cotacaoCompra': 4.80, 'cotacaoVenda': 4.81,
            'dataHoraCotacao': '2024-01-08T10:00:00', 'tipoBoletim': 'Abertura',
        }])


@pytest.mark.parametrize('sell', [None, '0', 'NaN', 'Infinity'])
def test_ptax_parser_rejects_incomplete_or_invalid_closing_pair(sell):
    with pytest.raises(ValueError):
        _parse_ptax_rows('USD', 'PTAX', [{
            'cotacaoCompra': 4.80, 'cotacaoVenda': sell,
            'dataHoraCotacao': '2024-01-08T13:00:00', 'tipoBoletim': 'Fechamento PTAX',
        }])


def test_weekend_fetches_when_cache_may_be_missing_friday(session):
    store_rates(session, [row(date(2024, 1, 3))])
    calls = []

    def fetch(*args):
        calls.append(args)
        return [row(date(2024, 1, 5), '4.88')]

    result = get_rates(session, 'USD', 'FX', date(2024, 1, 7), fetch)
    assert calls
    assert result[0].reference_date == date(2024, 1, 5)


def test_storage_failure_does_not_return_successful_fallback(session):
    from sqlalchemy.exc import IntegrityError

    store_rates(session, [row(date(2024, 1, 5))])
    session.commit()
    with pytest.raises(IntegrityError):
        get_rates(session, 'USD', 'FX', date(2024, 1, 9), lambda *args: [
            row(date(2024, 1, 8)), row(date(2024, 1, 9), '-1'),
        ])
    assert [item.reference_date for item in session.scalars(select(ExchangeRate))] == [date(2024, 1, 5)]


def test_provider_failure_uses_cached_fallback(session):
    store_rates(session, [row(date(2024, 1, 5))])

    def offline(*args):
        raise OSError('offline')

    assert get_rates(session, 'USD', 'FX', date(2024, 1, 8), offline)[0].reference_date == date(2024, 1, 5)


def test_yahoo_does_not_freeze_the_current_days_live_rate(monkeypatch):
    import pandas as pd
    import yfinance as yf
    from src.api import market_data

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2024, 1, 9, 12, tzinfo=timezone.utc).astimezone(tz)

    class Ticker:
        def history(self, **kwargs):
            return pd.DataFrame(
                {'Close': [4.90, 5.10]},
                index=pd.to_datetime(['2024-01-08', '2024-01-09']).tz_localize('UTC'),
            )

    monkeypatch.setattr(market_data, 'datetime', Clock)
    monkeypatch.setattr(yf, 'Ticker', lambda ticker: Ticker())
    rows = _fetch_yfinance_rates('USD', 'FX', date(2024, 1, 8), date(2024, 1, 9))
    assert [(item['reference_date'], item['rate']) for item in rows] == [
        (date(2024, 1, 8), Decimal('4.9')),
    ]
