from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from src.instruments import add_alias, create_instrument, resolve_instrument
from src.market_prices import get_latest, get_stored_history, save_user_price
from src.models import (
    Asset, Instrument, InstrumentAlias, LatestMarketQuote, MarketPrice,
    MarketPriceCoverage, Portfolio, ProviderInstrument, UserDefinedPrice,
)
from src.services import ensure_asset


@pytest.fixture
def session():
    engine = create_engine('sqlite://')
    for table in [
        Portfolio.__table__, Instrument.__table__, ProviderInstrument.__table__,
        InstrumentAlias.__table__, Asset.__table__, MarketPrice.__table__,
        MarketPriceCoverage.__table__, LatestMarketQuote.__table__,
        UserDefinedPrice.__table__,
    ]:
        table.create(engine)
    from sqlalchemy import text
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE transactions (id integer, instrument_id integer, asset_currency text, portfolio_id integer)'))
    with Session(engine) as value:
        yield value


def test_petr4_is_canonical_while_fetch_uses_provider_symbol(session):
    instrument = create_instrument(session, quote_currency='BRL', symbol='PETR4', name='Petrobras PN', asset_type='STOCK',
        exchange='B3', currency='BRL', provider='yfinance',
        provider_symbol='PETR4.SA', aliases=['PETR4.SA'],
    )
    portfolio = Portfolio(name='Brazil')
    session.add(portfolio)
    session.flush()
    asset = ensure_asset(session, portfolio.id, instrument)
    calls = []

    result = get_latest(session, asset, lambda symbol, currency: calls.append(
        (symbol, currency)
    ) or {
        'price': Decimal('30'), 'currency': 'BRL',
        'market_at': datetime(2024, 1, 8, 18, tzinfo=timezone.utc),
        'retrieved_at': datetime(2024, 1, 8, 19, tzinfo=timezone.utc),
    }, datetime(2024, 1, 8, 19, tzinfo=timezone.utc))

    assert instrument.symbol == 'PETR4'
    assert calls == [('PETR4.SA', 'BRL')]
    assert result.price.close == Decimal('30')


def test_btcbrl_alias_resolves_to_bitcoin_not_quote_pair(session):
    bitcoin = create_instrument(session, quote_currency='BRL', symbol='BTC', name='Bitcoin', asset_type='CRYPTO', currency='BRL',
        provider='yfinance', provider_symbol='BTC-BRL', aliases=['BTCBRL'],
    )
    resolution = resolve_instrument(session, ' btcbrl ', currency='BRL')
    assert resolution.status == 'resolved'
    assert resolution.instrument.id == bitcoin.id
    assert resolution.instrument.symbol == 'BTC'
    assert resolution.instrument.provider_mappings[0].provider_symbol == 'BTC-BRL'


def test_aapl_compatible_mapping_and_aliases_share_one_portfolio_asset(session):
    apple = create_instrument(session, quote_currency='USD', symbol='AAPL', name='Apple Inc.', asset_type='STOCK',
        currency='USD', provider='yfinance', provider_symbol='AAPL',
        aliases=['APPLE'],
    )
    portfolio = Portfolio(name='US')
    session.add(portfolio)
    session.flush()
    first = ensure_asset(session, portfolio.id, resolve_instrument(session, 'AAPL').instrument)
    second = ensure_asset(session, portfolio.id, resolve_instrument(session, 'APPLE').instrument)
    assert first.id == second.id
    assert session.scalar(select(func.count()).select_from(Asset)) == 1
    assert apple.symbol == 'AAPL'


def test_ambiguous_alias_is_explicit(session):
    first = create_instrument(session, symbol='ABC', currency='USD')
    second = create_instrument(session, symbol='ABC', currency='USD')
    add_alias(session, first, 'SHARED')
    add_alias(session, second, 'SHARED')
    result = resolve_instrument(session, 'shared', currency='USD')
    assert result.status == 'ambiguous'
    assert {item.id for item in result.candidates} == {first.id, second.id}


def test_unknown_identifier_is_not_created(session):
    result = resolve_instrument(session, 'DOES-NOT-EXIST', currency='USD')
    assert result.status == 'unresolved'
    assert session.scalar(select(func.count()).select_from(Instrument)) == 0


def test_provider_quote_caches_are_distinct_per_mapping(session):
    instrument = create_instrument(session, quote_currency='BRL', symbol='BTC', currency='BRL', provider='yfinance',
        provider_symbol='BTC-BRL',
    )
    usd = ProviderInstrument(
        instrument_id=instrument.id, provider='yfinance',
        provider_symbol='BTC-USD', quote_currency='USD', active=True,
    )
    session.add(usd)
    session.flush()
    brl = session.scalar(select(ProviderInstrument).where(ProviderInstrument.quote_currency == 'BRL'))
    now = datetime.now(timezone.utc)
    session.add_all([
        MarketPrice(provider_instrument_id=brl.id, reference_at=now, price=300000,
                    currency='BRL', source='yfinance', retrieved_at=now),
        MarketPrice(provider_instrument_id=usd.id, reference_at=now, price=60000,
                    currency='USD', source='yfinance', retrieved_at=now),
        LatestMarketQuote(
            provider_instrument_id=brl.id, price=Decimal('300000'), currency='BRL',
            source='yfinance', retrieved_at=now,
        ),
        LatestMarketQuote(
            provider_instrument_id=usd.id, price=Decimal('60000'), currency='USD',
            source='yfinance', retrieved_at=now,
        ),
        MarketPriceCoverage(
            provider_instrument_id=brl.id, interval='1d', source='yfinance',
            start_date=date(2024, 1, 1), end_date=date(2024, 1, 8), retrieved_at=now,
        ),
        MarketPriceCoverage(
            provider_instrument_id=usd.id, interval='1d', source='yfinance',
            start_date=date(2024, 1, 1), end_date=date(2024, 1, 8), retrieved_at=now,
        ),
    ])
    session.flush()
    assert session.scalar(select(func.count()).select_from(LatestMarketQuote)) == 2
    assert session.scalar(select(func.count()).select_from(MarketPriceCoverage)) == 2
    assert session.scalar(select(func.count()).select_from(MarketPrice)) == 2


def test_inactive_instrument_keeps_manual_history(session):
    instrument = create_instrument(session, quote_currency='NOK', symbol='SHLF', name='Shelf Drilling', currency='NOK',
        asset_type='STOCK', status='DELISTED', provider='yfinance', provider_symbol='SHLF.OL',
    )
    portfolio = Portfolio(name='Historical')
    session.add(portfolio)
    session.flush()
    asset = ensure_asset(session, portfolio.id, instrument)
    save_user_price(session, asset, datetime(2024, 1, 8).date(), Decimal('10'), 'NOK')
    assert get_stored_history(session, asset)[0].close == Decimal('10')
    assert asset.instrument.status == 'DELISTED'


def test_inactive_mapping_keeps_shared_history_and_cached_quote(session):
    from src.market_prices import history_for_domain
    instrument = create_instrument(session, quote_currency='USD', symbol='OLD', currency='USD', asset_type='STOCK',
                                   provider_symbol='OLD.X', status='DELISTED')
    portfolio = Portfolio(name='History')
    session.add(portfolio)
    session.flush()
    asset = ensure_asset(session, portfolio.id, instrument)
    mapping = instrument.provider_mappings[0]
    mapping.active = False
    now = datetime(2024, 1, 9, tzinfo=timezone.utc)
    session.add_all([
        MarketPrice(provider_instrument_id=mapping.id, reference_at=now,
                    price=10, currency='USD', source='yfinance', retrieved_at=now),
        LatestMarketQuote(provider_instrument_id=mapping.id, price=11,
                          currency='USD', source='yfinance', retrieved_at=now,
                          reference_date=date(2024, 1, 10)),
    ])
    session.flush()
    assert get_stored_history(session, asset)[0].close == 10
    assert history_for_domain(session, asset)[-1].close == 11
    result = get_latest(session, asset, lambda *args: pytest.fail('Inactive mapping fetched'))
    assert result.price.close == 11
    assert result.stale


def test_replacement_mapping_preserves_old_history_and_cached_quote(session):
    from src.market_prices import history_for_domain
    instrument = create_instrument(session, symbol='LISTING', currency='USD',
        asset_type='STOCK', provider_symbol='OLD.X', quote_currency='USD')
    portfolio = Portfolio(name='Replacement history')
    session.add(portfolio)
    session.flush()
    asset = ensure_asset(session, portfolio.id, instrument)
    old = instrument.provider_mappings[0]
    old.active = False
    now = datetime(2024, 1, 8, tzinfo=timezone.utc)
    session.add_all([
        MarketPrice(provider_instrument_id=old.id, reference_at=now,
                    price=10, currency='USD', source='yfinance', retrieved_at=now),
        LatestMarketQuote(provider_instrument_id=old.id, price=11,
            currency='USD', source='yfinance', retrieved_at=now,
            reference_date=date(2024, 1, 9)),
        ProviderInstrument(instrument_id=instrument.id, provider='yfinance',
            provider_symbol='NEW.X', quote_currency='USD', active=True),
    ])
    session.flush()
    assert [row.close for row in get_stored_history(session, asset)] == [10]
    assert [row.close for row in history_for_domain(session, asset)] == [10, 11]
    def unavailable(symbol, currency):
        assert (symbol, currency) == ('NEW.X', 'USD')
        raise ValueError('Provider unavailable')
    result = get_latest(session, asset, unavailable)
    assert result.stale and result.price.close == 11


def test_transaction_currency_cannot_be_valued_with_different_quote_currency(session):
    from fastapi import HTTPException
    from src.services import require_instrument
    instrument = create_instrument(session, symbol='AAPL', currency='USD', asset_type='STOCK')
    with pytest.raises(HTTPException) as error:
        require_instrument(session, 'AAPL', 'BRL', instrument.id)
    assert error.value.status_code == 422


def test_legacy_resolution_rejects_mismatched_currency(session):
    from src.import_legacy import _legacy_instrument
    create_instrument(session, symbol='AAPL', currency='USD', asset_type='STOCK')
    with pytest.raises(ValueError, match='USD'):
        _legacy_instrument(session, 'AAPL', 'BRL')


def test_search_finds_local_aliases_and_names_with_spaces(session, monkeypatch):
    from src.instruments import search_instruments
    instrument = create_instrument(session, symbol='BTC', currency='BRL',
                                   name='Bitcoin Digital Asset', aliases=['BTCBRL'])
    monkeypatch.setattr('src.instruments.market_data.search_instruments', lambda q: [])
    for query in [' btcbrl ', 'Bitcoin Digital']:
        assert search_instruments(session, query)[0]['instrument_id'] == instrument.id


def test_provider_search_retains_results_without_currency(monkeypatch):
    from io import StringIO
    from src.api import market_data
    monkeypatch.setattr(market_data, 'urlopen', lambda *a, **k: StringIO(
        '{"quotes": [{"symbol": "PETR4.SA", "shortname": "Petrobras", "quoteType": "EQUITY"}]}'
    ))
    result = market_data.search_instruments('Petrobras')
    assert len(result) == 1
    assert result[0]['provider_symbol'] == 'PETR4.SA'
    assert result[0]['quote_currency'] is None


def test_unresolved_import_preserves_row_for_explicit_selection(session):
    from sqlalchemy import text
    from src.transaction_import import preview_import
    content = (b'ticker,broker,type,trade_date,settlement_date,quantity,unit_price,asset_currency\n'
               b'UNKNOWN,Example,Buy,2024-01-02,2024-01-03,1,10,BRL\n')
    result = preview_import(session, 'input.csv', content, portfolio_id=1)
    row = result['rows'][0]
    assert not row['valid']
    assert row['instrument_resolution'] == 'unresolved'
    assert row['data']['asset'] == 'UNKNOWN'
    assert row['data']['price'] == '10'


def test_positions_expose_asset_identity_for_duplicate_symbols():
    from types import SimpleNamespace
    from src.domain import overview
    transactions = [SimpleNamespace(
        id=i, instrument_id=i, asset='SAME', broker='Example', allocation_class='Stocks',
        asset_currency='BRL', type='Buy', quantity=Decimal('1'), price=Decimal('10'),
        trade_date=date(2024, 1, 2), date_time=datetime(2024, 1, 2),
    ) for i in (1, 2)]
    assets = [SimpleNamespace(id=i + 10, instrument_id=i, ticker='SAME', history=[]) for i in (1, 2)]
    result = overview(transactions, assets)
    assert [position['asset_id'] for position in result['positions']] == [11, 12]


def test_crypto_pairs_reuse_identity_and_allow_brl(session):
    from src.services import require_instrument
    first = create_instrument(session, quote_currency='USD', symbol='BTC', asset_type='CRYPTO', currency='USD', provider_symbol='BTC-USD')
    second = create_instrument(session, quote_currency='EUR', symbol='BTC', asset_type='CRYPTO', currency='EUR', provider_symbol='BTC-EUR')
    assert first.id == second.id
    assert first.currency is None
    assert require_instrument(session, 'BTC', 'BRL', first.id) is first
    assert len(list(session.scalars(select(ProviderInstrument)))) == 2


def test_manual_instrument_never_fetches(session):
    from src.market_prices import get_history
    instrument = create_instrument(session, symbol='PRIVATE', currency=None, asset_type='OTHER')
    portfolio = Portfolio(name='Manual')
    session.add(portfolio)
    session.flush()
    asset = ensure_asset(session, portfolio.id, instrument)
    assert not get_latest(session, asset, lambda *a: pytest.fail('Unexpected provider call')).available
    save_user_price(session, asset, date(2024, 1, 2), Decimal('42'), 'BRL')
    assert get_latest(session, asset, lambda *a: pytest.fail('Unexpected provider call')).price.close == 42
    assert get_history(session, asset, date(2024, 1, 2), date(2024, 1, 3),
                       lambda *a: pytest.fail('Unexpected history call')).prices[0].close == 42


def test_mapping_selection_matches_target_and_rejects_ambiguity(session):
    from src.instruments import provider_mapping
    instrument = create_instrument(session, quote_currency='USD', symbol='BTC', asset_type='CRYPTO', currency='USD', provider_symbol='BTC-USD')
    create_instrument(session, quote_currency='EUR', symbol='BTC', asset_type='CRYPTO', currency='EUR', provider_symbol='BTC-EUR')
    assert provider_mapping(session, instrument, currency='EUR').provider_symbol == 'BTC-EUR'
    with pytest.raises(ValueError, match='unavailable'):
        provider_mapping(session, instrument, currency='BRL')
    with pytest.raises(ValueError, match='ambiguous'):
        provider_mapping(session, instrument)


def test_provider_currency_cannot_be_unknown(session):
    with pytest.raises(ValueError, match='currency'):
        create_instrument(session, quote_currency=None, symbol='GTLSX', asset_type='STOCK', currency=None, provider_symbol='GTLSX')


def test_search_reconciles_mapping_and_filters_types(session, monkeypatch):
    from src.instruments import search_instruments
    instrument = create_instrument(session, quote_currency='USD', symbol='BTC', name='Bitcoin', asset_type='CRYPTO', currency='USD', provider_symbol='BTC-USD')
    monkeypatch.setattr('src.instruments.market_data.search_instruments', lambda q: [
        dict(symbol='BTC', name='Bitcoin', asset_type='CRYPTO', currency='USD', provider='yfinance', provider_symbol='BTC-USD'),
        dict(symbol='GBTC', name='Bitcoin Trust', asset_type='ETF', currency='USD', provider='yfinance', provider_symbol='GBTC'),
    ])
    results = search_instruments(session, 'Bitcoin')
    assert len(results) == 2
    assert results[0]['instrument_id'] == instrument.id
    assert len(search_instruments(session, 'Bitcoin', category='CRYPTO')) == 1


def test_new_crypto_quote_variant_suggests_existing_identity(session, monkeypatch):
    from src.instruments import search_instruments
    btc = create_instrument(session, symbol='BTC', name='Bitcoin', asset_type='CRYPTO',
                            provider_symbol='BTC-USD', quote_currency='USD')
    monkeypatch.setattr('src.instruments.market_data.search_instruments', lambda q: [
        dict(symbol='BTC', name='Bitcoin', asset_type='CRYPTO', currency=None, quote_currency='EUR',
             provider='yfinance', provider_symbol='BTC-EUR'),
    ])
    result = search_instruments(session, 'BTC-EUR')[0]
    assert result['instrument_id'] == btc.id
    assert result['provider_symbol'] == 'BTC-EUR'
    assert session.scalar(select(func.count()).select_from(ProviderInstrument)) == 1


def test_provider_crypto_base_metadata_and_missing_base_are_explicit(monkeypatch):
    from io import StringIO
    from src.api import market_data
    monkeypatch.setattr(market_data, 'urlopen', lambda *a, **k: StringIO(
        '{"quotes": [{"symbol": "BTC-USD", "fromCurrency": "BTC", "currency": "USD", "quoteType": "CRYPTOCURRENCY"},'
        '{"symbol": "BTC-EUR", "quoteType": "CRYPTOCURRENCY"},'
        '{"symbol": "GBTC", "shortname": "Bitcoin Trust", "quoteType": "ETF", "exchange": "PCX", "currency": "USD"}]}'
    ))
    results = market_data.search_instruments('Bitcoin')
    assert results[0]['symbol'] == 'BTC'
    assert results[0]['currency'] is None
    assert results[0]['quote_currency'] == 'USD'
    assert results[1]['symbol'] == ''
    assert results[1]['quote_currency'] is None
    assert results[2]['asset_type'] == 'ETF'
    assert results[2]['exchange'] == 'PCX'


def test_explicit_petr4_market_variant_association_and_same_currency_ambiguity(session):
    from src.instruments import provider_mapping
    stock = create_instrument(session, symbol='PETR4', asset_type='STOCK', exchange='SAO',
                              currency='BRL', provider_symbol='PETR4.SA', quote_currency='BRL')
    attached = create_instrument(session, instrument_id=stock.id, symbol='PETR4', asset_type='STOCK',
                                 provider_symbol='PETR4F.SA', quote_currency='BRL')
    assert attached.id == stock.id
    assert resolve_instrument(session, 'PETR4F.SA').instrument.id == stock.id
    with pytest.raises(ValueError, match='ambiguous'):
        provider_mapping(session, stock, currency='BRL')


def test_domain_rejects_mixed_currency_across_brokers_for_one_instrument():
    from types import SimpleNamespace
    from src.domain import overview
    transactions = [SimpleNamespace(id=i, instrument_id=1, asset='BTC', broker=str(i), allocation_class='Crypto',
        asset_currency=currency, type='Buy', quantity=Decimal('1'), price=Decimal('10'),
        trade_date=date(2024, 1, 2), date_time=datetime(2024, 1, 2)) for i, currency in enumerate(['BRL', 'USD'])]
    with pytest.raises(ValueError, match='Mixed transaction currencies'):
        overview(transactions, [])


def test_database_rejects_duplicate_crypto_identity(session):
    from sqlalchemy.exc import IntegrityError
    create_instrument(session, symbol='BTC', asset_type='CRYPTO')
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(Instrument(symbol='BTC', asset_type='CRYPTO'))
            session.flush()


def test_ambiguous_same_currency_cached_quotes_do_not_choose_a_mapping(session):
    from src.market_prices import history_for_domain
    instrument = create_instrument(session, symbol='PETR4', asset_type='STOCK', currency='BRL',
                                   provider_symbol='PETR4.SA', quote_currency='BRL')
    create_instrument(session, instrument_id=instrument.id, symbol='PETR4', asset_type='STOCK',
                      provider_symbol='PETR4F.SA', quote_currency='BRL')
    portfolio = Portfolio(name='Ambiguous quotes')
    session.add(portfolio)
    session.flush()
    asset = ensure_asset(session, portfolio.id, instrument)
    now = datetime.now(timezone.utc)
    for index, mapping in enumerate(session.scalars(select(ProviderInstrument))):
        session.add(LatestMarketQuote(provider_instrument_id=mapping.id, price=10 + index, currency='BRL',
                                      source='yfinance', retrieved_at=now, reference_date=date.today()))
        session.add(MarketPrice(provider_instrument_id=mapping.id, price=10 + index, currency='BRL',
                                source='yfinance', retrieved_at=now, reference_at=now))
    session.flush()
    assert history_for_domain(session, asset) == []
    assert not get_latest(session, asset, lambda *a: pytest.fail('Ambiguous mapping fetched')).available
    save_user_price(session, asset, date.today(), 42, 'BRL')
    assert get_latest(session, asset, lambda *a: pytest.fail('Ambiguous mapping fetched')).price.close == 42
