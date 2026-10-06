"""Integration tests use an outer PostgreSQL transaction, rolled back after each test."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from src.main import app
from src.api.market_data import fetch_history as fetch_provider_history
from src.config import ROOT
from src.database import engine, get_session
from src.models import Transaction
from src.import_legacy import import_transactions

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.getenv('RUN_DB_TESTS') != '1', reason='Set RUN_DB_TESTS=1 with PostgreSQL migrated.')]


@pytest.fixture
def client(monkeypatch):
    # Synthetic instruments have no provider events unless a test supplies them.
    # A successful empty response certifies coverage only when actually fetched.
    monkeypatch.setattr('src.api.market_data.fetch_history', lambda *args, **kwargs: [])
    monkeypatch.setattr('src.api.market_data.fetch_rates', lambda *args, **kwargs: [])
    def offline_latest(*args, **kwargs):
        raise OSError('Synthetic test has no provider quote.')
    monkeypatch.setattr('src.api.market_data.fetch_latest', offline_latest)
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


def certify_no_additional_actions(client, portfolio_id, asset_id, first):
    """Explicit source coverage for valuation tests that do not consolidate."""
    from src.corporate_actions import get_actions
    from src.services import get_asset
    sessions = app.dependency_overrides[get_session]()
    try:
        session = next(sessions)
        asset = get_asset(session, portfolio_id, asset_id)
        assert get_actions(session, asset, first, date.today(), fetcher=lambda *_: []).complete
        session.commit()
    finally:
        sessions.close()


def test_closed_round_trips_include_today_return_without_a_quote(client):
    c, _ = client
    pid = c.post('/api/portfolios', json={'name': 'Closed round trips'}).json()['id']
    iid = register_instrument(c, 'ROUNDTRIP12', 'BRL')
    base = f'/api/portfolios/{pid}'
    yesterday = date.today() - timedelta(days=1)
    for day, sale_price in ((yesterday, 12), (date.today(), 11)):
        for kind, price in (('Buy', 10), ('Sell', sale_price)):
            response = c.post(base + '/transactions', json={
                'trade_date': day.isoformat(), 'settlement_date': day.isoformat(),
                'type': kind, 'asset': 'ROUNDTRIP12', 'instrument_id': iid,
                'broker': 'A', 'quantity': 1, 'price': price, 'transaction_currency': 'BRL',
            })
            assert response.status_code == 201, response.text
    assert c.post(base + '/consolidate').json()['complete']
    position = c.get(base + '/overview').json()['positions'][0]
    assert position['quantity'] == position['display_value'] == 0
    assert position['realized_gain'] == 3
    assert position['current_accumulated_profitability'] == 32
    assert position['return_date'] == date.today().isoformat()


def test_consolidation_reports_missing_current_cost_fx(client):
    from src.models import ExchangeRate
    c, connection = client
    pid = c.post('/api/portfolios', json={
        'name': 'Unsettled reporting FX', 'display_currency': 'EUR',
    }).json()['id']
    iid = register_instrument(c, 'SETTLEFX12', 'USD')
    base = f'/api/portfolios/{pid}'
    with Session(connection, join_transaction_mode='create_savepoint') as session:
        for currency, rate in (('USD', 5), ('EUR', 6)):
            session.add(ExchangeRate(currency=currency, rate_type='FX', rate_side='MARKET',
                                     reference_date=date.today(), rate=rate, source='manual'))
        session.commit()
    assert c.post(base + '/transactions', json={
        'trade_date': date.today().isoformat(),
        'settlement_date': (date.today() + timedelta(days=2)).isoformat(),
        'type': 'Buy', 'asset': 'SETTLEFX12', 'instrument_id': iid,
        'broker': 'A', 'quantity': 1, 'price': 10,
        'transaction_currency': 'USD', 'fx_rate': 5,
    }).status_code == 201
    aid = c.get(base + '/overview').json()['assets'][0]['id']
    assert c.put(base + f'/assets/{aid}/quote', json={
        'date': date.today().isoformat(), 'close': 10,
    }).status_code == 200
    result = c.post(base + '/consolidate').json()
    assert c.get(base + '/overview').json()['positions'][0]['status'] == 'missing_fx'
    assert result['complete'] is False
    assert 'SETTLEFX12' in result['incomplete_assets']
    assert result['reasons']['SETTLEFX12']


def test_today_split_is_applied_before_current_quote_and_return(client, monkeypatch):
    import pandas as pd
    import yfinance as yf
    from types import SimpleNamespace
    from src.models import MarketPrice, PositionSnapshot
    monkeypatch.setattr('src.api.market_data.fetch_history', fetch_provider_history)

    c, connection = client
    pid = c.post('/api/portfolios', json={'name': 'Split effective today'}).json()['id']
    iid = register_instrument(c, 'TODAYSPLIT12', 'BRL')
    base = f'/api/portfolios/{pid}'
    yesterday = date.today() - timedelta(days=1)
    assert c.post(base + '/transactions', json={
        'trade_date': yesterday.isoformat(), 'settlement_date': yesterday.isoformat(),
        'type': 'Buy', 'asset': 'TODAYSPLIT12', 'instrument_id': iid, 'broker': 'A',
        'quantity': 10, 'price': 100, 'transaction_currency': 'BRL',
    }).status_code == 201
    # Yahoo reports split-adjusted closes, including the split effective today.
    frame = pd.DataFrame({'Close': [50., 50.], 'Dividends': [0., 0.],
                          'Stock Splits': [0., 2.]},
                         index=pd.DatetimeIndex([yesterday, date.today()], tz='America/Sao_Paulo'))
    monkeypatch.setattr(yf, 'Ticker', lambda _: SimpleNamespace(
        history=lambda **kwargs: frame,
        get_history_metadata=lambda: {'currency': 'BRL', 'exchangeTimezoneName': 'America/Sao_Paulo'}))
    monkeypatch.setattr('src.api.market_data.fetch_latest', lambda *_: {
        'price': Decimal('50'), 'currency': 'BRL',
        'market_at': datetime.combine(date.today(), datetime.min.time(), timezone.utc),
        'retrieved_at': datetime.now(timezone.utc)})
    result = c.post(base + '/consolidate')
    assert result.status_code == 200, result.text
    assert result.json()['complete'], result.json()
    position = c.get(base + '/overview').json()['positions'][0]
    assert position['quantity'] == 20
    assert position['display_value'] == 1000
    assert position['current_total_gain'] == 0
    assert position['current_accumulated_profitability'] == 0
    assert position['status'] == 'complete'
    assert position['price_date'] == date.today().isoformat()
    history = c.get(base + '/performance', params={'asset_id': position['asset_id']}).json()
    assert history[-1]['quantity'] == 10
    assert history[-1]['market_value'] == 1000
    assert history[-1]['cumulative_return_pct'] == 0
    with Session(connection) as session:
        assert session.scalar(select(func.count()).select_from(MarketPrice).where(
            MarketPrice.reference_at >= datetime.combine(date.today(), datetime.min.time(), timezone.utc))) == 0
        assert session.scalar(select(func.count()).select_from(PositionSnapshot).where(
            PositionSnapshot.portfolio_id == pid, PositionSnapshot.date == date.today())) == 1
    # Refreshing/reconsolidating must neither double-apply the split nor rebuild yesterday.
    assert c.post(base + '/consolidate').json()['snapshot_days'] == 0
    assert c.get(base + '/overview').json()['positions'][0]['quantity'] == 20


def test_carried_current_quote_uses_valuation_day_fx(client, monkeypatch):
    from src.models import ExchangeRate

    c, connection = client
    pid = c.post('/api/portfolios', json={'name': 'Carried USD quote'}).json()['id']
    iid = register_instrument(c, 'CARRIEDFX12', 'USD')
    base = f'/api/portfolios/{pid}'
    first = date.today() - timedelta(days=2)
    with Session(connection, join_transaction_mode='create_savepoint') as session:
        for day, rate in ((first, 5), (first + timedelta(days=1), 6), (date.today(), 6)):
            session.add(ExchangeRate(currency='USD', rate_type='FX', rate_side='MARKET',
                                     reference_date=day, rate=rate, source='manual'))
        session.commit()
    assert c.post(base + '/transactions', json={
        'trade_date': first.isoformat(), 'settlement_date': first.isoformat(),
        'type': 'Buy', 'asset': 'CARRIEDFX12', 'instrument_id': iid, 'broker': 'A',
        'quantity': 1, 'price': 10, 'transaction_currency': 'USD', 'fx_rate': 5,
    }).status_code == 201
    monkeypatch.setattr('src.api.market_data.fetch_history', lambda symbol, currency, start, end, **kwargs: [
        {'date': first, 'price': Decimal('10'), 'currency': 'USD', 'source': 'yfinance'}
    ] if start <= first <= end else [])
    monkeypatch.setattr('src.api.market_data.fetch_latest', lambda *_: {
        'price': Decimal('10'), 'currency': 'USD',
        'market_at': datetime.combine(first, datetime.min.time(), timezone.utc),
        'retrieved_at': datetime.now(timezone.utc)})
    assert c.post(base + '/consolidate').json()['complete']
    position = c.get(base + '/overview').json()['positions'][0]
    history = c.get(base + '/performance', params={'asset_id': position['asset_id']}).json()
    assert position['display_value'] == history[-1]['market_value'] == 60
    assert position['current_total_gain'] == history[-1]['total_gain'] == 10
    assert position['current_accumulated_profitability'] == 20
    assert position['price_date'] == first.isoformat()
    assert position['valuation_date'] == date.today().isoformat()
    assert position['return_date'] == date.today().isoformat()
    assert position['status'] == 'complete'


@pytest.mark.parametrize('known_actions', [False, True])
def test_provider_outage_with_manual_prices_cannot_certify_history(client, monkeypatch, known_actions):
    c, _ = client
    pid = c.post('/api/portfolios', json={'name': 'Unverified actions'}).json()['id']
    iid = register_instrument(c, 'ACTIONOUTAGE12', 'BRL')
    base = f'/api/portfolios/{pid}'
    first = date.today() - timedelta(days=2)
    assert c.post(base + '/transactions', json={
        'trade_date': first.isoformat(), 'settlement_date': first.isoformat(),
        'type': 'Buy', 'asset': 'ACTIONOUTAGE12', 'instrument_id': iid, 'broker': 'A',
        'quantity': 1, 'price': 10, 'transaction_currency': 'BRL',
    }).status_code == 201
    aid = c.get(base + '/overview').json()['assets'][0]['id']
    for day in (first, date.today()):
        assert c.put(base + f'/assets/{aid}/quote', json={
            'date': day.isoformat(), 'close': 10,
        }).status_code == 200
    if known_actions:
        certify_no_additional_actions(c, pid, aid, first)
    def unavailable(*args, **kwargs):
        raise OSError('synthetic provider outage')
    monkeypatch.setattr('src.api.market_data.fetch_history', unavailable)
    for _ in range(2):
        response = c.post(base + '/consolidate')
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['complete'] is False
        assert result['history_status'] == 'incomplete'
        assert result['incomplete_assets'] == ['ACTIONOUTAGE12']
        assert result['message'] != 'Carteira consolidada.'
        overview = c.get(base + '/overview').json()
        assert overview['summary']['history_status'] == 'incomplete'
        assert (overview['positions'][0]['status'] == 'complete') == known_actions
        assert overview['positions'][0]['current_accumulated_profitability'] is None
        history = c.get(base + '/performance', params={'asset_id': aid}).json()
        affected = history[1:] if known_actions else history
        assert all(row['status'] != 'complete' for row in affected)
        assert all(row['cumulative_return_pct'] is None for row in affected)
    # Recovery with no events must still invalidate the formerly unknown series.
    monkeypatch.setattr('src.api.market_data.fetch_history', lambda *_, **kwargs: [])
    recovered = c.post(base + '/consolidate').json()
    assert recovered['complete']
    assert recovered['recalculated_from'] == first.isoformat()
    overview = c.get(base + '/overview').json()
    assert overview['summary']['history_status'] == 'complete'
    assert overview['positions'][0]['current_accumulated_profitability'] == 0


def test_expired_current_actions_do_not_certify_a_refreshed_quote(client, monkeypatch):
    from src.models import CorporateActionCoverage
    c, connection = client
    pid = c.post('/api/portfolios', json={'name': 'Current coverage failure'}).json()['id']
    iid = register_instrument(c, 'CURRENTGAP12', 'BRL')
    base = f'/api/portfolios/{pid}'
    yesterday = date.today() - timedelta(days=1)
    assert c.post(base + '/transactions', json={
        'trade_date': yesterday.isoformat(), 'settlement_date': yesterday.isoformat(),
        'type': 'Buy', 'asset': 'CURRENTGAP12', 'instrument_id': iid, 'broker': 'A',
        'quantity': 10, 'price': 100, 'transaction_currency': 'BRL',
    }).status_code == 201
    aid = c.get(base + '/overview').json()['assets'][0]['id']
    for day in (yesterday, date.today()):
        assert c.put(base + f'/assets/{aid}/quote', json={'date': day.isoformat(), 'close': 100}).status_code == 200
    assert c.post(base + '/consolidate').json()['complete']
    previous = c.get(base + '/history').json()
    with Session(connection, join_transaction_mode='create_savepoint') as session:
        coverage = session.scalar(select(CorporateActionCoverage).where(
            CorporateActionCoverage.instrument_id == iid, CorporateActionCoverage.is_final.is_(False)))
        coverage.retrieved_at = datetime.now(timezone.utc) - timedelta(hours=1)
        session.commit()
    def unavailable(*args, **kwargs):
        raise OSError('current actions unavailable')
    monkeypatch.setattr('src.api.market_data.fetch_history', unavailable)
    assert c.get(base + f'/assets/{aid}/quote').status_code == 200
    result = c.post(base + '/consolidate').json()
    assert not result['complete']
    assert result['history_status'] == 'complete'
    assert result['snapshot_days'] == 0
    assert c.get(base + '/history').json() == previous
    position = c.get(base + '/overview').json()['positions'][0]
    assert position['status'] == 'missing_actions'
    assert position['display_value'] is None
    assert position['current_accumulated_profitability'] is None
    assert position['action_coverage_through'] == yesterday.isoformat()
    monkeypatch.setattr('src.api.market_data.fetch_history', lambda *args, **kwargs: [])
    assert c.get(base + f'/assets/{aid}/quote').status_code == 200
    restored = c.get(base + '/overview').json()
    assert restored['summary']['dirty_from'] is None
    assert restored['positions'][0]['status'] == 'complete'
    assert restored['positions'][0]['current_accumulated_profitability'] == 0
    assert c.get(base + '/history').json() == previous


def test_public_api_cannot_write_provider_catalog(client):
    c, _ = client
    response = c.post('/api/instruments', json={
        'symbol': 'BYPASS', 'provider_symbol': 'BYPASS',
        'quote_currency': 'USD', 'provider_currency_confirmed': True,
    })
    assert response.status_code == 410


@pytest.mark.parametrize('source', ['manual_income', 'provider_income', 'manual_price'])
def test_fx_correction_does_not_invalidate_canonical_positions(client, source):
    from src.models import Asset, CorporateAction, ExchangeRate, Portfolio, UserCorporateEvent, UserDefinedPrice
    c, connection = client
    pid = c.post('/api/portfolios', json={'name': 'FX dependencies'}).json()['id']
    iid = register_instrument(c, 'FXDEPEND', 'BRL')
    day = date(2024, 1, 2)
    with Session(connection, join_transaction_mode='create_savepoint') as session:
        asset = Asset(portfolio_id=pid, instrument_id=iid, ticker='FXDEPEND')
        session.add(asset)
        session.flush()
        if source == 'manual_income':
            session.add(UserCorporateEvent(asset_id=asset.id, event_type='DIVIDEND',
                                          effective_date=day, currency='EUR', amount_per_unit=1))
        elif source == 'provider_income':
            session.add(CorporateAction(instrument_id=iid, event_type='DIVIDEND',
                                       effective_date=day, currency='EUR', amount_per_unit=1,
                                       source='yfinance', event_key='fx-dependency'))
        else:
            session.add(UserDefinedPrice(asset_id=asset.id, reference_date=day, currency='EUR', price=1))
        rate = ExchangeRate(currency='EUR', rate_type='FX', rate_side='MARKET',
                            reference_date=day, rate=6, source='yfinance')
        session.add(rate)
        session.flush()
        portfolio = session.get(Portfolio, pid)
        portfolio.dirty_from = None
        session.flush()
        rate.rate = 7
        session.flush()
        assert portfolio.dirty_from is None


def test_portfolio_display_currency_changes_without_editing_transactions(client):
    c, _ = client
    pid = c.post('/api/portfolios', json={'name': 'Currencies'}).json()['id']
    assert c.get('/api/portfolios').json()[-1]['display_currency'] == 'BRL'
    instrument_id = register_instrument(c, 'FXTEST', 'USD')
    base = f'/api/portfolios/{pid}'
    row = dict(trade_date='2024-01-02', settlement_date='2024-01-03', type='Buy',
               asset='FXTEST', instrument_id=instrument_id, broker='A', allocation_class='Stocks',
               quantity=2, price=10, transaction_currency='USD', fx_rate=5)
    assert c.post(base + '/transactions', json=row).status_code == 201
    saved = c.get(base + '/transactions').json()
    aid = c.get(base + '/overview').json()['assets'][0]['id']
    assert c.put(base + f'/assets/{aid}/quote', json={'date': '2024-01-04', 'close': 12}).status_code == 200
    assert c.put(base, json={'name': 'Currencies', 'display_currency': 'USD'}).status_code == 200
    assert c.put(base, json={'name': 'Renamed'}).json()['display_currency'] == 'USD'
    certify_no_additional_actions(c, pid, aid, date(2024, 1, 2))
    assert c.post(base + '/consolidate').status_code == 200
    overview = c.get(base + '/overview').json()
    assert overview['summary']['total_value'] == 24
    assert overview['positions'][0]['acquisition_cost'] == 20
    assert c.get(base + '/transactions').json() == saved


def test_reporting_fx_correction_does_not_rewind_canonical_trade(client):
    from src.models import ExchangeRate, Portfolio
    c, connection = client
    pid = c.post('/api/portfolios', json={'name': 'Settlement FX', 'display_currency': 'EUR'}).json()['id']
    iid = register_instrument(c, 'SETTLEFX', 'BRL')
    assert c.post(f'/api/portfolios/{pid}/transactions', json={
        'trade_date': '2024-01-02', 'settlement_date': '2024-01-04',
        'type': 'Buy', 'asset': 'SETTLEFX', 'instrument_id': iid, 'broker': 'A',
        'quantity': 1, 'price': 10, 'transaction_currency': 'BRL',
    }).status_code == 201
    with Session(connection, join_transaction_mode='create_savepoint') as session:
        portfolio = session.get(Portfolio, pid)
        portfolio.dirty_from = None
        session.flush()
        session.add(ExchangeRate(currency='EUR', rate_type='FX', rate_side='MARKET',
                                 reference_date=date(2024, 1, 4), rate=6, source='yfinance'))
        session.flush()
        assert portfolio.dirty_from is None


def test_consolidation_recalculates_only_dirty_suffix_and_preserves_sources(client):
    c, _ = client
    pid = c.post('/api/portfolios', json={'name': 'Incremental history'}).json()['id']
    iid = register_instrument(c, 'HISTORY', 'BRL')
    base = f'/api/portfolios/{pid}'
    first_day = date.today() - timedelta(days=2)
    row = dict(trade_date=first_day.isoformat(), settlement_date=first_day.isoformat(), type='Buy',
               asset='HISTORY', instrument_id=iid, broker='A', allocation_class='Stocks',
               quantity=10, price=10, transaction_currency='BRL')
    saved = c.post(base + '/transactions', json=row).json()
    aid = c.get(base + '/overview').json()['assets'][0]['id']
    for offset in (0, 1, 2):
        assert c.put(base + f'/assets/{aid}/quote', json={
            'date': (first_day + timedelta(days=offset)).isoformat(),
            'close': 10 if offset == 0 else 11,
        }).status_code == 200
    assert c.get('/api/portfolios').json()[-1]['dirty_from'] == first_day.isoformat()
    first = c.post(base + '/consolidate').json()
    assert first['history_status'] == 'complete'
    before = c.get(base + '/performance', params={'asset_id': aid}).json()
    assert before[0]['quantity'] == 10
    assert before[1]['cumulative_return_pct'] == 10
    assert before[0]['reporting_currency'] == 'BRL'
    assert before[0]['status'] == 'complete'
    portfolio_history = c.get(base + '/history').json()
    assert len(portfolio_history) == len(before)
    assert Decimal(str(portfolio_history[-1]['market_value'])) == 110
    sources = c.get(base + '/transactions').json()
    changed = c.put(base + f'/transactions/{saved["id"]}', json=row | {'quantity': 5}).json()
    assert Decimal(changed['quantity']) == 5
    assert c.get('/api/portfolios').json()[-1]['dirty_from'] == first_day.isoformat()
    second = c.post(base + '/consolidate').json()
    assert second['recalculated_from'] == first_day.isoformat()
    after = c.get(base + '/performance', params={'asset_id': aid}).json()
    assert after[0]['quantity'] == 5
    assert c.get(base + '/transactions').json()[0]['price'] == sources[0]['price']


def test_single_instrument_edit_preserves_unrelated_position_checkpoints(client, monkeypatch):
    from src.models import PositionInvalidation, PositionSnapshot
    from src import consolidation

    c, connection = client
    pid = c.post('/api/portfolios', json={'name': 'Targeted replay'}).json()['id']
    base = f'/api/portfolios/{pid}'
    first = date.today() - timedelta(days=2)
    ids = {symbol: register_instrument(c, symbol, 'BRL') for symbol in ('PETR4', 'ARKK')}
    trades = {}
    for symbol, instrument_id in ids.items():
        payload = dict(trade_date=first.isoformat(), settlement_date=first.isoformat(),
                       type='Buy', asset=symbol, instrument_id=instrument_id,
                       broker='A', quantity=1, price=10, transaction_currency='BRL')
        trades[symbol] = (c.post(base + '/transactions', json=payload).json(), payload)
    assets = {row['ticker']: row['id'] for row in c.get(base + '/overview').json()['assets']}
    for symbol, asset_id in assets.items():
        for offset in (0, 1, 2):
            assert c.put(base + f'/assets/{asset_id}/quote', json={
                'date': (first + timedelta(days=offset)).isoformat(), 'close': 10,
            }).status_code == 200
    assert c.post(base + '/consolidate').status_code == 200
    before = list(connection.scalars(select(PositionSnapshot.id).where(
        PositionSnapshot.portfolio_id == pid,
        PositionSnapshot.instrument_id == ids['ARKK']).order_by(PositionSnapshot.date)))
    transaction, payload = trades['PETR4']
    monkeypatch.setattr('src.api.routes.get_overview', lambda *_: pytest.fail('write called overview'))
    assert c.put(base + f'/transactions/{transaction["id"]}', json=payload | {'quantity': 2}).status_code == 200
    dirty = list(connection.scalars(select(PositionInvalidation.instrument_id).where(
        PositionInvalidation.portfolio_id == pid)))
    assert dirty == [ids['PETR4']]
    calls = []
    original = consolidation.get_history

    def tracked(session, asset, *args, **kwargs):
        calls.append(asset.instrument.symbol)
        return original(session, asset, *args, **kwargs)

    monkeypatch.setattr(consolidation, 'get_history', tracked)
    assert c.post(base + '/consolidate').status_code == 200
    assert 'ARKK' not in calls
    after = list(connection.scalars(select(PositionSnapshot.id).where(
        PositionSnapshot.portfolio_id == pid,
        PositionSnapshot.instrument_id == ids['ARKK']).order_by(PositionSnapshot.date)))
    assert after == before


def test_consolidation_continues_after_missing_quote(client, monkeypatch):
    c, _ = client
    pid = c.post('/api/portfolios', json={'name': 'Partial consolidation'}).json()['id']
    base = f'/api/portfolios/{pid}'
    for symbol in ('GOOD12', 'BAD12'):
        iid = register_instrument(c, symbol, 'BRL')
        assert c.post(base + '/transactions', json={
            'trade_date': (date.today() - timedelta(days=1)).isoformat(),
            'settlement_date': (date.today() - timedelta(days=1)).isoformat(), 'type': 'Buy',
            'asset': symbol, 'instrument_id': iid, 'broker': 'A', 'quantity': 1,
            'price': 10, 'transaction_currency': 'BRL',
        }).status_code == 201
    good_asset = next(asset for asset in c.get(base + '/overview').json()['assets'] if asset['ticker'] == 'GOOD12')
    for day in (date.today() - timedelta(days=1), date.today()):
        assert c.put(base + f'/assets/{good_asset["id"]}/quote', json={
            'date': day.isoformat(), 'close': 12,
        }).status_code == 200
    monkeypatch.setattr('src.market_prices.market_data.fetch_latest',
                        lambda symbol, *_: (_ for _ in ()).throw(OSError(symbol)))
    monkeypatch.setattr('src.api.market_data.fetch_history', lambda *_, **kwargs: [])
    result = c.post(base + '/consolidate').json()
    assert result['complete'] is False
    assert 'BAD12' in result['incomplete_assets']
    assert 'GOOD12' not in result['incomplete_assets']
    assert any('fechamento ausente' in reason for reason in result['reasons']['BAD12'])
    summary = c.get(base + '/overview').json()['summary']
    assert summary['dirty_from'] is None
    assert summary['history_status'] == 'incomplete'
    repeated = c.post(base + '/consolidate').json()
    assert repeated['complete'] is False
    assert repeated['history_status'] == 'incomplete'
    assert repeated['snapshot_days'] == 0
    assert len(c.get(base + '/overview').json()['positions']) == 2
    good_position = next(row for row in c.get(base + '/overview').json()['positions'] if row['asset'] == 'GOOD12')
    assert Decimal(str(good_position['display_value'])) == 12


def test_mixed_currency_btc_sale_is_one_lifetime_position(client):
    c, _ = client
    pid = c.post('/api/portfolios', json={'name': 'One BTC'}).json()['id']
    iid = register_instrument(c, 'BTC12', 'USD', asset_type='CRYPTO', provider_symbol='BTC12-USD')
    base = f'/api/portfolios/{pid}'
    first = (date.today() - timedelta(days=2)).isoformat()
    second = (date.today() - timedelta(days=1)).isoformat()
    common = dict(asset='BTC12', instrument_id=iid, broker='A', allocation_class='Crypto')
    assert c.post(base + '/transactions', json=common | {
        'trade_date': first, 'settlement_date': first, 'type': 'Buy',
        'quantity': 2, 'price': 100, 'transaction_currency': 'BRL',
    }).status_code == 201
    assert c.post(base + '/transactions', json=common | {
        'trade_date': second, 'settlement_date': second, 'type': 'Sell',
        'quantity': 1, 'price': 30, 'transaction_currency': 'USD', 'fx_rate': 5,
    }).status_code == 201
    aid = c.get(base + '/overview').json()['assets'][0]['id']
    certify_no_additional_actions(c, pid, aid, date.fromisoformat(first))
    assert c.post(base + '/consolidate').status_code == 200
    overview = c.get(base + '/overview').json()
    assert len(overview['positions']) == 1
    position = overview['positions'][0]
    assert Decimal(str(position['quantity'])) == 1
    assert Decimal(str(position['realized_gain'])) == 50
    assert position['transaction_currency'] is None
    assert position['status'] == 'missing_price'
    assert c.get(base + '/performance', params={'asset_id': position['asset_id']}).status_code == 200
    assert c.put(base, json={'name': 'One BTC', 'display_currency': 'EUR'}).status_code == 200
    incomplete = c.get(base + '/overview').json()['positions']
    assert len(incomplete) == 1
    assert incomplete[0]['realized_gain'] is None
    assert incomplete[0]['status'] == 'missing_price_and_fx'


def test_reporting_fx_and_dividend_change_history_without_source_mutation(client):
    from src.models import ExchangeRate
    c, connection = client
    pid = c.post('/api/portfolios', json={'name': 'FX return'}).json()['id']
    iid = register_instrument(c, 'FX-INCOME', 'USD')
    base = f'/api/portfolios/{pid}'
    first = date.today() - timedelta(days=2)
    second = first + timedelta(days=1)
    transaction = dict(trade_date=first.isoformat(), settlement_date=first.isoformat(),
                       type='Buy', asset='FX-INCOME', instrument_id=iid, broker='A',
                       quantity=1, price=10, transaction_currency='USD', fx_rate=5)
    assert c.post(base + '/transactions', json=transaction).status_code == 201
    asset_id = c.get(base + '/overview').json()['assets'][0]['id']
    for day in (first, second, date.today()):
        assert c.put(base + f'/assets/{asset_id}/quote', json={
            'date': day.isoformat(), 'close': 10,
        }).status_code == 200
    with Session(connection, join_transaction_mode='create_savepoint') as session:
        for day, rate in ((first, 5), (second, 6), (date.today(), 6)):
            session.add(ExchangeRate(currency='USD', rate_type='FX', rate_side='MARKET',
                                     reference_date=day, rate=rate, source='test',
                                     retrieved_at=datetime.now(timezone.utc)))
        session.commit()
    event_path = base + f'/assets/{asset_id}/corporate-events'
    assert c.post(event_path, json={'event_type': 'DIVIDEND',
                                    'effective_date': second.isoformat(),
                                    'amount_per_unit': 1, 'currency': 'USD'}).status_code == 201
    original = c.get(base + '/transactions').json()
    original_events = c.get(event_path).json()
    certify_no_additional_actions(c, pid, asset_id, first)
    assert c.post(base + '/consolidate').status_code == 200
    brl_overview = c.get(base + '/overview').json()
    brl_current = brl_overview['positions'][0]
    assert Decimal(str(brl_current['display_price'])) == 60
    assert Decimal(str(brl_current['display_value'])) == 60
    assert Decimal(str(brl_current['native_average_cost'])) == 10
    assert Decimal(str(brl_current['native_acquisition_cost'])) == 10
    assert Decimal(str(brl_current['gross_income'])) == 6
    assert Decimal(str(brl_current['native_gross_income'])) == 1
    assert Decimal(str(brl_current['current_total_gain'])) == 16
    assert Decimal(str(brl_overview['summary']['total_gain'])) == 16
    assert Decimal(str(brl_overview['summary']['gross_income'])) == 6
    assert c.post(base + '/consolidate').status_code == 200
    brl = c.get(base + '/performance', params={'asset_id': asset_id}).json()
    assert Decimal(str(brl[-1]['cumulative_return_pct'])) == 32
    assert Decimal(str(brl[-1]['total_gain'])) == 16
    before_currency_change = c.get('/api/portfolios').json()[-1]
    from src.models import PositionSnapshot
    snapshot_ids = list(connection.scalars(select(PositionSnapshot.id).where(
        PositionSnapshot.portfolio_id == pid).order_by(PositionSnapshot.date)))
    assert c.put(base, json={'name': 'FX return', 'display_currency': 'USD'}).status_code == 200
    after_currency_change = c.get('/api/portfolios').json()[-1]
    assert after_currency_change['dirty_from'] == before_currency_change['dirty_from']
    assert after_currency_change['history_built_through'] == before_currency_change['history_built_through']
    usd = c.get(base + '/performance', params={'asset_id': asset_id}).json()
    assert list(connection.scalars(select(PositionSnapshot.id).where(
        PositionSnapshot.portfolio_id == pid).order_by(PositionSnapshot.date))) == snapshot_ids
    assert Decimal(str(usd[-1]['cumulative_return_pct'])) == 10
    assert Decimal(str(usd[-1]['total_gain'])) == 1
    assert c.get(base + '/transactions').json() == original
    assert c.get(event_path).json() == original_events
    with Session(connection, join_transaction_mode='create_savepoint') as session:
        corrected = session.scalar(select(ExchangeRate).where(
            ExchangeRate.currency == 'USD', ExchangeRate.reference_date == second,
        ))
        corrected.rate = 7
        session.commit()
    assert c.get('/api/portfolios').json()[-1]['dirty_from'] is None
    assert c.put(base, json={'name': 'FX return', 'display_currency': 'BRL'}).status_code == 200
    revised = c.get(base + '/performance', params={'asset_id': asset_id}).json()
    assert Decimal(str(revised[-1]['market_value'])) == 70
    assert Decimal(str(revised[-1]['gross_income'])) == 7
    assert Decimal(str(revised[-1]['remaining_acquisition_cost'])) == 50


def test_native_valuation_uses_native_currency_when_quote_differs(client):
    from src.models import ExchangeRate, LatestMarketQuote, ProviderInstrument
    c, connection = client
    pid = c.post('/api/portfolios', json={'name': 'Native quote'}).json()['id']
    iid = register_instrument(c, 'NATIVE12', 'USD')
    base = f'/api/portfolios/{pid}'
    day = date.today() - timedelta(days=1)
    assert c.post(base + '/transactions', json={
        'trade_date': day.isoformat(), 'settlement_date': day.isoformat(),
        'type': 'Buy', 'asset': 'NATIVE12', 'instrument_id': iid,
        'broker': 'A', 'quantity': 2, 'price': 10, 'transaction_currency': 'USD',
        'fx_rate': 5,
    }).status_code == 201
    with Session(connection, join_transaction_mode='create_savepoint') as session:
        mapping = session.scalar(select(ProviderInstrument).where(
            ProviderInstrument.instrument_id == iid))
        mapping.quote_currency = 'BRL'
        session.flush()
        session.add(LatestMarketQuote(
            provider_instrument_id=mapping.id, price=12, currency='BRL',
            source='yfinance', reference_date=day,
            retrieved_at=datetime.now(timezone.utc),
        ))
        session.add(ExchangeRate(currency='USD', rate_type='FX', rate_side='MARKET',
                                 reference_date=day, rate=5, source='test',
                                 retrieved_at=datetime.now(timezone.utc)))
        session.commit()
    aid = c.get(base + '/overview').json()['assets'][0]['id']
    certify_no_additional_actions(c, pid, aid, day)
    assert c.post(base + '/consolidate').status_code == 200
    position = c.get(base + '/overview').json()['positions'][0]
    assert position['quote_currency'] == 'BRL'
    assert position['native_currency'] == 'USD'
    assert Decimal(str(position['display_price'])) == 12
    assert Decimal(str(position['current_price'])) == Decimal('2.4')
    assert Decimal(str(position['total_value'])) == Decimal('4.8')


def test_reconsolidation_preserves_snapshots_before_dirty_date(client):
    from src.models import PositionSnapshot
    c, connection = client
    pid = c.post('/api/portfolios', json={'name': 'Dirty suffix'}).json()['id']
    iid = register_instrument(c, 'SUFFIX', 'BRL')
    base = f'/api/portfolios/{pid}'
    first = date.today() - timedelta(days=2)
    second = first + timedelta(days=1)
    common = dict(asset='SUFFIX', instrument_id=iid, broker='A', type='Buy',
                  transaction_currency='BRL', quantity=1, price=10)
    assert c.post(base + '/transactions', json=common | {
        'trade_date': first.isoformat(), 'settlement_date': first.isoformat(),
    }).status_code == 201
    later = c.post(base + '/transactions', json=common | {
        'trade_date': second.isoformat(), 'settlement_date': second.isoformat(),
    }).json()
    aid = c.get(base + '/overview').json()['assets'][0]['id']
    for day in (first, second, date.today()):
        assert c.put(base + f'/assets/{aid}/quote', json={'date': day.isoformat(), 'close': 10}).status_code == 200
    assert c.post(base + '/consolidate').status_code == 200
    original_id = connection.scalar(select(PositionSnapshot.id).where(
        PositionSnapshot.portfolio_id == pid, PositionSnapshot.date == first))
    assert c.put(base + f'/transactions/{later["id"]}', json=common | {
        'trade_date': second.isoformat(), 'settlement_date': second.isoformat(), 'price': 12,
    }).status_code == 200
    assert c.get('/api/portfolios').json()[-1]['dirty_from'] == second.isoformat()
    result = c.post(base + '/consolidate').json()
    assert result['recalculated_from'] == second.isoformat()
    assert connection.scalar(select(PositionSnapshot.id).where(
        PositionSnapshot.portfolio_id == pid, PositionSnapshot.date == first)) == original_id
    assert c.put(base + f'/assets/{aid}/quote', json={
        'date': second.isoformat(), 'close': 11,
    }).status_code == 200
    assert c.get('/api/portfolios').json()[-1]['dirty_from'] is None


def test_deleting_first_trade_removes_stale_early_history(client):
    c, _ = client
    pid = c.post('/api/portfolios', json={'name': 'Moved history start'}).json()['id']
    iid = register_instrument(c, 'START12', 'BRL')
    base = f'/api/portfolios/{pid}'
    first = date.today() - timedelta(days=2)
    second = first + timedelta(days=1)
    common = dict(asset='START12', instrument_id=iid, broker='A', type='Buy',
                  transaction_currency='BRL', quantity=1, price=10)
    early = c.post(base + '/transactions', json=common | {
        'trade_date': first.isoformat(), 'settlement_date': first.isoformat(),
    }).json()
    assert c.post(base + '/transactions', json=common | {
        'trade_date': second.isoformat(), 'settlement_date': second.isoformat(),
    }).status_code == 201
    aid = c.get(base + '/overview').json()['assets'][0]['id']
    for day in (first, second, date.today()):
        assert c.put(base + f'/assets/{aid}/quote', json={
            'date': day.isoformat(), 'close': 10,
        }).status_code == 200
    assert c.post(base + '/consolidate').status_code == 200
    assert c.get(base + '/performance', params={'asset_id': aid}).json()[0]['date'] == first.isoformat()
    assert c.delete(base + f'/transactions/{early["id"]}').status_code == 204
    assert c.get('/api/portfolios').json()[-1]['dirty_from'] == first.isoformat()
    assert c.post(base + '/consolidate').status_code == 200
    position = c.get(base + '/performance', params={'asset_id': aid}).json()
    portfolio = c.get(base + '/history').json()
    assert position[0]['date'] == second.isoformat()
    assert portfolio[0]['date'] == second.isoformat()
    assert position[0]['quantity'] == 1
    assert portfolio[0]['market_value'] == 10


def test_consolidation_reuses_fresh_shared_quote_without_provider_call(client, monkeypatch):
    from src.models import LatestMarketQuote, ProviderInstrument
    c, connection = client
    pid = c.post('/api/portfolios', json={'name': 'Fresh quote'}).json()['id']
    iid = register_instrument(c, 'FRESH12', 'BRL')
    base = f'/api/portfolios/{pid}'
    yesterday = date.today() - timedelta(days=1)
    assert c.post(base + '/transactions', json={
        'trade_date': yesterday.isoformat(), 'settlement_date': yesterday.isoformat(),
        'type': 'Buy', 'asset': 'FRESH12', 'instrument_id': iid,
        'broker': 'A', 'quantity': 1, 'price': 10, 'transaction_currency': 'BRL',
    }).status_code == 201
    aid = c.get(base + '/overview').json()['assets'][0]['id']
    assert c.put(base + f'/assets/{aid}/quote', json={
        'date': yesterday.isoformat(), 'close': 10,
    }).status_code == 200
    with Session(connection, join_transaction_mode='create_savepoint') as session:
        mapping = session.scalar(select(ProviderInstrument).where(
            ProviderInstrument.instrument_id == iid))
        mapping_id = mapping.id
        session.add(LatestMarketQuote(
            provider_instrument_id=mapping_id, price=12, currency='BRL',
            source='yfinance', reference_date=date.today(),
            retrieved_at=datetime.now(timezone.utc),
        ))
        session.commit()
    monkeypatch.setattr('src.market_prices.market_data.fetch_latest',
                        lambda *args: pytest.fail('Fresh cached quote fetched again'))
    result = c.post(base + '/consolidate')
    assert result.status_code == 200, result.text
    assert result.json()['complete']
    assert Decimal(str(c.get(base + '/overview').json()['positions'][0]['display_value'])) == 12
    with Session(connection, join_transaction_mode='create_savepoint') as session:
        cached = session.scalar(select(LatestMarketQuote).where(
            LatestMarketQuote.currency == 'BRL',
            LatestMarketQuote.provider_instrument_id == mapping_id,
        ))
        cached.retrieved_at = datetime.now(timezone.utc) - timedelta(hours=1)
        session.commit()
    calls = []
    def fresh_quote(*args):
        calls.append(args)
        return {'price': Decimal('14'), 'currency': 'BRL',
                'market_at': datetime.now().astimezone(),
                'retrieved_at': datetime.now(timezone.utc)}
    monkeypatch.setattr('src.market_prices.market_data.fetch_latest', fresh_quote)
    refreshed = c.post(base + '/consolidate').json()
    assert refreshed['snapshot_days'] == 0
    assert len(calls) == 1
    assert Decimal(str(c.get(base + '/overview').json()['positions'][0]['display_value'])) == 14


def test_consolidation_fetches_daily_history_and_exposes_yesterday_value(client, monkeypatch):
    c, _ = client
    pid = c.post('/api/portfolios', json={'name': 'Daily backfill'}).json()['id']
    iid = register_instrument(c, 'BACKFILL12', 'BRL')
    base = f'/api/portfolios/{pid}'
    first = date.today() - timedelta(days=8)
    first -= timedelta(days=first.weekday())
    assert c.post(base + '/transactions', json={
        'trade_date': first.isoformat(), 'settlement_date': first.isoformat(),
        'type': 'Buy', 'asset': 'BACKFILL12', 'instrument_id': iid,
        'broker': 'A', 'quantity': 1, 'price': 10, 'transaction_currency': 'BRL',
    }).status_code == 201
    calls = []
    def fetch_history(symbol, currency, start, end, **kwargs):
        calls.append((start, end))
        return [dict(date=start + timedelta(days=offset), price=Decimal('12'),
                     currency='BRL', source='yfinance')
                for offset in range((end - start).days + 1)
                if (start + timedelta(days=offset)).weekday() < 5
                and start + timedelta(days=offset) != first + timedelta(days=1)]
    monkeypatch.setattr('src.api.market_data.fetch_history', fetch_history)
    monkeypatch.setattr('src.api.market_data.fetch_latest', lambda *_: {
        'price': Decimal('13'), 'currency': 'BRL',
        'market_at': datetime.now().astimezone(), 'retrieved_at': datetime.now(timezone.utc),
    })
    result = c.post(base + '/consolidate')
    assert result.status_code == 200, result.text
    assert calls
    aid = c.get(base + '/overview').json()['assets'][0]['id']
    series = c.get(base + '/performance', params={'asset_id': aid}).json()
    yesterday = date.today() - timedelta(days=1)
    assert series[-1]['date'] == yesterday.isoformat()
    closure = next(row for row in series if row['date'] == (first + timedelta(days=1)).isoformat())
    assert Decimal(str(closure['market_value'])) == 12
    assert closure['status'] == 'complete'
    if yesterday.weekday() < 5:
        assert Decimal(str(series[-1]['market_value'])) == 12
    assert c.get(base + '/overview').json()['summary']['dirty_from'] is None


def test_split_dividend_and_illiquidity_flow_from_yahoo_to_reporting(client, monkeypatch):
    import pandas as pd
    import yfinance as yf
    from types import SimpleNamespace
    from src.models import UserDefinedPrice
    monkeypatch.setattr('src.api.market_data.fetch_history', fetch_provider_history)

    c, connection = client
    pid = c.post('/api/portfolios', json={'name': 'Share units', 'display_currency': 'USD'}).json()['id']
    iid = register_instrument(c, 'UNITS12', 'USD')
    base = f'/api/portfolios/{pid}'
    first = date.today() - timedelta(days=12)
    days = [first, first + timedelta(days=1), first + timedelta(days=2), date.today() - timedelta(days=1)]
    frame = pd.DataFrame({'Close': [50., 49., 49., 55.], 'Dividends': [0., 1., 0., 0.],
                          'Stock Splits': [0., 0., 2., 0.]},
                         index=pd.DatetimeIndex(days, tz='America/New_York'))
    monkeypatch.setattr(yf, 'Ticker', lambda _: SimpleNamespace(
        history=lambda **kwargs: frame,
        get_history_metadata=lambda: {'currency': 'USD', 'exchangeTimezoneName': 'America/New_York'}))
    monkeypatch.setattr('src.api.market_data.fetch_latest', lambda *_: {
        'price': Decimal('55'), 'currency': 'USD',
        'market_at': datetime.now().astimezone(), 'retrieved_at': datetime.now(timezone.utc)})
    assert c.post(base + '/transactions', json={
        'asset': 'UNITS12', 'instrument_id': iid, 'broker': 'A', 'type': 'Buy',
        'trade_date': first.isoformat(), 'settlement_date': first.isoformat(),
        'quantity': 1, 'price': 100, 'transaction_currency': 'USD', 'fx_rate': 5,
    }).status_code == 201
    aid = c.get(base + '/overview').json()['assets'][0]['id']
    with Session(connection, join_transaction_mode='create_savepoint') as session:
        session.add(UserDefinedPrice(asset_id=aid, reference_date=first,
                                      price=50, currency='USD', source='legacy'))
        session.commit()
    source = c.get(base + '/transactions').json()
    result = c.post(base + '/consolidate').json()
    assert result['complete'] is True
    series = c.get(base + '/performance', params={'asset_id': aid}).json()
    assert [Decimal(str(row['cumulative_return_pct'])) for row in series[:3]] == [0, 0, 0]
    assert all(row['status'] == 'complete' for row in series)
    assert series[-2]['quote_date'] == days[2].isoformat()
    assert series[-1]['quantity'] == 2
    assert series[-1]['gross_income'] == 2
    assert series[-1]['total_gain'] == 12
    position = c.get(base + '/overview').json()['positions'][0]
    assert position['current_total_gain'] == 12
    assert Decimal(str(position['current_accumulated_profitability'])) > 0
    assert c.get(base + '/transactions').json() == source
    assert c.post(base + '/consolidate').json()['snapshot_days'] == 0


def test_crud_prices_isolation_and_rollback(client, monkeypatch):
    c, _ = client
    assert c.get('/api/health').status_code == 200
    pid = c.post('/api/portfolios', json={'name': 'Integration test'}).json()['id']
    other = c.post('/api/portfolios', json={'name': 'Other'}).json()['id']
    instrument_id = register_instrument(c, 'TEST', 'BRL')
    base = f'/api/portfolios/{pid}'
    payload = dict(trade_date='2024-01-02', settlement_date='2024-01-03', type='Buy',
                   asset='test', instrument_id=instrument_id, broker='Broker', allocation_class='Stocks', quantity=10,
                   price=20, transaction_currency='BRL', brokerage_fee=1, other_fees=2, notes='')
    response = c.post(base + '/transactions', json=payload)
    assert response.status_code == 201, response.text
    assert response.json()['instrument_id'] == instrument_id
    tid = response.json()['id']
    result = c.get(base + '/overview').json()
    assert result['positions'][0]['average_cost'] is None
    assert result['positions'][0]['status'] == 'pending'
    aid = result['assets'][0]['id']
    certify_no_additional_actions(c, pid, aid, date(2024, 1, 2))
    assert c.put(base + f'/assets/{aid}/quote', json={'date': '2024-01-03', 'close': 30}).status_code == 200
    assert c.post(base + '/consolidate').status_code == 200
    result = c.get(base + '/overview').json()
    assert result['positions'][0]['average_cost'] == 20.3
    assert result['summary']['total_value'] == 300
    assert result['positions'][0]['current_total_gain'] == 97
    assert c.get(f'/api/portfolios/{other}/assets/{aid}/history').status_code == 404
    assert c.delete(f'/api/portfolios/{other}/transactions/{tid}').status_code == 404
    assert c.put(base + f'/transactions/{tid}', json=payload | {'quantity': 5}).status_code == 200
    assert c.get(base + '/overview').json()['summary']['total_value'] == 300
    assert c.post(base + '/consolidate').status_code == 200
    assert c.get(base + '/overview').json()['summary']['total_value'] == 150
    assert c.post(base + '/transactions', json=payload | {'quantity': -1}).status_code == 422
    assert len(c.get(base + '/transactions').json()) == 1
    monkeypatch.setattr('src.market_prices.market_data.fetch_history', lambda *args: (_ for _ in ()).throw(RuntimeError('offline')))
    monkeypatch.setattr('src.market_prices.market_data.fetch_latest', lambda *args: (_ for _ in ()).throw(RuntimeError('offline')))
    assert c.post(base + f'/assets/{aid}/refresh').status_code == 502
    assert c.get(base + f'/assets/{aid}/history').json()[0]['close'] == 30
    assert c.post('/api/portfolios', json={'name':'forbidden'}, headers={'Origin':'https://example.com'}).status_code == 403
    assert c.delete(base + f'/transactions/{tid}').status_code == 204
    assert c.get(base + '/overview').json()['positions'][0]['status'] == 'pending'
    assert c.post(base + '/consolidate').status_code == 200
    cleared = c.get(base + '/overview').json()
    assert cleared['positions'] == []
    assert cleared['summary']['history_status'] == 'complete'
    assert cleared['summary']['total_value'] == 0


def test_quote_endpoint_keeps_manual_prices_private_and_checks_currency(client, monkeypatch):
    from datetime import date
    c, _ = client
    first = c.post('/api/portfolios', json={'name': 'Manual price owner'}).json()['id']
    second = c.post('/api/portfolios', json={'name': 'Other price owner'}).json()['id']
    instrument_id = register_instrument(c, 'QUOTE-TEST', 'USD')
    payload = dict(trade_date='2024-01-02', settlement_date='2024-01-02', type='Buy',
                   asset='QUOTE-TEST', instrument_id=instrument_id, broker='Example', quantity='1', price='10',
                   transaction_currency='USD', fx_rate='5')
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
        broker='Synthetic', quantity='1', price='10', transaction_currency='BRL',
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
        'ticker,broker,type,trade_date,settlement_date,quantity,unit_price,transaction_currency,fx_rate\n'
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
               asset='TEST', instrument_id=test_instrument_id, broker='Example', quantity='1', price='10', transaction_currency='BRL')
    assert c.post(base, json=row).status_code == 201
    csv = ('ticker,broker,type,trade_date,settlement_date,quantity,unit_price,transaction_currency,fx_rate\n'
           'TEST,Example,Buy,2024-01-02,2024-01-03,1,10,USD,5\n')
    preview = c.post(base + '/import-preview?filename=conflict.csv', content=csv).json()
    assert not preview['valid']
    assert preview['rows'][0]['errors'][0]['field'] == 'transaction_currency'
    result = c.post(base + '/import', json={
        'digest': 'a' * 64, 'filename': 'conflict.csv',
        'rows': [row | {'asset': 'NEW', 'instrument_id': new_instrument_id}, row | {'transaction_currency': 'USD', 'fx_rate': '5'}],
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
                   price='10.000000000001', transaction_currency='USD')
    response = c.post(base, json=payload)
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved['quantity'] == payload['quantity']
    assert saved['price'] == payload['price']
    assert calls == [date(2024, 1, 4)]
    timestamp = datetime(2024, 1, 2, 15, 30)
    connection.execute(Transaction.__table__.update().where(Transaction.id == saved['id']).values(date_time=timestamp))
    edit = {
        key: value for key, value in saved.items()
        if key not in {'id', 'portfolio_id', 'transaction_currency_locked'}
    }
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
    csv = ('ticker,broker,type,trade_date,settlement_date,quantity,unit_price,transaction_currency\n'
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
    assert overview['positions'][0]['quantity'] is None
    assert overview['positions'][0]['status'] == 'pending'
    assert c.post(f'/api/portfolios/{pid}/consolidate').status_code == 200
    assert c.get(f'/api/portfolios/{pid}/overview').json()['positions'][0]['quantity'] == 2


@pytest.mark.parametrize('asset_type', ['STOCK', 'ETF'])
def test_listed_transactions_use_native_currency_and_reject_conflicts(client, asset_type):
    c, _ = client
    pid = c.post('/api/portfolios', json={'name': 'Currency safety'}).json()['id']
    iid = register_instrument(c, 'USDONLY', 'USD', asset_type=asset_type)
    base = f'/api/portfolios/{pid}/transactions'
    row = dict(trade_date='2024-01-02', settlement_date='2024-01-03', type='Buy',
               asset='USDONLY', instrument_id=iid, broker='Example', quantity='1', price='10', fx_rate='5')
    saved = c.post(base, json=row)
    assert saved.status_code == 201, saved.text
    assert saved.json()['transaction_currency'] == 'USD'
    assert saved.json()['transaction_currency_locked'] is True
    assert c.post(base, json=row | {'transaction_currency': 'BRL'}).status_code == 422
    resolved = c.post(base + '/import-resolve', json=row)
    assert resolved.status_code == 200
    assert resolved.json()['transaction_currency'] == 'USD'
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
               asset='BTC', instrument_id=iid, broker='Example', quantity='0.01', price='320000', transaction_currency='BRL')
    saved = c.post(base, json=row)
    assert saved.status_code == 201, saved.text
    assert saved.json()['transaction_currency_locked'] is False
    tid = saved.json()['id']
    second = c.post(base, json=row | {'transaction_currency': 'EUR', 'fx_rate': '6'})
    assert second.status_code == 201, second.text
    assert c.put(base + f'/{tid}', json=row | {'transaction_currency': 'USD', 'fx_rate': '5'}).status_code == 200
    transactions = c.get(base).json()
    assert {transaction['instrument_id'] for transaction in transactions} == {iid}
    assert {transaction['transaction_currency'] for transaction in transactions} == {'EUR', 'USD'}
    csv = ('ticker,broker,type,trade_date,settlement_date,quantity,unit_price,transaction_currency\n'
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
    monkeypatch.setattr('src.api.market_data.fetch_history', lambda *a, **kwargs: history_calls.append(a) or [])
    aid = c.get(f'/api/portfolios/{pid}/overview').json()['assets'][0]['id']
    certify_no_additional_actions(c, pid, aid, date(2024, 1, 2))
    assert c.post(f'/api/portfolios/{pid}/consolidate').status_code == 200
    overview = c.get(f'/api/portfolios/{pid}/overview').json()
    assert len(overview['positions']) == 1
    position = overview['positions'][0]
    assert position['transaction_currency'] is None
    assert position['current_price'] == 61000
    assert Decimal(str(position['quantity'])) == Decimal('0.03')
    assert Decimal(str(position['acquisition_cost'])) == 38400
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
def test_selectable_transaction_currency_allows_multiple_values_per_instrument(client, asset_type):
    c, _ = client
    pid = c.post('/api/portfolios', json={'name': 'Selectable'}).json()['id']
    instrument = c.post('/api/instruments/custom', json={
        'symbol': 'MANUAL', 'name': 'Manual asset', 'asset_type': asset_type, 'currency': 'EUR',
    }).json()
    assert instrument['currency'] == (None if asset_type == 'CRYPTO' else 'EUR')
    row = dict(trade_date='2024-01-02', settlement_date='2024-01-03', type='Buy',
               asset='MANUAL', instrument_id=instrument['id'], broker='Example', quantity=1, price=10, transaction_currency='EUR', fx_rate=6)
    base = f'/api/portfolios/{pid}/transactions'
    assert c.post(base, json=row).status_code == 201
    assert c.post(base, json=row | {'transaction_currency': 'BRL'}).status_code == 201


def test_manual_corporate_event_crud_recalculates_and_feeds_activity(client):
    c, _ = client
    pid = c.post('/api/portfolios', json={'name': 'Corporate events'}).json()['id']
    iid = register_instrument(c, 'EVENT-TEST', 'USD')
    base = f'/api/portfolios/{pid}'
    transaction = {
        'trade_date': '2024-01-02', 'settlement_date': '2024-01-03',
        'type': 'Buy', 'asset': 'EVENT-TEST', 'instrument_id': iid,
        'broker': 'Example', 'allocation_class': 'Stocks',
        'quantity': '10', 'price': '20', 'transaction_currency': 'USD', 'fx_rate': '5',
    }
    assert c.post(base + '/transactions', json=transaction).status_code == 201
    asset_id = c.get(base + '/overview').json()['assets'][0]['id']
    events_url = base + f'/assets/{asset_id}/corporate-events'

    split = c.post(events_url, json={
        'event_type': 'STOCK_SPLIT', 'effective_date': '2024-01-03',
        'conversion_factor': '2', 'notes': '2 for 1',
    })
    assert split.status_code == 201, split.text
    dividend = c.post(events_url, json={
        'event_type': 'DIVIDEND', 'effective_date': '2024-01-04',
        'payment_date': '2024-01-10', 'amount_per_unit': '1.5',
        'currency': 'USD', 'notes': '',
    })
    assert dividend.status_code == 201, dividend.text
    assert c.post(events_url, json={
        'event_type': 'DIVIDEND', 'effective_date': '2024-01-04',
        'amount_per_unit': '9', 'currency': 'USD',
    }).status_code == 409

    assert c.post(base + '/consolidate').status_code == 200
    overview = c.get(base + '/overview').json()
    assert Decimal(str(overview['positions'][0]['quantity'])) == 20
    assert Decimal(str(overview['positions'][0]['average_cost'])) == 50
    assert Decimal(str(overview['positions'][0]['income_by_currency']['USD'])) == 30
    events = c.get(events_url).json()
    assert [row['origin'] for row in events] == ['manual', 'manual']
    assert Decimal(str(events[1]['gross_amount'])) == 30
    activity = c.get(base + f'/assets/{asset_id}/activity').json()
    assert [row['kind'] for row in activity] == [
        'TRANSACTION', 'CORPORATE_ACTION', 'CORPORATE_ACTION',
    ]

    dividend_id = dividend.json()['id']
    edited = c.put(events_url + f'/{dividend_id}', json={
        'event_type': 'DIVIDEND', 'effective_date': '2024-01-04',
        'payment_date': '2024-01-10', 'amount_per_unit': '2',
        'currency': 'USD', 'notes': 'corrected',
    })
    assert edited.status_code == 200, edited.text
    assert Decimal(str(c.get(base + '/overview').json()['positions'][0]['income_by_currency']['USD'])) == 30
    assert c.post(base + '/consolidate').status_code == 200
    assert Decimal(str(c.get(base + '/overview').json()['positions'][0]['income_by_currency']['USD'])) == 40

    assert c.delete(events_url + f"/{split.json()['id']}").status_code == 204
    assert c.get(base + '/overview').json()['positions'][0]['quantity'] == 20
    assert c.post(base + '/consolidate').status_code == 200
    final = c.get(base + '/overview').json()['positions'][0]
    assert Decimal(str(final['quantity'])) == 10
    assert Decimal(str(final['average_cost'])) == 100
    assert Decimal(str(final['income_by_currency']['USD'])) == 20


def test_asset_activity_orders_same_day_split_before_income(client):
    c, _ = client
    pid = c.post('/api/portfolios', json={'name': 'Same day events'}).json()['id']
    iid = register_instrument(c, 'ORDER-TEST', 'USD')
    base = f'/api/portfolios/{pid}'
    transaction = {
        'trade_date': '2024-01-02', 'settlement_date': '2024-01-03',
        'type': 'Buy', 'asset': 'ORDER-TEST', 'instrument_id': iid,
        'broker': 'Example', 'allocation_class': 'Stocks',
        'quantity': '10', 'price': '20', 'transaction_currency': 'USD', 'fx_rate': '5',
    }
    assert c.post(base + '/transactions', json=transaction).status_code == 201
    asset_id = c.get(base + '/overview').json()['assets'][0]['id']
    events_url = base + f'/assets/{asset_id}/corporate-events'
    assert c.post(events_url, json={
        'event_type': 'DIVIDEND', 'effective_date': '2024-01-03',
        'amount_per_unit': '1', 'currency': 'USD',
    }).status_code == 201
    assert c.post(events_url, json={
        'event_type': 'STOCK_SPLIT', 'effective_date': '2024-01-03',
        'conversion_factor': '2',
    }).status_code == 201

    activity = c.get(base + f'/assets/{asset_id}/activity').json()
    assert [row.get('event_type', row.get('type')) for row in activity] == [
        'Buy', 'STOCK_SPLIT', 'DIVIDEND',
    ]
    assert Decimal(str(activity[-1]['eligible_quantity'])) == 20
