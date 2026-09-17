from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from src.database import Base
from src.market_prices import get_history, get_latest, get_stored_history, save_user_price
from src.models import (
    Asset, Instrument, LatestMarketQuote, MarketPrice, MarketPriceCoverage, Portfolio,
    UserDefinedPrice,
)


@pytest.fixture
def market_session():
    engine = create_engine('sqlite://')
    for table in [
        Portfolio.__table__, Instrument.__table__, Asset.__table__, MarketPrice.__table__,
        MarketPriceCoverage.__table__, LatestMarketQuote.__table__, UserDefinedPrice.__table__,
    ]:
        table.create(engine)
    with Session(engine) as session:
        instrument = Instrument(symbol='TEST', currency='USD')
        first = Portfolio(name='First')
        second = Portfolio(name='Second')
        session.add_all([instrument, first, second])
        session.flush()
        session.add_all([
            Asset(portfolio_id=first.id, instrument_id=instrument.id, ticker='TEST'),
            Asset(portfolio_id=second.id, instrument_id=instrument.id, ticker='TEST'),
        ])
        session.flush()
        yield session


def assets(session):
    return list(session.scalars(select(Asset).order_by(Asset.id)))


def history_row(day, price='10'):
    return {
        'date': day, 'price': Decimal(price), 'currency': 'USD', 'source': 'yfinance',
        'retrieved_at': datetime(2024, 1, 10, tzinfo=timezone.utc),
    }


def test_provider_history_is_shared_across_portfolios_and_not_refetched(market_session):
    first, second = assets(market_session)
    calls = []

    def fetch(*args):
        calls.append(args)
        return [history_row(date(2024, 1, 8))]

    assert get_history(
        market_session, first, date(2024, 1, 8), date(2024, 1, 8), fetch
    ).complete
    assert get_history(
        market_session, second, date(2024, 1, 8), date(2024, 1, 8),
        lambda *args: pytest.fail('covered shared range was fetched again'),
    ).prices[0].close == Decimal('10.000000000000')
    assert len(calls) == 1
    assert market_session.scalar(select(func.count()).select_from(MarketPrice)) == 1


def test_history_fetches_only_uncovered_subranges(market_session):
    asset = assets(market_session)[0]
    market_session.add_all([
        MarketPriceCoverage(
            instrument_id=asset.instrument_id, interval='1d', source='yfinance',
            start_date=date(2024, 1, 1), end_date=date(2024, 1, 3),
            retrieved_at=datetime.now(timezone.utc),
        ),
        MarketPriceCoverage(
            instrument_id=asset.instrument_id, interval='1d', source='yfinance',
            start_date=date(2024, 1, 6), end_date=date(2024, 1, 7),
            retrieved_at=datetime.now(timezone.utc),
        ),
    ])
    calls = []

    def fetch(symbol, currency, start, end):
        calls.append((start, end))
        return []

    result = get_history(market_session, asset, date(2024, 1, 1), date(2024, 1, 8), fetch)
    assert result.complete
    assert calls == [
        (date(2024, 1, 4), date(2024, 1, 5)),
        (date(2024, 1, 8), date(2024, 1, 8)),
    ]


def test_empty_provider_range_records_holiday_coverage(market_session):
    asset = assets(market_session)[0]
    calls = []

    def empty(*args):
        calls.append(args)
        return []

    first = get_history(market_session, asset, date(2024, 1, 1), date(2024, 1, 1), empty)
    second = get_history(market_session, asset, date(2024, 1, 1), date(2024, 1, 1), empty)
    assert first.complete and second.complete
    assert len(calls) == 1


def test_manual_price_wins_same_date_and_stays_private(market_session):
    first, second = assets(market_session)
    get_history(
        market_session, first, date(2024, 1, 8), date(2024, 1, 8),
        lambda *args: [history_row(date(2024, 1, 8), '10')],
    )
    save_user_price(
        market_session, first, date(2024, 1, 8), Decimal('12'), 'USD',
        dividends=Decimal('0.5'), stock_splits=Decimal('2'),
    )
    assert get_stored_history(market_session, first)[0].origin == 'user-defined'
    assert get_stored_history(market_session, first)[0].close == Decimal('12.000000000000')
    assert get_stored_history(market_session, first)[0].dividends == Decimal('0.500000000000')
    assert get_stored_history(market_session, second)[0].origin == 'shared'
    assert get_stored_history(market_session, second)[0].close == Decimal('10.000000000000')
    with pytest.raises(ValueError, match='conversão de moedas'):
        save_user_price(market_session, first, date(2024, 1, 9), Decimal('12'), 'BRL')


def test_latest_quote_uses_ttl_then_refreshes_and_keeps_market_timestamp(market_session):
    asset = assets(market_session)[0]
    now = datetime(2024, 1, 8, 15, tzinfo=timezone.utc)
    calls = []

    def fetch(symbol, currency):
        calls.append((symbol, currency))
        return {
            'price': Decimal(str(20 + len(calls))), 'currency': currency,
            'source': 'yfinance', 'market_at': now - timedelta(minutes=1),
            'retrieved_at': now,
        }

    first = get_latest(market_session, asset, fetch, now)
    cached = get_latest(
        market_session, asset, lambda *args: pytest.fail('fresh quote was fetched'),
        now + timedelta(minutes=14),
    )
    refreshed = get_latest(market_session, asset, fetch, now + timedelta(minutes=16))
    assert first.price.close == cached.price.close == Decimal('21')
    assert refreshed.price.close == Decimal('22')
    assert first.price.market_at == now - timedelta(minutes=1)
    assert first.price.retrieved_at == now
    assert len(calls) == 2


def test_provider_failure_returns_explicit_incomplete_or_stale_result(market_session):
    asset = assets(market_session)[0]
    history = get_history(
        market_session, asset, date(2024, 1, 8), date(2024, 1, 9),
        lambda *args: (_ for _ in ()).throw(OSError('offline')),
    )
    latest = get_latest(
        market_session, asset, lambda *args: (_ for _ in ()).throw(OSError('offline')),
    )
    assert not history.complete
    assert history.missing_ranges == [(date(2024, 1, 8), date(2024, 1, 9))]
    assert not latest.available and latest.stale


def test_today_manual_quote_does_not_call_provider(market_session):
    asset = assets(market_session)[0]
    now = datetime(2024, 1, 8, 15, tzinfo=timezone.utc)
    save_user_price(market_session, asset, now.date(), Decimal('12'))
    calls = []
    result = get_latest(market_session, asset, lambda *args: calls.append(args), now)
    assert calls == []
    assert result.price.origin == 'user-defined'
    assert not result.stale


def test_local_today_manual_quote_wins_after_utc_midnight(market_session, monkeypatch):
    asset = assets(market_session)[0]
    now = datetime(2026, 9, 17, 0, 30, tzinfo=timezone.utc)
    save_user_price(market_session, asset, date(2026, 9, 16), Decimal('12'))
    monkeypatch.setattr('src.market_prices._local_date', lambda value: date(2026, 9, 16))
    result = get_latest(
        market_session, asset, lambda *args: pytest.fail('manual quote should win'), now,
    )
    assert result.price.origin == 'user-defined'
    assert not result.stale


def test_zero_manual_price_and_edit_of_migrated_provider_price(market_session):
    from src.schemas import QuoteInput
    asset = assets(market_session)[0]
    quote = QuoteInput(date=date(2024, 1, 8), close='0')
    market_session.add(UserDefinedPrice(
        asset_id=asset.id, reference_date=quote.date, price=10,
        currency='USD', source='yfinance',
    ))
    market_session.flush()
    save_user_price(market_session, asset, quote.date, quote.close)
    resolved = get_stored_history(market_session, asset)[0]
    assert resolved.close == 0
    assert resolved.source == 'manual'


def test_manual_history_is_resolved_before_provider_without_sharing_coverage(market_session):
    first, second = assets(market_session)
    day = date(2024, 1, 8)
    save_user_price(market_session, first, day, Decimal('12'))
    calls = []
    fetch = lambda *args: calls.append(args) or []
    result = get_history(market_session, first, day, day, fetch)
    assert result.complete and calls == []
    get_history(market_session, second, day, day, fetch)
    assert len(calls) == 1


def test_daily_close_is_not_replaced_by_older_intraday_quote(market_session):
    from src.market_prices import history_for_domain
    asset = assets(market_session)[0]
    day = date(2024, 1, 8)
    get_history(market_session, asset, day, day, lambda *args: [history_row(day, '20')])
    market_session.add(LatestMarketQuote(
        instrument_id=asset.instrument_id, source='yfinance', currency='USD',
        price=Decimal('10'), market_at=datetime(2024, 1, 8, 12, tzinfo=timezone.utc),
        retrieved_at=datetime(2024, 1, 8, 12, tzinfo=timezone.utc),
    ))
    history = history_for_domain(market_session, asset)
    assert history[0].close == Decimal('20')
    assert history[0].origin == 'shared'


def test_stored_dates_without_coverage_are_not_downloaded_again(market_session):
    from src.market_prices import _store_market_prices
    asset = assets(market_session)[0]
    _store_market_prices(market_session, asset.instrument, [history_row(date(2024, 1, 8))])
    calls = []
    get_history(market_session, asset, date(2024, 1, 8), date(2024, 1, 9),
                lambda symbol, currency, start, end: calls.append((start, end)) or [])
    assert calls == [(date(2024, 1, 9), date(2024, 1, 9))]


@pytest.mark.parametrize('bad_value', [{'currency': 'BRL'}, {'price': Decimal('NaN')}])
def test_invalid_provider_history_is_not_persisted_or_marked_complete(market_session, bad_value):
    asset = assets(market_session)[0]
    day = date(2024, 1, 8)
    result = get_history(market_session, asset, day, day,
                         lambda *args: [history_row(day) | bad_value])
    assert not result.complete
    assert not result.prices
    assert market_session.scalar(select(func.count()).select_from(MarketPriceCoverage)) == 0


@pytest.mark.parametrize('operation', ['fetch_history', 'fetch_latest'])
@pytest.mark.parametrize('currency', ['BRL', 'GBp', None])
def test_yahoo_currency_is_verified(monkeypatch, operation, currency):
    import pandas as pd
    import yfinance as yf
    from types import SimpleNamespace
    from src.api import market_data
    frame = pd.DataFrame({'Close': [20.]}, index=pd.to_datetime(['2024-01-08T12:00:00Z']))
    monkeypatch.setattr(yf, 'Ticker', lambda symbol: SimpleNamespace(
        history=lambda **kwargs: frame, get_history_metadata=lambda: {'currency': currency},
    ))
    args = ('TEST', 'USD')
    if operation == 'fetch_history':
        args += (date(2024, 1, 8), date(2024, 1, 8))
    with pytest.raises(ValueError, match='currency'):
        getattr(market_data, operation)(*args)


def test_yahoo_does_not_freeze_an_unfinished_exchange_day(monkeypatch):
    import pandas as pd
    import yfinance as yf
    from types import SimpleNamespace
    from src.api import market_data

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2024, 1, 9, 1, tzinfo=timezone.utc)

    frame = pd.DataFrame({'Close': [20.]}, index=pd.DatetimeIndex(
        ['2024-01-08'], tz='America/New_York',
    ))
    monkeypatch.setattr(market_data, 'datetime', Clock)
    monkeypatch.setattr(yf, 'Ticker', lambda symbol: SimpleNamespace(
        history=lambda **kwargs: frame, get_history_metadata=lambda: {
            'currency': 'USD', 'exchangeTimezoneName': 'America/New_York',
        },
    ))
    with pytest.raises(ValueError, match='final'):
        market_data.fetch_history('TEST', 'USD', date(2024, 1, 8), date(2024, 1, 8))


def test_xlk_daily_bar_keeps_exchange_trading_date(monkeypatch):
    import pandas as pd
    import yfinance as yf
    from types import SimpleNamespace
    from src.api import market_data

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = datetime(2026, 9, 16, 12, tzinfo=timezone.utc)
            return value if tz is None else value.astimezone(tz)

    frame = pd.DataFrame(
        {'Close': [183.74], 'Dividends': [0.0], 'Stock Splits': [0.0]},
        index=pd.DatetimeIndex(['2026-09-15 00:00'], tz='America/New_York'),
    )
    monkeypatch.setattr(market_data, 'datetime', Clock)
    monkeypatch.setattr(yf, 'Ticker', lambda symbol: SimpleNamespace(
        history=lambda **kwargs: frame,
        get_history_metadata=lambda: {
            'currency': 'USD', 'exchangeTimezoneName': 'America/New_York',
        },
    ))
    rows = market_data.fetch_history(
        'XLK', 'USD', date(2026, 9, 14), date(2026, 9, 16),
    )
    assert rows[0]['date'] == date(2026, 9, 15)
    assert rows[0]['price'] == Decimal('183.74')


def test_daily_reference_is_not_shifted_by_postgres_session_timezone():
    from src.market_prices import _reference_date
    sao_paulo = timezone(timedelta(hours=-3))
    # PostgreSQL may render 2026-09-15 00:00 UTC as the prior local evening.
    stored_value = datetime(2026, 9, 14, 21, tzinfo=sao_paulo)
    assert _reference_date(stored_value) == date(2026, 9, 15)


def test_latest_uses_regular_market_metadata_not_last_minute_bar(monkeypatch):
    import pandas as pd
    import yfinance as yf
    from types import SimpleNamespace
    from src.api import market_data

    def unexpected_history(**kwargs):
        pytest.fail('latest quote must not use a one-minute candle')

    monkeypatch.setattr(yf, 'Ticker', lambda symbol: SimpleNamespace(
        history=unexpected_history,
        get_history_metadata=lambda: {
            'currency': 'USD',
            'exchangeTimezoneName': 'America/New_York',
            'regularMarketPrice': 183.93,
            'regularMarketTime': pd.Timestamp('2026-09-16 16:00', tz='America/New_York'),
            'postMarketPrice': 183.96,
        },
    ))
    quote = market_data.fetch_latest('XLK', 'USD')
    assert quote['price'] == Decimal('183.93')
    assert quote['market_at'] == datetime(
        2026, 9, 16, 16, tzinfo=quote['market_at'].tzinfo,
    )


def test_latest_date_survives_database_timezone_conversion(market_session):
    from src.market_prices import _as_resolved
    asset = assets(market_session)[0]
    now = datetime(2024, 1, 9, 1, tzinfo=timezone.utc)
    market_at = datetime(2024, 1, 8, 19, tzinfo=timezone(timedelta(hours=-5)))
    result = get_latest(market_session, asset, lambda *args: {
        'price': Decimal('20'), 'currency': 'USD', 'market_at': market_at,
        'retrieved_at': now,
    }, now)
    assert result.price.date == date(2024, 1, 8)
    cached = market_session.scalar(select(LatestMarketQuote))
    # PostgreSQL TIMESTAMPTZ preserves the instant, not the original offset.
    cached.market_at = market_at.astimezone(timezone.utc)
    assert _as_resolved(cached).date == date(2024, 1, 8)
