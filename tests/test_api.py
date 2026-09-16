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


def test_crud_prices_isolation_and_rollback(client, monkeypatch):
    c, _ = client
    assert c.get('/api/health').status_code == 200
    pid = c.post('/api/portfolios', json={'name': 'Integration test'}).json()['id']
    other = c.post('/api/portfolios', json={'name': 'Other'}).json()['id']
    base = f'/api/portfolios/{pid}'
    payload = dict(trade_date='2024-01-02', settlement_date='2024-01-03', type='Buy',
                   asset='test', broker='Broker', allocation_class='Stocks', quantity=10,
                   price=20, asset_currency='BRL', brokerage_fee=1, other_fees=2, notes='')
    response = c.post(base + '/transactions', json=payload)
    assert response.status_code == 201, response.text
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
    monkeypatch.setattr('src.api.routes.fetch_history', lambda *args: (_ for _ in ()).throw(RuntimeError('offline')))
    assert c.post(base + f'/assets/{aid}/refresh').status_code == 502
    assert c.get(base + f'/assets/{aid}/history').json()[0]['close'] == 30
    assert c.post('/api/portfolios', json={'name':'forbidden'}, headers={'Origin':'https://example.com'}).status_code == 403
    assert c.delete(base + f'/transactions/{tid}').status_code == 204
    assert c.get(base + '/overview').json()['positions'] == []


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
    base = f'/api/portfolios/{pid}/transactions'
    row = dict(trade_date='2024-01-02', settlement_date='2024-01-03', type='Buy',
               asset='TEST', broker='Example', quantity='1', price='10', asset_currency='BRL')
    assert c.post(base, json=row).status_code == 201
    csv = ('ticker,broker,type,trade_date,settlement_date,quantity,unit_price,asset_currency,fx_rate\n'
           'TEST,Example,Buy,2024-01-02,2024-01-03,1,10,USD,5\n')
    preview = c.post(base + '/import-preview?filename=conflict.csv', content=csv).json()
    assert not preview['valid']
    assert preview['rows'][0]['errors'][0]['field'] == 'asset_currency'
    result = c.post(base + '/import', json={
        'digest': 'a' * 64, 'filename': 'conflict.csv',
        'rows': [row | {'asset': 'NEW'}, row | {'asset_currency': 'USD', 'fx_rate': '5'}],
    })
    assert result.status_code == 422
    assert len(c.get(base).json()) == 1
    assert len(c.get(f'/api/portfolios/{pid}/overview').json()['assets']) == 1


def test_manual_fx_precision_and_edit_preserve_history(client, monkeypatch):
    from datetime import date
    c, connection = client
    pid = c.post('/api/portfolios', json={'name': 'Frozen history'}).json()['id']
    base = f'/api/portfolios/{pid}/transactions'
    calls = []
    def rates(session, currency, rate_type, day):
        from types import SimpleNamespace
        calls.append(day)
        return [SimpleNamespace(rate_side='MARKET', rate=Decimal('5.123456789012'))]
    monkeypatch.setattr('src.services.get_rates', rates)
    payload = dict(trade_date='2024-01-02', settlement_date='2024-01-04', type='Buy',
                   asset='USDTEST', broker='Example', quantity='12345.123456789012',
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
