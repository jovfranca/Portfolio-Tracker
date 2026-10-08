"""Stored portfolio FX diagnostics respect dated conversion and fallback contracts."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Asset, ExchangeRate, FixedIncomeSnapshot
from tests.test_auth import auth_client, login


def create_foreign_position(client, currency='USD', display='BRL'):
    pid = client.post('/api/portfolios', json={'name': 'FX coverage', 'display_currency': display}).json()['id']
    iid = client.post('/api/instruments/custom', json={
        'symbol': 'SYNTH-FX', 'name': 'Synthetic FX instrument', 'currency': currency,
    }).json()['id']
    first = date.today() - timedelta(days=3)
    assert client.post(f'/api/portfolios/{pid}/transactions', json={
        'asset': 'SYNTH-FX', 'instrument_id': iid, 'type': 'Buy', 'broker': 'Synthetic',
        'trade_date': first.isoformat(), 'settlement_date': first.isoformat(),
        'quantity': '2', 'price': '10', 'transaction_currency': currency, 'fx_rate': '5',
    }).status_code == 201
    return pid, first


def test_fx_coverage_history_fallback_missing_dates_and_truthful_timestamps(auth_client, monkeypatch):
    client, engine = auth_client
    login(client)
    pid, first = create_foreign_position(client)
    retrieved = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    with Session(engine) as session:
        session.add(ExchangeRate(currency='USD', rate_type='FX', rate_side='MARKET',
            reference_date=first, rate=Decimal('5'), source='synthetic', retrieved_at=retrieved))
        session.add_all([ExchangeRate(currency='USD', rate_type='PTAX', rate_side=side,
            reference_date=first, rate=Decimal('5'), source='bcb-synthetic', retrieved_at=retrieved)
            for side in ('BUY', 'SELL')])
        session.commit()
    monkeypatch.setenv('RATE_FALLBACK_DAYS', '1')
    def no_provider(*args, **kwargs):
        raise AssertionError('Coverage must never fetch or mutate rates')
    monkeypatch.setattr('src.api.market_data.fetch_rates', no_provider)
    response = client.get(f'/api/portfolios/{pid}/fx-coverage')
    assert response.status_code == 200
    data = response.json()
    assert data['reporting_currency'] == 'BRL'
    assert data['status'] == 'incomplete'
    pair = data['pairs'][0]
    assert pair['currency'] == 'USD' and pair['base_currency'] == 'BRL'
    assert pair['required_start'] == first.isoformat() and pair['required_end'] == date.today().isoformat()
    assert pair['missing_dates'] == [(first + timedelta(days=2)).isoformat(), date.today().isoformat()]
    assert pair['covered_count'] == 2 and pair['required_count'] == 4
    assert pair['requirements'][1]['reference_date'] == first.isoformat()
    assert pair['requirements'][1]['fallback_used']
    assert {row['rate_type'] for row in pair['history']} == {'FX', 'PTAX'}
    assert {row['source'] for row in pair['history']} == {'synthetic', 'bcb-synthetic'}
    assert data['last_successful_sync_at'] is None and data['sync_tracking'] == 'not_recorded'
    assert pair['last_observation_retrieved_at'].startswith('2026-01-01T12:00:00')
    login(client, 'stranger')
    assert client.get(f'/api/portfolios/{pid}/fx-coverage').status_code == 404


def test_fx_coverage_includes_display_currency_bridge_without_requiring_same_currency_rates(auth_client):
    client, engine = auth_client
    login(client)
    pid, first = create_foreign_position(client, display='EUR')
    data = client.get(f'/api/portfolios/{pid}/fx-coverage').json()
    assert {p['currency'] for p in data['pairs']} == {'USD', 'EUR'}
    assert all(p['missing_dates'] for p in data['pairs'])
    # The transaction FX is already frozen in BRL. Only EUR is needed for its reporting cost.
    usd = next(p for p in data['pairs'] if p['currency'] == 'USD')
    eur = next(p for p in data['pairs'] if p['currency'] == 'EUR')
    assert 'transaction_reporting' not in usd['requirements'][0]['reasons']
    assert 'transaction_reporting' in eur['requirements'][0]['reasons']
    assert client.put(f'/api/portfolios/{pid}', json={'name': 'FX coverage', 'display_currency': 'USD'}).status_code == 200
    assert client.get(f'/api/portfolios/{pid}/fx-coverage').json()['pairs'] == []


def test_brl_only_portfolio_has_complete_empty_fx_coverage(auth_client):
    client, _ = auth_client
    login(client)
    pid = client.post('/api/portfolios', json={'name': 'No FX'}).json()['id']
    data = client.get(f'/api/portfolios/{pid}/fx-coverage').json()
    assert data['pairs'] == [] and data['status'] == 'complete'


def test_fx_coverage_reports_unresolved_accounting_currency_instead_of_claiming_complete(auth_client):
    client, engine = auth_client
    login(client)
    pid, _ = create_foreign_position(client)
    with Session(engine) as session:
        asset = session.scalar(select(Asset).where(Asset.portfolio_id == pid))
        asset.instrument.asset_type = 'CRYPTO'  # no primary pricing mapping in this synthetic fixture
        session.commit()
    response = client.get(f'/api/portfolios/{pid}/fx-coverage')
    assert response.status_code == 200
    assert response.json()['status'] == response.json()['requirements_status'] == 'incomplete'
    assert response.json()['unknown_requirements'] == ['SYNTH-FX']


def test_fx_coverage_stops_market_valuation_after_closure_and_includes_income_currency(auth_client, monkeypatch):
    from src.corporate_actions import CorporateActionResult, get_stored_actions
    client, engine = auth_client
    login(client)
    pid, first = create_foreign_position(client)
    monkeypatch.setattr('src.api.market_data.fetch_rates', lambda *args: [])
    monkeypatch.setattr('src.consolidation.get_actions', lambda session, asset, start, end:
                        CorporateActionResult(get_stored_actions(session, asset, start, end), []))
    aid = client.get(f'/api/portfolios/{pid}/overview').json()['assets'][0]['id']
    assert client.put(f'/api/portfolios/{pid}/assets/{aid}/quote', json={
        'date': first.isoformat(), 'close': '10',
    }).status_code == 200
    iid = client.get(f'/api/portfolios/{pid}/transactions').json()[0]['instrument_id']
    assert client.post(f'/api/portfolios/{pid}/assets/{aid}/corporate-events', json={
        'event_type': 'DIVIDEND', 'effective_date': (first + timedelta(days=1)).isoformat(),
        'amount_per_unit': '1', 'currency': 'EUR',
    }).status_code == 201
    assert client.post(f'/api/portfolios/{pid}/transactions', json={
        'asset': 'SYNTH-FX', 'instrument_id': iid, 'type': 'Sell', 'broker': 'Synthetic',
        'trade_date': (first + timedelta(days=2)).isoformat(),
        'settlement_date': (first + timedelta(days=2)).isoformat(),
        'quantity': '2', 'price': '12', 'transaction_currency': 'USD', 'fx_rate': '5',
    }).status_code == 201
    assert client.post(f'/api/portfolios/{pid}/consolidate').status_code == 200
    data = client.get(f'/api/portfolios/{pid}/fx-coverage').json()
    usd = next(p for p in data['pairs'] if p['currency'] == 'USD')
    eur = next(p for p in data['pairs'] if p['currency'] == 'EUR')
    assert usd['required_end'] == (first + timedelta(days=1)).isoformat()
    assert eur['required_start'] == eur['required_end'] == (first + timedelta(days=1)).isoformat()
    assert eur['requirements'][0]['reasons'] == ['income_reporting']


def test_fx_coverage_includes_retained_fixed_income_snapshots_and_display_bridge(auth_client):
    client, engine = auth_client
    login(client)
    pid = client.post('/api/portfolios', json={'name': 'FI FX', 'display_currency': 'EUR'}).json()['id']
    iid = client.post('/api/instruments/custom', json={
        'symbol': 'RETAINED', 'name': 'Synthetic retained snapshot', 'currency': 'USD',
    }).json()['id']
    first = date.today() - timedelta(days=2)
    # Source deletion can leave saved lot history until the next consolidation.
    with Session(engine) as session:
        session.add(FixedIncomeSnapshot(portfolio_id=pid, instrument_id=iid, lot_id=999,
            date=first, accounting_currency='USD', status='complete', valuation={},
            ledger_state=None, lot_metadata={}, net_flow=0, purchases=0))
        session.commit()
    data = client.get(f'/api/portfolios/{pid}/fx-coverage').json()
    assert {p['currency'] for p in data['pairs']} == {'USD', 'EUR'}
    assert all(p['required_count'] == 3 for p in data['pairs'])
    assert all(p['requirements'][0]['reasons'] == ['fixed_income_valuation'] for p in data['pairs'])
