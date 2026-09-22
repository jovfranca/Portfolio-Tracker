"""Integration tests use an outer PostgreSQL transaction, rolled back after each test."""
from datetime import datetime, timezone
from decimal import Decimal
import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from src.main import app
from src.config import ROOT
from src.database import engine, get_session
from src.models import Transaction
from src.import_legacy import import_transactions

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.getenv('RUN_DB_TESTS') != '1', reason='Set RUN_DB_TESTS=1 with PostgreSQL migrated.')]


@pytest.fixture
def client():
    with engine.connect() as connection:
        outer = connection.begin()
        def override():
            with Session(connection, join_transaction_mode='create_savepoint', expire_on_commit=False) as session:
                yield session
        app.dependency_overrides[get_session] = override
        try:
            with TestClient(app) as c:
                yield c, connection
        finally:
            app.dependency_overrides.clear()
            outer.rollback()


def test_health_rejects_outdated_provider_schema(client):
    from sqlalchemy import text
    c, connection = client
    connection.execute(text('ALTER TABLE provider_instruments RENAME COLUMN quote_currency TO currency'))
    assert c.get('/api/health').status_code == 503


def register_instrument(client, symbol, currency, **extra):
    from src.instruments import create_instrument
    sessions = app.dependency_overrides[get_session]()
    try:
        session = next(sessions)
        instrument = create_instrument(
            session, symbol=symbol, currency=currency, quote_currency=currency,
            asset_type=extra.pop('asset_type', 'STOCK'),
            provider_symbol=extra.pop('provider_symbol', symbol), **extra,
        )
        session.commit()
        return instrument.id
    finally:
        sessions.close()


def test_public_api_cannot_write_provider_catalog(client):
    c, _ = client
    response = c.post('/api/instruments', json={
        'symbol': 'BYPASS', 'provider_symbol': 'BYPASS',
        'quote_currency': 'USD', 'provider_currency_confirmed': True,
    })
    assert response.status_code == 410


def test_crud_prices_isolation_and_rollback(client, monkeypatch):
    c, _ = client
    assert c.get('/api/health').status_code == 200
    pid = c.post('/api/portfolios', json={'name': 'Integration test'}).json()['id']
    other = c.post('/api/portfolios', json={'name': 'Other'}).json()['id']
    instrument_id = register_instrument(c, 'TEST', 'BRL')
    base = f'/api/portfolios/{pid}'
    payload = dict(trade_date='2024-01-02', settlement_date='2024-01-03', type='Buy',
                   asset='test', instrument_id=instrument_id, broker='Broker', allocation_class='Stocks', quantity=10,
                   price=20, asset_currency='BRL', brokerage_fee=1, other_fees=2, notes='')
    response = c.post(base + '/transactions', json=payload)
    assert response.status_code == 201, response.text
    assert response.json()['instrument_id'] == instrument_id
    tid = response.json()['id']
    result = c.get(base + '/overview').json()
    assert result['positions'][0]['average_cost'] == 20
    aid = result['assets'][0]['id']
    assert c.put(base + f'/assets/{aid}/quote', json={'date': '2024-01-03', 'close': 30}).status_code == 200
    result = c.get(base + '/overview').json()
    assert result['summary']['total_value'] == 300
    assert result['positions'][0]['current_total_gain'] == 100
    assert c.get(f'/api/portfolios/{other}/assets/{aid}/history').status_code == 404
    assert c.delete(f'/api/portfolios/{other}/transactions/{tid}').status_code == 404
    assert c.put(base + f'/transactions/{tid}', json=payload | {'quantity': 5}).status_code == 200
    assert c.get(base + '/overview').json()['summary']['total_value'] == 150
    assert c.post(base + '/transactions', json=payload | {'quantity': -1}).status_code == 422
    assert len(c.get(base + '/transactions').json()) == 1
    monkeypatch.setattr('src.market_prices.market_data.fetch_history', lambda *args: (_ for _ in ()).throw(RuntimeError('offline')))
    monkeypatch.setattr('src.market_prices.market_data.fetch_latest', lambda *args: (_ for _ in ()).throw(RuntimeError('offline')))
    assert c.post(base + f'/assets/{aid}/refresh').status_code == 502
    assert c.get(base + f'/assets/{aid}/history').json()[0]['close'] == 30
    assert c.post('/api/portfolios', json={'name':'forbidden'}, headers={'Origin':'https://example.com'}).status_code == 403
    assert c.delete(base + f'/transactions/{tid}').status_code == 204
    assert c.get(base + '/overview').json()['positions'] == []


def test_quote_endpoint_keeps_manual_prices_private_and_checks_currency(client, monkeypatch):
    from datetime import date
    c, _ = client
    first = c.post('/api/portfolios', json={'name': 'Manual price owner'}).json()['id']
    second = c.post('/api/portfolios', json={'name': 'Other price owner'}).json()['id']
    instrument_id = register_instrument(c, 'QUOTE-TEST', 'USD')
    payload = dict(trade_date='2024-01-02', settlement_date='2024-01-02', type='Buy',
                   asset='QUOTE-TEST', instrument_id=instrument_id, broker='Example', quantity='1', price='10',
                   asset_currency='USD', fx_rate='5')
    asset_ids = []
    for pid in (first, second):
        assert c.post(f'/api/portfolios/{pid}/transactions', json=payload).status_code == 201
        asset_ids.append(c.get(f'/api/portfolios/{pid}/overview').json()['assets'][0]['id'])
    path = f'/api/portfolios/{first}/assets/{asset_ids[0]}/quote'
    quote = {'date': date.today().isoformat(), 'close': '12', 'currency': 'USD'}
    assert c.put(path, json=quote | {'currency': 'BRL'}).status_code == 422
    assert c.put(path, json=quote).status_code == 200
    calls = []

    def offline(*args):
        calls.append(args)
        raise OSError('offline')

    monkeypatch.setattr('src.market_prices.market_data.fetch_latest', offline)
    response = c.get(path)
    assert response.status_code == 200
    assert response.json()['origin'] == 'user-defined'
    assert not response.json()['stale']
    assert calls == []
    assert c.get(f'/api/portfolios/{second}/assets/{asset_ids[0]}/quote').status_code == 404
    assert c.get(f'/api/portfolios/{second}/assets/{asset_ids[1]}/quote').status_code == 404
    assert len(calls) == 1


def test_legacy_import_is_atomic_and_repeatable(client):
    c, connection = client
    pid = c.post('/api/portfolios', json={'name': 'Import test'}).json()['id']
    with Session(connection, join_transaction_mode='create_savepoint') as session:
        first = import_transactions(session, ROOT / 'src/db/transactions.pkl', pid, ROOT / 'src/db/assets.pkl')
        session.commit()
        second = import_transactions(session, ROOT / 'src/db/transactions.pkl', pid)
        assert first['imported'] == 10
        assert second['already_imported']
        assert session.scalar(select(func.count()).select_from(Transaction).where(Transaction.portfolio_id == pid)) == 10
        session.commit()
    assert len(c.get(f'/api/portfolios/{pid}/overview').json()['assets']) == 2


def test_legacy_import_preserves_price_provenance(client, monkeypatch):
    from datetime import date
    from types import SimpleNamespace
    from src.models import Asset, UserDefinedPrice
    from src.schemas import QuoteInput
    c, connection = client
    pid = c.post('/api/portfolios', json={'name': 'Synthetic legacy import'}).json()['id']
    monkeypatch.setattr('src.import_legacy.read_transactions', lambda path: ('a' * 64, []))
    monkeypatch.setattr('src.import_legacy.read_assets', lambda path: [
        (SimpleNamespace(ticker='SYNTHETIC'), [QuoteInput(date=date(2024, 1, 2), close='12')]),
    ])
    with Session(connection, join_transaction_mode='create_savepoint') as session:
        import_transactions(session, 'synthetic', pid, 'synthetic')
        price = session.scalar(select(UserDefinedPrice).join(UserDefinedPrice.asset).where(
            Asset.portfolio_id == pid,
        ))
        assert price.source == 'legacy'
        assert price.retrieved_at is None


@pytest.mark.parametrize('trade_today', [False, True])
def test_refresh_reports_unavailable_latest_and_still_attempts_it(client, monkeypatch, trade_today):
    from datetime import date
    c, _ = client
    pid = c.post('/api/portfolios', json={'name': 'Refresh failure'}).json()['id']
    instrument_id = register_instrument(c, 'REFRESH-FAIL', 'BRL')
    day = date.today().isoformat() if trade_today else '2024-01-02'
    base = f'/api/portfolios/{pid}'
    response = c.post(base + '/transactions', json=dict(
        trade_date=day, settlement_date=day, type='Buy', asset='REFRESH-FAIL', instrument_id=instrument_id,
        broker='Synthetic', quantity='1', price='10', asset_currency='BRL',
    ))
    assert response.status_code == 201
    aid = c.get(base + '/overview').json()['assets'][0]['id']
    calls = []

    def offline(*args):
        calls.append(args)
        raise OSError('offline')

    monkeypatch.setattr('src.market_prices.market_data.fetch_history', offline)
    monkeypatch.setattr('src.market_prices.market_data.fetch_latest', offline)
    assert c.post(base + f'/assets/{aid}/refresh').status_code == 502
    assert any(len(args) == 2 for args in calls)


def test_latest_quote_keeps_exchange_date_after_postgres_reload(client):
    from datetime import date, timedelta
    from sqlalchemy import text
    from src.market_prices import get_latest
    from src.instruments import create_instrument
    from src.services import ensure_asset
    c, connection = client
    pid = c.post('/api/portfolios', json={'name': 'Quote timezone'}).json()['id']
    now = datetime(2024, 1, 9, 1, tzinfo=timezone.utc)
    with Session(connection, join_transaction_mode='create_savepoint') as session:
        session.execute(text("SET LOCAL TIME ZONE 'UTC'"))
        instrument = create_instrument(session, quote_currency='USD', symbol='TIMEZONE-TEST', currency='USD', asset_type='STOCK', provider='yfinance',
            provider_symbol='TIMEZONE-TEST',
        )
        asset = ensure_asset(session, pid, instrument)
        get_latest(session, asset, lambda *args: {
            'price': Decimal('20'), 'currency': 'USD', 'retrieved_at': now,
            'market_at': datetime(2024, 1, 8, 19, tzinfo=timezone(timedelta(hours=-5))),
        }, now)
        session.flush()
        session.expire_all()
        result = get_latest(session, asset, lambda *args: pytest.fail('fresh cache fetched'), now)
        assert result.price.date == date(2024, 1, 8)


def test_historical_rate_lookup_cache_and_backfill(client, monkeypatch):
    c, _ = client
    calls = []

    def fetch(currency, rate_type, start, end):
        calls.append((currency, rate_type, start, end))
        sides = ['BUY', 'SELL'] if rate_type == 'PTAX' else ['MARKET']
        return [
            {
                'currency': currency,
                'rate_type': rate_type,
                'rate_side': side,
                'reference_date': end,
                'rate': Decimal('5.123456789012'),
                'source': 'integration-provider',
                'retrieved_at': datetime(2024, 1, 1, tzinfo=timezone.utc),
            }
            for side in sides
        ]

    monkeypatch.setattr('src.api.market_data.fetch_rates', fetch)
    first = c.get('/api/rates/FX/ZZZ/2024-01-08')
    assert first.status_code == 200, first.text
    assert first.json()['rates'][0]['rate'] == '5.123456789012'
    assert first.json()['rates'][0]['side'] == 'MARKET'
    assert not first.json()['fallback_used']

    monkeypatch.setattr(
        'src.api.market_data.fetch_rates',
        lambda *args: pytest.fail('cached rate queried the provider'),
    )
    second = c.get('/api/rates/FX/ZZZ/2024-01-08')
    assert second.status_code == 200
    assert len(calls) == 1

    monkeypatch.setattr('src.api.market_data.fetch_rates', fetch)
    backfill = c.post('/api/rates/backfill', json={
        'currencies': ['YYY'],
        'rate_types': ['FX', 'PTAX'],
        'start_date': '2024-01-08',
        'end_date': '2024-01-09',
    })
    assert backfill.status_code == 200, backfill.text
    assert backfill.json() == {'inserted': 3, 'series': 2}


def test_transaction_import_preview_fx_and_duplicate_protection(client, monkeypatch):
    c, _ = client
    pid = c.post('/api/portfolios', json={'name': 'CSV import'}).json()['id']
    register_instrument(c, 'AAPL', 'USD')

    def fetch(currency, rate_type, start, end):
        return [{
            'currency': currency, 'rate_type': rate_type, 'rate_side': 'MARKET',
            'reference_date': end, 'rate': Decimal('5.25'), 'source': 'test',
            'retrieved_at': datetime(2024, 1, 1, tzinfo=timezone.utc),
        }]

    monkeypatch.setattr('src.api.market_data.fetch_rates', fetch)
    csv = (
        'ticker,broker,type,trade_date,settlement_date,quantity,unit_price,asset_currency,fx_rate\n'
        'AAPL,Example,Buy,2024-01-02,2024-01-03,2.5,100.01,USD,\n'
    ).encode()
    base = f'/api/portfolios/{pid}/transactions'
    preview = c.post(base + '/import-preview?filename=records.csv', content=csv)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body['valid'] and not body['already_imported']
    assert Decimal(body['rows'][0]['data']['fx_rate']) == Decimal('5.25')

    confirm = c.post(base + '/import', json={
        'digest': body['digest'], 'filename': body['filename'],
        'rows': [body['rows'][0]['data']],
    })
    assert confirm.status_code == 201, confirm.text
    saved = c.get(base).json()[0]
    assert saved['asset'] == 'AAPL'
    assert saved['instrument_id'] == register_instrument(c, 'AAPL', 'USD')
    assert saved['settlement_date'] == '2024-01-03'
    assert saved['fx_rate'] == '5.250000000000'
    duplicate = c.post(base + '/import', json={
        'digest': body['digest'], 'filename': body['filename'],
        'rows': [body['rows'][0]['data']],
    })
    assert duplicate.status_code == 409
    assert len(c.get(base).json()) == 1


def test_import_conflicts_preview_and_atomic_rollback(client):
    c, _ = client
    pid = c.post('/api/portfolios', json={'name': 'Atomic import'}).json()['id']
    test_instrument_id = register_instrument(c, 'TEST', 'BRL')
    new_instrument_id = register_instrument(c, 'NEW', 'BRL')
    base = f'/api/portfolios/{pid}/transactions'
    row = dict(trade_date='2024-01-02', settlement_date='2024-01-03', type='Buy',
               asset='TEST', instrument_id=test_instrument_id, broker='Example', quantity='1', price='10', asset_currency='BRL')
    assert c.post(base, json=row).status_code == 201
    csv = ('ticker,broker,type,trade_date,settlement_date,quantity,unit_price,asset_currency,fx_rate\n'
           'TEST,Example,Buy,2024-01-02,2024-01-03,1,10,USD,5\n')
    preview = c.post(base + '/import-preview?filename=conflict.csv', content=csv).json()
    assert not preview['valid']
    assert preview['rows'][0]['errors'][0]['field'] == 'asset_currency'
    result = c.post(base + '/import', json={
        'digest': 'a' * 64, 'filename': 'conflict.csv',
        'rows': [row | {'asset': 'NEW', 'instrument_id': new_instrument_id}, row | {'asset_currency': 'USD', 'fx_rate': '5'}],
    })
    assert result.status_code == 422
    assert len(c.get(base).json()) == 1
    assert len(c.get(f'/api/portfolios/{pid}/overview').json()['assets']) == 1


def test_manual_fx_precision_and_edit_preserve_history(client, monkeypatch):
    from datetime import date
    c, connection = client
    pid = c.post('/api/portfolios', json={'name': 'Frozen history'}).json()['id']
    instrument_id = register_instrument(c, 'USDTEST', 'USD')
    base = f'/api/portfolios/{pid}/transactions'
    calls = []
    def rates(session, currency, rate_type, day):
        from types import SimpleNamespace
        calls.append(day)
        return [SimpleNamespace(rate_side='MARKET', rate=Decimal('5.123456789012'))]
    monkeypatch.setattr('src.services.get_rates', rates)
    payload = dict(trade_date='2024-01-02', settlement_date='2024-01-04', type='Buy',
                   asset='USDTEST', instrument_id=instrument_id, broker='Example', quantity='12345.123456789012',
                   price='10.000000000001', asset_currency='USD')
    response = c.post(base, json=payload)
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved['quantity'] == payload['quantity']
    assert saved['price'] == payload['price']
    assert calls == [date(2024, 1, 4)]
    timestamp = datetime(2024, 1, 2, 15, 30)
    connection.execute(Transaction.__table__.update().where(Transaction.id == saved['id']).values(date_time=timestamp))
    edit = {key: value for key, value in saved.items() if key not in {'id', 'portfolio_id'}}
    edit['notes'] = 'Edited note'
    response = c.put(base + '/' + str(saved['id']), json=edit)
    assert response.status_code == 200, response.text
    assert calls == [date(2024, 1, 4)]
    assert response.json()['fx_rate'] == '5.123456789012'
    assert connection.scalar(select(Transaction.date_time).where(Transaction.id == saved['id'])) == timestamp


def test_import_explicit_resolution_and_alias_reuse(client):
    c, _ = client
    pid = c.post('/api/portfolios', json={'name': 'Resolution'}).json()['id']
    base = f'/api/portfolios/{pid}/transactions'
    raw_identifier = 'UNRESOLVED-IMPORT-ALIAS'
    csv = ('ticker,broker,type,trade_date,settlement_date,quantity,unit_price,asset_currency\n'
           f'{raw_identifier},Example,Buy,2024-01-02,2024-01-03,1,10,BRL\n')
    preview = c.post(base + '/import-preview?filename=crypto.csv', content=csv).json()
    assert not preview['valid']
    row = preview['rows'][0]['data']
    assert c.post(base + '/import', json={
        'digest': preview['digest'], 'filename': preview['filename'], 'rows': [row],
    }).status_code == 422
    instrument_id = register_instrument(c, 'CUSTOM-IMPORT-ASSET', 'BRL')
    resolved = c.post(base + '/import-resolve', json=row | {'instrument_id': instrument_id})
    assert resolved.status_code == 200, resolved.text
    assert c.get(base).json() == []
    assert c.post(base + '/import', json={
        'digest': preview['digest'], 'filename': preview['filename'], 'rows': [resolved.json()],
    }).status_code == 201
    again = c.post(base + '/import-preview?filename=crypto.csv', content=csv).json()
    assert again['rows'][0]['instrument_resolution'] == 'resolved'
    assert again['rows'][0]['data']['instrument_id'] == instrument_id
    assert c.post(base, json=row | {'asset': raw_identifier}).status_code == 201
    overview = c.get(f'/api/portfolios/{pid}/overview').json()
    assert len(overview['assets']) == 1
    assert overview['positions'][0]['quantity'] == 2


@pytest.mark.parametrize('asset_type', ['STOCK', 'ETF'])
def test_transaction_currency_may_differ_from_native_currency(client, asset_type):
    c, _ = client
    pid = c.post('/api/portfolios', json={'name': 'Currency safety'}).json()['id']
    iid = register_instrument(c, 'USDONLY', 'USD', asset_type=asset_type)
    base = f'/api/portfolios/{pid}/transactions'
    row = dict(trade_date='2024-01-02', settlement_date='2024-01-03', type='Buy',
               asset='USDONLY', instrument_id=iid, broker='Example', quantity='1', price='10', asset_currency='BRL')
    assert c.post(base, json=row).status_code == 201
    assert c.post(base + '/import-resolve', json=row).status_code == 200
    assert len(c.get(base).json()) == 1


def test_crypto_accounting_currency_is_separate_from_provider_quotes(client, monkeypatch):
    from datetime import date
    from src.models import Instrument, ProviderInstrument, MarketPrice, LatestMarketQuote
    c, connection = client
    pid = c.post('/api/portfolios', json={'name': 'Crypto accounting'}).json()['id']
    iid = register_instrument(c, 'BTC', 'USD', asset_type='CRYPTO', provider_symbol='BTC-USD')
    assert register_instrument(c, 'BTC', 'EUR', asset_type='CRYPTO', provider_symbol='BTC-EUR') == iid
    assert connection.scalar(select(func.count()).select_from(Instrument).where(Instrument.symbol == 'BTC')) == 1
    assert connection.scalar(select(Instrument.currency).where(Instrument.id == iid)) is None
    base = f'/api/portfolios/{pid}/transactions'
    row = dict(trade_date='2024-01-02', settlement_date='2024-01-03', type='Buy',
               asset='BTC', instrument_id=iid, broker='Example', quantity='0.01', price='320000', asset_currency='BRL')
    saved = c.post(base, json=row)
    assert saved.status_code == 201, saved.text
    tid = saved.json()['id']
    assert c.post(base, json=row | {'asset_currency': 'EUR', 'fx_rate': '6'}).status_code == 422
    assert c.put(base + f'/{tid}', json=row | {'asset_currency': 'USD', 'fx_rate': '5'}).status_code == 422
    csv = ('ticker,broker,type,trade_date,settlement_date,quantity,unit_price,asset_currency\n'
           'BTC,Example,Buy,2024-01-02,2024-01-03,0.01,320000,BRL\n')
    preview = c.post(base + '/import-preview?filename=btc.csv', content=csv).json()
    assert preview['valid'], preview
    resolved = c.post(base + '/import-resolve', json=row | {'asset': 'BITCOIN-BROKER'})
    assert resolved.status_code == 200
    assert c.post(base + '/import', json={'digest': 'c' * 64, 'filename': 'btc.csv', 'rows': [resolved.json()]}).status_code == 201
    with Session(connection, join_transaction_mode='create_savepoint') as session:
        mapping = session.scalar(select(ProviderInstrument).where(ProviderInstrument.instrument_id == iid, ProviderInstrument.quote_currency == 'USD'))
        now = datetime.now(timezone.utc)
        session.add_all([
            MarketPrice(provider_instrument_id=mapping.id, reference_at=datetime(2024, 1, 8, tzinfo=timezone.utc), price=60000, currency='USD', source='yfinance', retrieved_at=now),
            LatestMarketQuote(provider_instrument_id=mapping.id, price=61000, currency='USD', source='yfinance', retrieved_at=now, reference_date=date.today()),
        ])
        session.commit()
    history_calls = []
    monkeypatch.setattr('src.api.market_data.fetch_latest', lambda *a: pytest.fail('Fresh USD quote fetched again'))
    monkeypatch.setattr('src.api.market_data.fetch_history', lambda *a: history_calls.append(a) or [])
    overview = c.get(f'/api/portfolios/{pid}/overview').json()
    position = overview['positions'][0]
    assert position['current_price'] is None
    assert Decimal(str(position['average_cost'])) == 320000
    asset_id = position['asset_id']
    quote_url = f'/api/portfolios/{pid}/assets/{asset_id}/quote'
    quote = c.get(quote_url)
    assert quote.status_code == 200
    assert quote.json()['currency'] == 'USD'
    assert c.post(f'/api/portfolios/{pid}/assets/{asset_id}/refresh').status_code == 200
    assert history_calls and history_calls[0][:2] == ('BTC-USD', 'USD')
    assert c.put(quote_url, json={'date': date.today().isoformat(), 'close': '330000', 'currency': 'BRL'}).status_code == 200
    assert c.get(quote_url).json()['currency'] == 'BRL'
    assert Decimal(str(c.get(f'/api/portfolios/{pid}/overview').json()['positions'][0]['current_price'])) == 330000
    assert c.get(base).json()[0]['price'] == '320000.000000000000'


def test_legacy_provider_registration_is_disabled(client):
    c, _ = client
    payload = dict(symbol='GTLSX', asset_type='STOCK', currency='BRL', provider_symbol='GTLSX')
    assert c.post('/api/instruments', json=payload).status_code == 410
    assert c.post('/api/instruments', json=payload | {'provider_currency_confirmed': True}).status_code == 410
    assert c.post('/api/instruments', json=payload | {'provider_currency_confirmed': True, 'quote_currency': 'USD'}).status_code == 410


@pytest.mark.parametrize('asset_type', ['CRYPTO', 'OTHER'])
def test_selectable_initial_currency_then_portfolio_accounting_lock(client, asset_type):
    c, _ = client
    pid = c.post('/api/portfolios', json={'name': 'Selectable'}).json()['id']
    instrument = c.post('/api/instruments/custom', json={
        'symbol': 'MANUAL', 'name': 'Manual asset', 'asset_type': asset_type, 'currency': 'EUR',
    }).json()
    assert instrument['currency'] == (None if asset_type == 'CRYPTO' else 'EUR')
    row = dict(trade_date='2024-01-02', settlement_date='2024-01-03', type='Buy',
               asset='MANUAL', instrument_id=instrument['id'], broker='Example', quantity=1, price=10, asset_currency='EUR', fx_rate=6)
    base = f'/api/portfolios/{pid}/transactions'
    assert c.post(base, json=row).status_code == 201
    assert c.post(base, json=row | {'asset_currency': 'BRL'}).status_code == 422
