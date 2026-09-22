from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from src.instruments import add_alias, create_instrument, provider_mapping, resolve_instrument
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
    mapping.is_primary = False
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
    old.is_primary = False
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


def test_transaction_currency_is_independent_from_native_and_quote_currency(session):
    from src.services import require_instrument
    instrument = create_instrument(
        session, symbol='AAPL', currency='USD', asset_type='STOCK',
        provider_symbol='AAPL', quote_currency='USD',
    )
    assert require_instrument(session, 'AAPL', 'BRL', instrument.id) is instrument


def test_legacy_resolution_preserves_transaction_currency_independently(session):
    from src.import_legacy import _legacy_instrument
    instrument = create_instrument(session, symbol='AAPL', currency='USD', asset_type='STOCK')
    assert _legacy_instrument(session, 'AAPL', 'BRL') is instrument


def test_search_finds_catalog_aliases_and_names_with_spaces(session):
    from src.instruments import search_instruments
    instrument = create_instrument(session, symbol='BTC', currency='BRL',
                                   name='Bitcoin Digital Asset', aliases=['BTCBRL'], origin='CATALOG')
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


def test_provider_discovery_filters_unsupported_options_and_futures(monkeypatch):
    from io import StringIO
    from src.api import market_data
    monkeypatch.setattr(market_data, 'urlopen', lambda *a, **k: StringIO(
        '{"quotes": ['
        '{"symbol": "AAPL", "quoteType": "EQUITY", "currency": "USD"},'
        '{"symbol": "AAPL260101C00100000", "quoteType": "OPTION", "currency": "USD"},'
        '{"symbol": "ES=F", "quoteType": "FUTURE", "currency": "USD"}'
        ']}'
    ))
    assert [item['provider_symbol'] for item in market_data.search_instruments('AAPL')] == ['AAPL']


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


def test_custom_manual_instrument_preserves_its_entered_default_currency(session):
    instrument = create_instrument(
        session, symbol='PRIVATE-USD', name='Private company', currency='USD',
        asset_type='OTHER', origin='CUSTOM',
    )
    assert instrument.currency == 'USD'
    assert instrument.provider_mappings == []


def test_mapping_selection_uses_primary_not_transaction_currency(session):
    from src.instruments import provider_mapping
    instrument = create_instrument(session, quote_currency='USD', symbol='BTC', asset_type='CRYPTO', currency='USD', provider_symbol='BTC-USD')
    create_instrument(session, quote_currency='EUR', symbol='BTC', asset_type='CRYPTO', currency='EUR', provider_symbol='BTC-EUR')
    assert provider_mapping(session, instrument).provider_symbol == 'BTC-USD'
    with pytest.raises(ValueError, match='must not use transaction currency'):
        provider_mapping(session, instrument, currency='EUR')


def test_provider_currency_cannot_be_unknown(session):
    with pytest.raises(ValueError, match='currency'):
        create_instrument(session, quote_currency=None, symbol='GTLSX', asset_type='STOCK', currency=None, provider_symbol='GTLSX')


def test_catalog_search_filters_supported_types_without_provider_discovery(session):
    from src.instruments import search_instruments
    instrument = create_instrument(session, quote_currency='USD', symbol='BTC', name='Bitcoin', asset_type='CRYPTO', currency='USD', provider_symbol='BTC-USD', origin='CATALOG')
    create_instrument(session, symbol='GBTC', name='Bitcoin Trust', asset_type='ETF', currency='USD', origin='CUSTOM')
    results = search_instruments(session, 'Bitcoin')
    assert len(results) == 1
    assert results[0]['instrument_id'] == instrument.id
    assert len(search_instruments(session, 'Bitcoin', category='CRYPTO')) == 1


def test_normal_catalog_search_never_creates_provider_mappings(session):
    from src.instruments import search_instruments
    btc = create_instrument(session, symbol='BTC', name='Bitcoin', asset_type='CRYPTO',
                            provider_symbol='BTC-USD', quote_currency='USD', origin='CATALOG')
    assert search_instruments(session, 'BTC-EUR') == []
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


def test_explicit_petr4_market_variant_keeps_primary_deterministic(session):
    from src.instruments import provider_mapping
    stock = create_instrument(session, symbol='PETR4', asset_type='STOCK', exchange='SAO',
                              currency='BRL', provider_symbol='PETR4.SA', quote_currency='BRL')
    attached = create_instrument(session, instrument_id=stock.id, symbol='PETR4', asset_type='STOCK',
                                 provider_symbol='PETR4F.SA', quote_currency='BRL')
    assert attached.id == stock.id
    assert resolve_instrument(session, 'PETR4F.SA').instrument.id == stock.id
    assert provider_mapping(session, stock).provider_symbol == 'PETR4.SA'


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


def test_database_rejects_two_primary_mappings_for_provider(session):
    from sqlalchemy.exc import IntegrityError
    instrument = create_instrument(
        session, symbol='BTC', asset_type='CRYPTO', provider_symbol='BTC-USD',
        quote_currency='USD',
    )
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(ProviderInstrument(
                instrument_id=instrument.id, provider='yfinance',
                provider_symbol='BTC-EUR', quote_currency='EUR', active=True,
                is_primary=True,
            ))
            session.flush()


def test_primary_mapping_prevents_cached_quote_ambiguity(session):
    from src.market_prices import history_for_domain
    instrument = create_instrument(session, symbol='PETR4', asset_type='STOCK', currency='BRL',
                                   provider_symbol='PETR4.SA', quote_currency='BRL')
    create_instrument(session, instrument_id=instrument.id, symbol='PETR4', asset_type='STOCK',
                      provider_symbol='PETR4F.SA', quote_currency='BRL')
    portfolio = Portfolio(name='Ambiguous quotes')
    session.add(portfolio)
    session.flush()
    asset = ensure_asset(session, portfolio.id, instrument)
    now = datetime(2024, 1, 8, 12, tzinfo=timezone.utc)
    for index, mapping in enumerate(session.scalars(select(ProviderInstrument))):
        session.add(LatestMarketQuote(provider_instrument_id=mapping.id, price=10 + index, currency='BRL',
                                      source='yfinance', retrieved_at=now, reference_date=now.date()))
        session.add(MarketPrice(provider_instrument_id=mapping.id, price=10 + index, currency='BRL',
                                source='yfinance', retrieved_at=now, reference_at=now))
    session.flush()
    assert [row.close for row in history_for_domain(session, asset)] == [10]
    assert get_latest(session, asset, lambda *a: pytest.fail('Fresh primary cache fetched'), now).available
    save_user_price(session, asset, now.date(), 42, 'BRL')
    assert get_latest(session, asset, lambda *a: pytest.fail('Ambiguous mapping fetched'), now).price.close == 42


def test_catalog_seed_is_idempotent_and_loads_aliases_and_mappings(session):
    from src.instrument_catalog import seed_catalog
    first = seed_catalog(session)
    second = seed_catalog(session)
    assert first == second == {'instruments': 4, 'mappings': 6}
    assert session.scalar(select(func.count()).select_from(Instrument)) == 4
    assert session.scalar(select(func.count()).select_from(ProviderInstrument)) == 6
    assert resolve_instrument(session, 'PETR4.SA').instrument.symbol == 'PETR4'
    assert resolve_instrument(session, 'BTCBRL').instrument.symbol == 'BTC'
    btc = session.scalar(select(Instrument).where(Instrument.symbol == 'BTC'))
    assert btc.origin == 'CATALOG'
    assert provider_mapping(session, btc).provider_symbol == 'BTC-USD'


def test_catalog_replacement_retires_mapping_without_hiding_its_history(session, monkeypatch):
    from dataclasses import replace
    from src import instrument_catalog
    instrument_catalog.seed_catalog(session)
    instrument = resolve_instrument(session, 'AAPL').instrument
    old = provider_mapping(session, instrument)
    portfolio = Portfolio(name='Catalog replacement')
    session.add(portfolio)
    session.flush()
    asset = ensure_asset(session, portfolio.id, instrument)
    now = datetime(2024, 1, 2, tzinfo=timezone.utc)
    session.add(MarketPrice(provider_instrument_id=old.id, reference_at=now,
                            price=100, currency='USD', source='yfinance', retrieved_at=now))
    rows = [replace(row, provider_symbol='AAPL.NEW') if row.symbol == 'AAPL' else row
            for row in instrument_catalog.read_catalog()]
    monkeypatch.setattr(instrument_catalog, 'read_catalog', lambda path: rows)
    instrument_catalog.seed_catalog(session)
    assert not old.active
    assert provider_mapping(session, instrument).provider_symbol == 'AAPL.NEW'
    assert [row.close for row in get_stored_history(session, asset)] == [100]


def test_catalog_repairs_malformed_migrated_arkx_in_place(session):
    from src.instrument_catalog import seed_catalog
    legacy = Instrument(symbol='ARKX', name='', asset_type='OTHER', origin='MIGRATED')
    session.add(legacy)
    session.flush()
    guessed = ProviderInstrument(
        instrument_id=legacy.id, provider='yfinance', provider_symbol='ARKX',
        quote_currency='USD', active=False, is_primary=False,
    )
    session.add(guessed)
    session.flush()

    seed_catalog(session)

    arkx = resolve_instrument(session, 'ARKX').instrument
    assert arkx.id == legacy.id
    assert (arkx.name, arkx.asset_type, arkx.exchange, arkx.origin) == (
        'ARK Space & Defense Innovation ETF', 'ETF', 'CBOE', 'CATALOG',
    )
    assert provider_mapping(session, arkx).id == guessed.id


def test_catalog_fails_when_provider_symbol_has_another_owner(session):
    from src.instrument_catalog import seed_catalog
    hijacker = create_instrument(
        session, symbol='NOT-ARKX', asset_type='OTHER', provider_symbol='ARKX',
        quote_currency='USD', origin='CUSTOM',
    )
    with pytest.raises(ValueError, match='already belongs'):
        seed_catalog(session)
    assert hijacker.origin == 'CUSTOM'
    session.commit()
    assert session.scalar(select(func.count()).select_from(Instrument)) == 1
    assert session.scalar(select(func.count()).select_from(InstrumentAlias)) == 1


def test_catalog_rejects_provider_symbol_owned_in_different_currency(session):
    from src.instrument_catalog import seed_catalog
    create_instrument(session, symbol='WRONG', provider_symbol='ARKX', quote_currency='BRL')
    with pytest.raises(ValueError, match='already belongs'):
        seed_catalog(session)


def test_catalog_does_not_relabel_known_migrated_listing(session):
    from src.instrument_catalog import seed_catalog
    legacy = create_instrument(session, symbol='AAPL', asset_type='STOCK',
                               exchange='OTHER-EXCHANGE', currency='EUR', origin='MIGRATED')
    with pytest.raises(ValueError, match='Conflicting migrated'):
        seed_catalog(session)
    assert legacy.currency == 'EUR'
    assert legacy.exchange == 'OTHER-EXCHANGE'


def test_catalog_repairs_migration_placeholder_currency_without_changing_transactions(session):
    from src.instrument_catalog import seed_catalog
    legacy = Instrument(symbol='AAPL', name='', asset_type='OTHER', currency='BRL', origin='MIGRATED')
    session.add(legacy)
    session.flush()
    add_alias(session, legacy, 'AAPL', 'migration')
    session.execute(text("INSERT INTO transactions VALUES (1, :iid, 'BRL', 1)"), {'iid': legacy.id})
    original_id = legacy.id
    seed_catalog(session)
    seed_catalog(session)
    assert (legacy.id, legacy.currency, legacy.exchange, legacy.origin) == (original_id, 'USD', 'NASDAQ', 'CATALOG')
    assert provider_mapping(session, legacy).quote_currency == 'USD'
    assert session.execute(text('SELECT instrument_id, asset_currency FROM transactions')).one() == (original_id, 'BRL')


def test_catalog_reuses_migrated_crypto_with_provider_market_label(session):
    from src.instrument_catalog import seed_catalog
    btc = create_instrument(session, symbol='BTC', name='Bitcoin', asset_type='CRYPTO',
                            exchange='CCC', provider_exchange='CCC', provider_symbol='BTC-USD',
                            quote_currency='USD', origin='MIGRATED', alias_source='selection')
    mapping = provider_mapping(session, btc)
    mapping.is_primary = False
    mapping.active = False
    seed_catalog(session)
    assert btc.exchange is None
    assert btc.currency is None
    assert provider_mapping(session, btc).id == mapping.id
    assert mapping.provider_exchange == 'CCC'


def test_catalog_still_rejects_currency_conflict_on_selected_metadata(session):
    from src.instrument_catalog import seed_catalog
    create_instrument(session, symbol='AAPL', currency='BRL', asset_type='OTHER',
                      origin='MIGRATED', alias_source='selection')
    with pytest.raises(ValueError, match='Conflicting migrated'):
        seed_catalog(session)


@pytest.mark.parametrize('source', ['manual-entry', 'import'])
def test_transaction_alias_does_not_poison_another_identity(session, source):
    first = create_instrument(session, symbol='FIRST')
    second = create_instrument(session, symbol='SECOND')
    add_alias(session, second, 'FIRST', source)
    assert resolve_instrument(session, 'FIRST').instrument.id == first.id


def test_cached_accounting_quote_survives_primary_currency_change(session):
    from src.instrument_catalog import seed_catalog
    from src.market_prices import history_for_domain
    seed_catalog(session)
    btc = resolve_instrument(session, 'BTC').instrument
    portfolio = Portfolio(name='Retained cache')
    session.add(portfolio)
    session.flush()
    asset = ensure_asset(session, portfolio.id, btc)
    session.execute(text("INSERT INTO transactions VALUES (1, :iid, 'BRL', :pid)"),
                    {'iid': btc.id, 'pid': portfolio.id})
    old = session.scalar(select(ProviderInstrument).where(ProviderInstrument.provider_symbol == 'BTC-BRL'))
    old.active = False
    session.add(LatestMarketQuote(provider_instrument_id=old.id, currency='BRL',
                                 price=42, source='yfinance', reference_date=date(2024, 1, 2),
                                 retrieved_at=datetime(2024, 1, 2, tzinfo=timezone.utc)))
    session.flush()
    prices = history_for_domain(session, asset)
    assert [(p.close, p.currency) for p in prices] == [(Decimal('42'), 'BRL')]


def test_history_survives_when_all_mapping_candidates_are_retired(session):
    instrument = create_instrument(session, symbol='OLD', currency='USD', asset_type='STOCK',
                                   provider_symbol='OLD.A', quote_currency='USD')
    create_instrument(session, instrument_id=instrument.id, symbol='OLD', asset_type='STOCK',
                      provider_symbol='OLD.B', quote_currency='USD')
    portfolio = Portfolio(name='Retired mappings')
    session.add(portfolio)
    session.flush()
    asset = ensure_asset(session, portfolio.id, instrument)
    for index, mapping in enumerate(session.scalars(select(ProviderInstrument)), 1):
        mapping.is_primary = False
        mapping.active = False
        now = datetime(2024, 1, index, tzinfo=timezone.utc)
        session.add(MarketPrice(provider_instrument_id=mapping.id, reference_at=now,
                                price=index, currency='USD', source='yfinance', retrieved_at=now))
    session.flush()
    assert [row.close for row in get_stored_history(session, asset)] == [1, 2]
    result = get_latest(session, asset, lambda *args: pytest.fail('Retired mapping fetched'))
    assert result.stale and result.price.close == 2


def test_catalog_validation_rejects_duplicate_primary_mappings(tmp_path):
    from src.instrument_catalog import read_catalog
    catalog = tmp_path / 'invalid.csv'
    catalog.write_text(
        'canonical_symbol,name,asset_type,exchange,native_currency,status,provider,provider_symbol,quote_currency,is_primary,aliases\n'
        'BTC,Bitcoin,CRYPTO,,,ACTIVE,yfinance,BTC-USD,USD,true,\n'
        'BTC,Bitcoin,CRYPTO,,,ACTIVE,yfinance,BTC-BRL,BRL,true,\n',
        encoding='utf-8',
    )
    with pytest.raises(ValueError, match='exactly one primary'):
        read_catalog(catalog)


def test_btc_brl_transaction_fetches_primary_usd_mapping_and_stores_usd(session):
    from src.instrument_catalog import seed_catalog
    seed_catalog(session)
    btc = session.scalar(select(Instrument).where(Instrument.symbol == 'BTC'))
    portfolio = Portfolio(name='BTC in BRL')
    session.add(portfolio)
    session.flush()
    asset = ensure_asset(session, portfolio.id, btc)
    session.execute(text(
        "INSERT INTO transactions (id, instrument_id, asset_currency, portfolio_id) "
        "VALUES (1, :instrument_id, 'BRL', :portfolio_id)"
    ), {'instrument_id': btc.id, 'portfolio_id': portfolio.id})
    calls = []
    result = get_latest(session, asset, lambda symbol, currency: calls.append((symbol, currency)) or {
        'price': Decimal('86000'), 'currency': 'USD',
        'market_at': datetime(2024, 1, 8, 18, tzinfo=timezone.utc),
        'retrieved_at': datetime(2024, 1, 8, 19, tzinfo=timezone.utc),
    }, datetime(2024, 1, 8, 19, tzinfo=timezone.utc))
    assert calls == [('BTC-USD', 'USD')]
    assert result.price.currency == 'USD'
    stored = session.scalar(select(LatestMarketQuote).where(
        LatestMarketQuote.provider_instrument_id == provider_mapping(session, btc).id,
    ))
    assert stored.currency == 'USD'
    from src.market_prices import get_history, history_for_domain
    day = date(2024, 1, 8)
    history = get_history(session, asset, day, day, lambda *args: [{
        'date': day, 'close': Decimal('86000'), 'currency': 'USD',
    }])
    assert [(p.close, p.currency) for p in history.prices] == [(Decimal('86000'), 'USD')]
    assert history_for_domain(session, asset) == []
    save_user_price(session, asset, day, Decimal('430000'), 'BRL')
    history = get_history(session, asset, day, day, lambda *args: pytest.fail('Covered history fetched'))
    assert [(p.close, p.currency) for p in history.prices] == [(Decimal('430000'), 'BRL')]
