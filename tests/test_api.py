"""Integration tests use an outer PostgreSQL transaction, rolled back after each test."""
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
    payload = dict(date_time='2024-01-02T10:00:00', type='Buy', asset='test', broker='Broker',
                   allocation_class='Stocks', quantity=10, price=20, brokerage_fee=1, other_fees=2, notes='')
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
