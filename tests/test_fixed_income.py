from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import CheckConstraint, MetaData, create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.database import Base, engine as postgres_engine, get_session
from src.main import app
from src.models import (
    Benchmark, BenchmarkObservation, BenchmarkProviderMapping, ExchangeRate,
    FixedIncomeLot, FixedIncomeMovement, FixedIncomeProduct, Instrument, Portfolio, PortfolioSnapshot,
)


@pytest.fixture
def client():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    sqlite_metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        table.to_metadata(sqlite_metadata)
    transaction_table = sqlite_metadata.tables['transactions']
    for constraint in list(transaction_table.constraints):
        if isinstance(constraint, CheckConstraint) and '~' in str(constraint.sqltext):
            transaction_table.constraints.remove(constraint)
    sqlite_metadata.create_all(engine)

    def override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override
    with Session(engine) as session:
        session.add_all([
            Portfolio(name='Savings'),
            Instrument(symbol='CDB-ISSUER', name='Issuer CDB', asset_type='FIXED_INCOME', currency='BRL', portfolio_id=1),
            Benchmark(code='CDI', name='CDI', kind='INTEREST_RATE', frequency='DAILY',
                      value_type='RATE', unit='PERCENT_PER_DAY', status='ACTIVE'),
        ])
        session.commit()
    try:
        with TestClient(app) as value:
            yield value, engine
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def lot_payload(**changes):
    payload = {
        'instrument_id': 1, 'product_type': 'CDB', 'issuer': 'Issuer', 'broker': 'Broker',
        'currency': 'BRL', 'start_date': '2024-01-02', 'maturity_date': '2026-01-02',
        'yield_structure': 'FIXED_RATE', 'fixed_rate': '0.12',
        'day_count_basis': 'BUS_252', 'compounding': 'COMPOUND',
        'business_day_calendar': 'BR', 'benchmark_lag_months': 0,
        'opening_amount': '1000.00',
    }
    payload.update(changes)
    return payload


def test_reporting_uses_saved_lots_through_pending_edits_and_deletion(client, monkeypatch):
    c, engine = client
    start = date.today() - timedelta(days=4)
    created = c.post('/api/portfolios/1/fixed-income/lots', json=lot_payload(
        start_date=start.isoformat(), maturity_date=None, fixed_rate='0',
        day_count_basis='ACT_365', business_day_calendar='NONE')).json()
    overview_url = '/api/portfolios/1/overview'
    assert c.get(overview_url).json()['positions'][0]['status'] == 'pending'
    assert c.get(overview_url).json()['summary']['total_value'] is None
    assert c.post('/api/portfolios/1/consolidate').status_code == 200
    history_url = '/api/portfolios/1/history'
    saved = c.get(history_url).json()
    opening = created['movements'][0]['id']
    movement_url = f"/api/portfolios/1/fixed-income/lots/{created['id']}/movements/{opening}"
    edited = c.put(movement_url, json={
        'movement_type': 'INITIAL_INVESTMENT', 'effective_date': start.isoformat(),
        'amount': '1500', 'currency': 'BRL'})
    assert edited.status_code == 200, edited.text
    from src import fixed_income, fixed_income_history, domain
    with monkeypatch.context() as guard:
        guard.setattr(fixed_income, '_lot_valuation', lambda *_: pytest.fail('GET replayed contract'))
        guard.setattr(fixed_income_history, 'fixed_income_valuation', lambda *_args, **_kwargs: pytest.fail('GET replayed contract'))
        guard.setattr(domain, 'fixed_income_valuation', lambda *_args, **_kwargs: pytest.fail('GET replayed contract'))
        assert c.get(overview_url).json()['positions'][0]['display_value'] == 1000
        pending = c.get(history_url).json()
        assert [row['market_value'] for row in pending] == [row['market_value'] for row in saved]
        assert all(row['status'] == 'pending' for row in pending)
        assert Decimal(c.get(f"/api/portfolios/1/fixed-income/lots/{created['id']}").json()['current_value']) == 1000
        assert c.get('/api/portfolios/1/performance', params={'asset_id': created['asset_id']}).json()[-1]['market_value'] == 1000
    assert c.delete(movement_url).status_code == 204
    with monkeypatch.context() as guard:
        guard.setattr(fixed_income, '_lot_valuation', lambda *_: pytest.fail('GET replayed deleted lot'))
        assert c.get(overview_url).json()['positions'][0]['display_value'] == 1000
        assert [row['market_value'] for row in c.get(history_url).json()] == [row['market_value'] for row in saved]
    assert c.post('/api/portfolios/1/consolidate').status_code == 200
    assert c.get(overview_url).json()['positions'] == []


def test_fixed_income_suffix_reuses_checkpoint_and_leaves_other_lot_untouched(client, monkeypatch):
    from src import fixed_income_history
    from src.models import FixedIncomeSnapshot, FixedIncomeInvalidation
    c, engine = client
    start = date.today() - timedelta(days=6)
    payload = lot_payload(start_date=start.isoformat(), maturity_date=None,
                         day_count_basis='ACT_365', business_day_calendar='NONE')
    first = c.post('/api/portfolios/1/fixed-income/lots', json=payload).json()
    second = c.post('/api/portfolios/1/fixed-income/lots', json=payload).json()
    assert c.post('/api/portfolios/1/consolidate').json()['complete']
    boundary = start + timedelta(days=4)
    with Session(engine) as session:
        other_ids = list(session.scalars(select(FixedIncomeSnapshot.id).where(
            FixedIncomeSnapshot.lot_id == second['id']).order_by(FixedIncomeSnapshot.date)))
        prefix_ids = list(session.scalars(select(FixedIncomeSnapshot.id).where(
            FixedIncomeSnapshot.lot_id == first['id'], FixedIncomeSnapshot.date < boundary
        ).order_by(FixedIncomeSnapshot.date)))
    assert c.post(f"/api/portfolios/1/fixed-income/lots/{first['id']}/movements", json={
        'movement_type': 'PARTIAL_REDEMPTION', 'effective_date': boundary.isoformat(),
        'amount': '100', 'currency': 'BRL'}).status_code == 201
    with Session(engine) as session:
        dirty = list(session.scalars(select(FixedIncomeInvalidation)))
        assert [(row.lot_id, row.dirty_from) for row in dirty] == [(first['id'], boundary)]
    original = fixed_income_history.fixed_income_valuation
    calls = []
    def recorded(lot, movements, day, observations, *, initial_state=None):
        calls.append((lot.id, day, initial_state))
        return original(lot, movements, day, observations, initial_state=initial_state)
    monkeypatch.setattr(fixed_income_history, 'fixed_income_valuation', recorded)
    assert c.post('/api/portfolios/1/consolidate').json()['complete']
    assert [(lot_id, day) for lot_id, day, _ in calls] == [
        (first['id'], boundary + timedelta(days=offset)) for offset in range(3)]
    assert calls[0][2]['date'] == (boundary - timedelta(days=1)).isoformat()
    with Session(engine) as session:
        assert list(session.scalars(select(FixedIncomeSnapshot.id).where(
            FixedIncomeSnapshot.lot_id == second['id']).order_by(FixedIncomeSnapshot.date))) == other_ids
        assert list(session.scalars(select(FixedIncomeSnapshot.id).where(
            FixedIncomeSnapshot.lot_id == first['id'], FixedIncomeSnapshot.date < boundary
        ).order_by(FixedIncomeSnapshot.date))) == prefix_ids
        assert list(session.scalars(select(FixedIncomeInvalidation))) == []


def test_fixed_income_currency_projection_does_not_replay_or_change_snapshots(client, monkeypatch):
    from src import fixed_income_history
    from src.models import FixedIncomeSnapshot
    c, engine = client
    start = date.today() - timedelta(days=3)
    foreign = c.post('/api/portfolios/1/fixed-income/instruments/custom', json={
        'symbol': 'CANONICAL-USD', 'name': 'USD bond', 'asset_type': 'FIXED_INCOME', 'currency': 'USD'}).json()
    created = c.post('/api/portfolios/1/fixed-income/lots', json=lot_payload(
        instrument_id=foreign['id'], currency='USD', start_date=start.isoformat(),
        maturity_date=None, fixed_rate='0', day_count_basis='ACT_365', business_day_calendar='NONE')).json()
    with Session(engine) as session:
        for offset in range(4):
            for currency, rate in [('USD', 5), ('EUR', 10)]:
                session.add(ExchangeRate(currency=currency, rate_type='FX', rate_side='MARKET',
                    reference_date=start + timedelta(days=offset), rate=rate, source='test'))
        session.commit()
    assert c.post('/api/portfolios/1/consolidate').json()['complete']
    with Session(engine) as session:
        saved = [(row.id, row.accounting_currency, row.valuation, row.ledger_state)
                 for row in session.scalars(select(FixedIncomeSnapshot).order_by(FixedIncomeSnapshot.date))]
        assert all(row[1] == 'USD' for row in saved)
    monkeypatch.setattr(fixed_income_history, 'fixed_income_valuation',
                        lambda *_args, **_kwargs: pytest.fail('currency change replayed lot'))
    for currency, expected in [('BRL', 5000), ('USD', 1000), ('EUR', 500)]:
        assert c.put('/api/portfolios/1', json={'name': 'Savings', 'display_currency': currency}).status_code == 200
        assert c.get('/api/portfolios/1/overview').json()['summary']['total_value'] == expected
        assert c.get('/api/portfolios/1/history').json()[-1]['market_value'] == expected
        assert c.get('/api/portfolios/1/performance', params={'asset_id': created['asset_id']}).json()[-1]['market_value'] == expected
    with Session(engine) as session:
        assert [(row.id, row.accounting_currency, row.valuation, row.ledger_state)
                for row in session.scalars(select(FixedIncomeSnapshot).order_by(FixedIncomeSnapshot.date))] == saved


def test_benchmark_revision_invalidates_only_affected_lot_and_period(client, monkeypatch):
    from src.models import FixedIncomeInvalidation, FixedIncomeSnapshot
    c, engine = client
    start = date.today() - timedelta(days=7)
    reference = next(start + timedelta(days=offset) for offset in range(2, 7)
                     if (start + timedelta(days=offset)).weekday() < 5)
    with Session(engine) as session:
        mapping = BenchmarkProviderMapping(benchmark_id=1, provider='test', series_id='checkpoint-cdi',
                                           active=True, is_primary=True)
        session.add(mapping)
        session.flush()
        for offset in range(7):
            session.add(BenchmarkObservation(benchmark_id=1, provider_mapping_id=mapping.id,
                reference_date=start + timedelta(days=offset), value=Decimal('.04'),
                source='test', retrieved_at=datetime.now(timezone.utc)))
        session.commit()
    payload = lot_payload(start_date=start.isoformat(), maturity_date=None,
                         business_day_calendar='NONE')
    indexed = c.post('/api/portfolios/1/fixed-income/lots', json={**payload,
        'fixed_rate': None, 'yield_structure': 'BENCHMARK_MULTIPLE',
        'benchmark_id': 1, 'benchmark_multiplier': '1'}).json()
    fixed = c.post('/api/portfolios/1/fixed-income/lots', json=payload).json()
    assert c.post('/api/portfolios/1/consolidate').json()['complete']
    with Session(engine) as session:
        other_ids = list(session.scalars(select(FixedIncomeSnapshot.id).where(
            FixedIncomeSnapshot.lot_id == fixed['id']).order_by(FixedIncomeSnapshot.date)))
        row = session.scalar(select(BenchmarkObservation).where(
            BenchmarkObservation.reference_date == reference))
        row.value = Decimal('.05')
        session.flush()
        dirty = list(session.scalars(select(FixedIncomeInvalidation)))
        assert [(row.lot_id, row.dirty_from) for row in dirty] == [
            (indexed['id'], reference + timedelta(days=1))]
        session.commit()
    assert c.post('/api/portfolios/1/consolidate').json()['complete']
    with Session(engine) as session:
        assert list(session.scalars(select(FixedIncomeSnapshot.id).where(
            FixedIncomeSnapshot.lot_id == fixed['id']).order_by(FixedIncomeSnapshot.date))) == other_ids


def test_today_lot_first_consolidation_builds_current_value(client, monkeypatch):
    c, _ = client
    from src import fixed_income_history
    created = c.post('/api/portfolios/1/fixed-income/lots', json=lot_payload(
        start_date=date.today().isoformat(), maturity_date=None, fixed_rate='0',
        day_count_basis='ACT_365', business_day_calendar='NONE')).json()
    assert c.get('/api/portfolios/1/overview').json()['summary']['history_status'] == 'pending'
    assert c.post('/api/portfolios/1/consolidate').json()['complete']
    monkeypatch.setattr(fixed_income_history, 'fixed_income_valuation',
                        lambda *_args, **_kwargs: pytest.fail('GET replayed new lot'))
    overview = c.get('/api/portfolios/1/overview').json()
    assert overview['summary']['history_status'] == 'complete'
    assert overview['summary']['total_value'] == 1000
    assert c.get(f"/api/portfolios/1/fixed-income/lots/{created['id']}").json()['valuation_status'] == 'complete'
    assert c.get('/api/portfolios/1/history').json() == []


def test_new_benchmark_observations_are_consumed_by_extension(client, monkeypatch):
    from src import benchmarks, consolidation
    from src.models import FixedIncomeInvalidation
    c, engine = client
    today = date.today()
    start = today - timedelta(days=7)
    with Session(engine) as session:
        session.add(BenchmarkProviderMapping(benchmark_id=1, provider='test',
            series_id='extension-cdi', active=True, is_primary=True))
        session.commit()

    def fetch(mapping, first, last):
        return [{'reference_date': first + timedelta(days=i), 'value': '.04',
                 'source': 'test', 'retrieved_at': datetime.now(timezone.utc)}
                for i in range((last - first).days + 1)]

    monkeypatch.setattr(benchmarks, 'fetch_benchmark_history', fetch)
    c.post('/api/portfolios/1/fixed-income/lots', json=lot_payload(
        start_date=start.isoformat(), maturity_date=None, fixed_rate=None,
        yield_structure='BENCHMARK_MULTIPLE', benchmark_id=1,
        benchmark_multiplier='1', business_day_calendar='NONE'))

    class Yesterday(date):
        @classmethod
        def today(cls):
            return today - timedelta(days=1)

    with monkeypatch.context() as clock:
        clock.setattr(consolidation, 'date', Yesterday)
        assert c.post('/api/portfolios/1/consolidate').json()['complete']
    result = c.post('/api/portfolios/1/consolidate').json()
    assert result['complete'], result
    with Session(engine) as session:
        assert list(session.scalars(select(FixedIncomeInvalidation))) == []
    assert c.get('/api/portfolios/1/overview').json()['summary']['history_status'] == 'complete'


@pytest.mark.parametrize('offset', [-2, 2, 8])
def test_moving_consolidated_lot_start_replaces_the_old_range_only_after_update(client, offset):
    from src.models import FixedIncomeSnapshot
    c, engine = client
    start = date.today() - timedelta(days=4)
    moved = start + timedelta(days=offset)
    created = c.post('/api/portfolios/1/fixed-income/lots', json=lot_payload(
        start_date=start.isoformat(), maturity_date=None, fixed_rate='0',
        day_count_basis='ACT_365', business_day_calendar='NONE')).json()
    assert c.post('/api/portfolios/1/consolidate').json()['complete']
    saved = c.get('/api/portfolios/1/history').json()
    url = f"/api/portfolios/1/fixed-income/lots/{created['id']}/movements/{created['movements'][0]['id']}"
    assert c.put(url, json={'movement_type': 'INITIAL_INVESTMENT',
        'effective_date': moved.isoformat(), 'amount': '1500', 'currency': 'BRL'}).status_code == 200
    assert c.get('/api/portfolios/1/overview').json()['summary']['total_value'] == 1000
    assert [row['market_value'] for row in c.get('/api/portfolios/1/history').json()] == [row['market_value'] for row in saved]
    assert c.post('/api/portfolios/1/consolidate').json()['complete']
    history = c.get('/api/portfolios/1/history').json()
    assert all(row['date'] >= moved.isoformat() and row['market_value'] == 1500 for row in history)
    assert len(history) == max(0, (date.today() - moved).days)
    with Session(engine) as session:
        assert all(day >= moved for day in session.scalars(select(FixedIncomeSnapshot.date)))


def test_active_benchmark_catalog_and_fixed_income_search(client):
    c, engine = client
    with Session(engine) as session:
        session.add(Benchmark(code='RETIRED', name='Retired', kind='INTEREST_RATE', frequency='DAILY',
                              value_type='RATE', unit='PERCENT_PER_DAY', status='INACTIVE'))
        session.commit()
    response = c.get('/api/benchmarks')
    assert response.status_code == 200
    assert response.json() == [{'id': 1, 'code': 'CDI', 'name': 'CDI'}]
    search = c.get('/api/instruments/search', params={'q': 'CDB', 'category': 'FIXED_INCOME', 'portfolio_id': 1})
    assert search.status_code == 200
    assert len(search.json()) == 1
    assert search.json()[0]['asset_type'] == 'FIXED_INCOME'


def test_private_fixed_income_instrument_is_scoped_to_portfolio(client):
    c, _ = client
    other = c.post('/api/portfolios', json={'name': 'Other'}).json()['id']
    payload = {'symbol': 'PRIVATE-BOND', 'name': 'Private bond',
               'asset_type': 'FIXED_INCOME', 'currency': 'USD'}
    assert c.post('/api/instruments/custom', json=payload).status_code == 422
    created = c.post('/api/portfolios/1/fixed-income/instruments/custom', json=payload)
    assert created.status_code == 201, created.text
    assert c.get('/api/instruments/search', params={
        'q': 'PRIVATE-BOND', 'category': 'FIXED_INCOME', 'portfolio_id': 1}).json()[0]['instrument_id'] == created.json()['id']
    assert c.get('/api/instruments/search', params={
        'q': 'PRIVATE-BOND', 'category': 'FIXED_INCOME', 'portfolio_id': other}).json() == []
    assert c.post(f'/api/portfolios/{other}/fixed-income/lots', json=lot_payload(
        instrument_id=created.json()['id'], product_type='PRIVATE-BOND')).status_code == 422


def test_canonical_product_defaults_are_snapshotted_into_lots(client):
    from src.instrument_catalog import seed_catalog

    c, engine = client
    with Session(engine) as session:
        seed_catalog(session)
        session.commit()
    products = c.get('/api/fixed-income/products').json()
    assert {row['symbol'] for row in products} == {'CDB', 'LCI', 'LCA'}
    cdb = next(row for row in products if row['symbol'] == 'CDB')
    assert cdb['default_currency'] == 'BRL'
    payload = lot_payload(instrument_id=cdb['instrument_id'])
    for field in ('currency', 'day_count_basis', 'compounding', 'business_day_calendar', 'benchmark_lag_months'):
        del payload[field]
    first = c.post('/api/portfolios/1/fixed-income/lots', json=payload)
    assert first.status_code == 201, first.text
    assert first.json()['day_count_basis'] == 'BUS_252'
    with Session(engine) as session:
        session.get(FixedIncomeProduct, cdb['instrument_id']).day_count_basis = 'ACT_365'
        session.commit()
    second = c.post('/api/portfolios/1/fixed-income/lots', json={
        **payload, 'issuer': 'Another bank', 'fixed_rate': '0.15'})
    assert second.status_code == 201, second.text
    assert c.get(f"/api/portfolios/1/fixed-income/lots/{first.json()['id']}").json()['day_count_basis'] == 'BUS_252'
    assert second.json()['day_count_basis'] == 'ACT_365'
    assert first.json()['asset_id'] == second.json()['asset_id']
    assert first.json()['issuer'] != second.json()['issuer']
    override = c.post('/api/portfolios/1/fixed-income/lots', json={
        **payload, 'currency': 'USD', 'day_count_basis': 'ACT_360'})
    assert override.status_code == 201, override.text
    assert override.json()['currency'] == 'USD' and override.json()['day_count_basis'] == 'ACT_360'


def test_independent_lots_and_authoritative_opening_movements(client):
    c, engine = client
    start = date.today() - timedelta(days=3)
    first = c.post('/api/portfolios/1/fixed-income/lots', json=lot_payload(
        start_date=start.isoformat(), maturity_date=None, day_count_basis='ACT_365',
        business_day_calendar='NONE')).json()
    second = c.post('/api/portfolios/1/fixed-income/lots', json=lot_payload(
        start_date=(start + timedelta(days=1)).isoformat(), maturity_date=None,
        day_count_basis='ACT_365', business_day_calendar='NONE',
        fixed_rate='0.13', opening_amount='2000')).json()
    assert first['id'] != second['id']
    assert first['asset_id'] == second['asset_id']
    assert first['instrument_id'] == second['instrument_id'] == 1
    assert first['instrument_symbol'] == 'CDB-ISSUER'
    assert first['instrument_name'] == 'Issuer CDB'
    assert Decimal(first['opening_amount']) == Decimal('1000.00')
    assert first['current_value'] is None and first['profitability'] is None
    assert first['current_value'] is None and first['valuation_status'] == 'pending'
    assert first['business_day_calendar'] == 'NONE' and first['benchmark_lag_months'] == 0
    assert first['movements'][0]['amount'] == '1000.000000000000'
    assert [x['id'] for x in c.get('/api/portfolios/1/fixed-income/lots').json()] == [first['id'], second['id']]
    assert c.get(f"/api/portfolios/1/fixed-income/lots/{first['id']}").json()['fixed_rate'] == '0.120000000000'
    with Session(engine) as session:
        assert session.query(FixedIncomeLot).count() == 2
        assert session.query(FixedIncomeMovement).count() == 2
    assert c.post('/api/portfolios/1/consolidate').status_code == 200
    overview = c.get('/api/portfolios/1/overview').json()
    assert overview['fixed_income']['valuation_status'] == 'complete'
    assert overview['summary']['total_value'] > 3000
    assert overview['summary']['total_gain'] > 0
    assert overview['summary']['gross_income'] == 0
    assert len(overview['fixed_income']['positions']) == 1
    assert len(overview['fixed_income']['positions'][0]['lots']) == 2
    consolidation = c.post('/api/portfolios/1/consolidate').json()
    assert consolidation['complete'] is True
    history = c.get('/api/portfolios/1/history').json()
    assert history and all(row['status'] == 'complete' for row in history)
    assert history[-1]['market_value'] > 3000


def test_future_lot_does_not_make_active_position_incomplete(client):
    c, _ = client
    today = date.today()
    active = c.post('/api/portfolios/1/fixed-income/lots', json=lot_payload(
        start_date=(today - timedelta(days=2)).isoformat(), maturity_date=None,
        fixed_rate='0', day_count_basis='ACT_365', business_day_calendar='NONE'))
    assert active.status_code == 201, active.text
    future = c.post('/api/portfolios/1/fixed-income/lots', json=lot_payload(
        start_date=(today + timedelta(days=2)).isoformat(), maturity_date=None,
        fixed_rate='0', day_count_basis='ACT_365', business_day_calendar='NONE',
        broker='Future Broker'))
    assert future.status_code == 201, future.text

    assert c.post('/api/portfolios/1/consolidate').status_code == 200
    overview = c.get('/api/portfolios/1/overview').json()
    assert overview['fixed_income']['valuation_status'] == 'complete'
    assert overview['summary']['total_value'] == 1000
    assert len(overview['fixed_income']['positions'][0]['lots']) == 1
    assert overview['fixed_income']['positions'][0]['lots'][0]['id'] == active.json()['id']
    assert overview['positions'][0]['broker'] == 'Broker'
    assert c.get(f"/api/portfolios/1/fixed-income/lots/{future.json()['id']}").json()['valuation_status'] == 'before_start'


@pytest.mark.parametrize('changes', [
    {'fixed_rate': None},
    {'fixed_rate': '0.12', 'benchmark_id': 1},
    {'yield_structure': 'BENCHMARK_MULTIPLE', 'fixed_rate': None, 'benchmark_multiplier': '1.10'},
    {'yield_structure': 'BENCHMARK_SPREAD', 'fixed_rate': None, 'benchmark_id': 1},
    {'yield_structure': 'BENCHMARK_MULTIPLE', 'fixed_rate': None,
     'benchmark_id': 999, 'benchmark_multiplier': '1.10'},
    {'benchmark_lag_months': -1},
    {'maturity_date': '2023-01-01'},
    {'instrument_id': 999},
])
def test_invalid_contracts_are_rejected(client, changes):
    c, engine = client
    response = c.post('/api/portfolios/1/fixed-income/lots', json=lot_payload(**changes))
    assert response.status_code == 422, response.text
    with Session(engine) as session:
        assert session.query(FixedIncomeLot).count() == 0


def test_benchmark_terms_and_movements_are_preserved(client):
    c, engine = client
    response = c.post('/api/portfolios/1/fixed-income/lots', json=lot_payload(
        product_type='LCI', yield_structure='BENCHMARK_MULTIPLE', fixed_rate=None,
        benchmark_id=1, benchmark_multiplier='1.10'))
    assert response.status_code == 201, response.text
    lot = response.json()
    assert lot['benchmark_id'] == 1 and Decimal(lot['benchmark_multiplier']) == Decimal('1.10')
    assert lot['benchmark_code'] == 'CDI'
    movement = c.post(f"/api/portfolios/1/fixed-income/lots/{lot['id']}/movements", json={
        'movement_type': 'ADDITIONAL_INVESTMENT', 'effective_date': '2024-03-01',
        'amount': '250.50', 'currency': 'BRL',
    })
    assert movement.status_code == 201, movement.text
    assert [m['movement_type'] for m in c.get(
        f"/api/portfolios/1/fixed-income/lots/{lot['id']}/movements").json()] == [
            'INITIAL_INVESTMENT', 'ADDITIONAL_INVESTMENT']
    assert c.post(f"/api/portfolios/1/fixed-income/lots/{lot['id']}/movements", json={
        'movement_type': 'ADDITIONAL_INVESTMENT', 'effective_date': '2024-03-01',
        'amount': '1', 'currency': 'USD'}).status_code == 422
    assert c.post(f"/api/portfolios/1/fixed-income/lots/{lot['id']}/movements", json={
        'movement_type': 'INITIAL_INVESTMENT', 'effective_date': '2024-03-01',
        'amount': '1', 'currency': 'BRL'}).status_code == 422
    with Session(engine) as session:
        assert session.scalar(select(Benchmark).where(Benchmark.code == 'CDI')) is not None
        assert session.query(Benchmark).count() == 1


def test_spread_contract_and_foreign_currency_are_independent_of_benchmark(client):
    c, engine = client
    response = c.post('/api/portfolios/1/fixed-income/instruments/custom', json={
        'symbol': 'FOREIGN-BOND', 'name': 'Foreign bond',
        'asset_type': 'FIXED_INCOME', 'currency': 'USD'})
    assert response.status_code == 201, response.text
    instrument_id = response.json()['id']
    response = c.post('/api/portfolios/1/fixed-income/lots', json=lot_payload(
        instrument_id=instrument_id, product_type='LCA', currency='USD',
        yield_structure='BENCHMARK_SPREAD', fixed_rate=None, benchmark_id=1,
        benchmark_spread='0.06'))
    assert response.status_code == 201, response.text
    lot = response.json()
    assert lot['currency'] == 'USD' and lot['benchmark_id'] == 1
    assert Decimal(lot['benchmark_spread']) == Decimal('0.06')
    assert lot['current_value'] is None
    assert c.post('/api/portfolios/1/transactions', json={
        'trade_date': '2024-01-02', 'settlement_date': '2024-01-02',
        'type': 'Buy', 'asset': 'FOREIGN-BOND', 'instrument_id': instrument_id,
        'broker': 'Broker', 'quantity': 1, 'price': 1000, 'transaction_currency': 'USD',
    }).status_code == 422
    with Session(engine) as session:
        assert session.query(Benchmark).count() == 1


def test_portfolio_history_requires_canonical_positions_after_lot_start(client):
    c, engine = client
    from datetime import date

    with Session(engine) as session:
        for day in (date(2024, 1, 1), date(2024, 1, 2)):
            session.add(PortfolioSnapshot(
                portfolio_id=1, date=day, reporting_currency='BRL',
                remaining_acquisition_cost=Decimal('80'), market_value=Decimal('100'),
                realized_gain=Decimal('0'), unrealized_gain=Decimal('20'),
                gross_income=Decimal('0'), total_gain=Decimal('20'),
                daily_return_pct=Decimal('1'), cumulative_return_pct=Decimal('25'),
                status='complete', return_factor=Decimal('1.01'),
            ))
        session.commit()

    response = c.post('/api/portfolios/1/fixed-income/lots', json=lot_payload())
    assert response.status_code == 201, response.text
    # A legacy aggregate snapshot alone cannot certify canonical positions.
    assert c.get('/api/portfolios/1/history').json() == []


def test_current_lot_api_and_history_use_accrued_value_without_rewriting_sources(client):
    c, engine = client
    start = date.today() - timedelta(days=3)
    payload = lot_payload(start_date=start.isoformat(), maturity_date=None,
                          day_count_basis='ACT_365', business_day_calendar='NONE')
    created = c.post('/api/portfolios/1/fixed-income/lots', json=payload).json()
    lot_id = created['id']
    assert c.post('/api/portfolios/1/consolidate').status_code == 200
    current = c.get(f'/api/portfolios/1/fixed-income/lots/{lot_id}').json()
    assert current['valuation_status'] == 'complete'
    assert Decimal(current['current_value']) > 1000
    assert Decimal(str(current['valuation']['outstanding_principal'])) == 1000
    opening = c.get(f'/api/portfolios/1/fixed-income/lots/{lot_id}',
                    params={'as_of': start.isoformat()}).json()
    assert Decimal(opening['current_value']) == 1000
    assert opening['valuation']['valuation_date'] == start.isoformat()
    first = c.post('/api/portfolios/1/consolidate').json()
    assert first['complete'] is True
    history = c.get('/api/portfolios/1/history').json()
    assert len(history) == 3
    assert history[0]['market_value'] == 1000
    assert history[-1]['market_value'] > 1000
    performance = c.get('/api/portfolios/1/performance',
                        params={'asset_id': created['asset_id']}).json()
    assert performance[0]['quantity'] is None
    assert performance[0]['cumulative_return_pct'] == 0
    assert performance[-1]['cumulative_return_pct'] > 0
    c.post('/api/portfolios/1/consolidate')
    assert c.get('/api/portfolios/1/history').json() == history
    with Session(engine) as session:
        assert session.get(FixedIncomeLot, lot_id).fixed_rate == Decimal('0.12')
        assert session.query(FixedIncomeMovement).filter_by(lot_id=lot_id).count() == 1


def test_future_dirty_movement_preserves_finalized_history(client):
    c, _ = client
    start = date.today() - timedelta(days=3)
    created = c.post('/api/portfolios/1/fixed-income/lots', json=lot_payload(
        start_date=start.isoformat(), maturity_date=None,
        day_count_basis='ACT_365', business_day_calendar='NONE')).json()
    assert c.post('/api/portfolios/1/consolidate').json()['complete']
    history = c.get('/api/portfolios/1/history').json()
    assert all(row['status'] == 'complete' for row in history)

    response = c.post(f"/api/portfolios/1/fixed-income/lots/{created['id']}/movements", json={
        'movement_type': 'PARTIAL_REDEMPTION',
        'effective_date': date.today().isoformat(),
        'amount': '100', 'currency': 'BRL',
    })
    assert response.status_code == 201, response.text
    assert c.get('/api/portfolios/1/history').json() == history


@pytest.mark.parametrize('lot_currency,display_currency,expected', [
    ('BRL', 'USD', 200), ('USD', 'BRL', 5000), ('USD', 'EUR', 500),
])
def test_fixed_income_only_consolidation_fetches_required_fx(
        client, monkeypatch, lot_currency, display_currency, expected):
    from src import consolidation

    c, engine = client
    start = date.today() - timedelta(days=3)
    with Session(engine) as session:
        session.get(Portfolio, 1).display_currency = display_currency
        session.get(Instrument, 1).currency = lot_currency
        session.commit()
    created = c.post('/api/portfolios/1/fixed-income/lots', json=lot_payload(
        currency=lot_currency, start_date=start.isoformat(), maturity_date=None,
        fixed_rate='0', day_count_basis='ACT_365')).json()
    calls = []

    def backfill(session, currencies, rate_types, first, last):
        calls.extend(currencies)
        assert rate_types == ['FX']
        assert (first, last) == (start, date.today())
        for currency in currencies:
            for offset in range((last - first).days + 1):
                session.add(ExchangeRate(
                    currency=currency, rate_type='FX', rate_side='MARKET',
                    reference_date=first + timedelta(days=offset),
                    rate=Decimal('5' if currency == 'USD' else '10'), source='test'))
        session.flush()

    monkeypatch.setattr(consolidation, 'backfill_rates', backfill)
    result = c.post('/api/portfolios/1/consolidate')
    assert result.status_code == 200, result.text
    assert result.json()['complete'], result.text
    assert set(calls) == {lot_currency, display_currency} - {'BRL'}
    assert c.get('/api/portfolios/1/overview').json()['summary']['total_value'] == expected
    history = c.get('/api/portfolios/1/history').json()
    assert len(history) == 3
    assert all(row['status'] == 'complete' and row['market_value'] == expected for row in history)
    with Session(engine) as session:
        stored = session.get(FixedIncomeLot, created['id'])
        assert stored.currency == lot_currency
        assert stored.movements[0].amount == 1000


def test_missing_cdi_and_fx_keep_current_value_unknown(client, monkeypatch):
    monkeypatch.setattr('src.consolidation.backfill_rates', lambda *args: None)
    c, engine = client
    start = date.today() - timedelta(days=5)
    benchmark = c.post('/api/portfolios/1/fixed-income/lots', json=lot_payload(
        start_date=start.isoformat(), maturity_date=None, yield_structure='BENCHMARK_MULTIPLE',
        fixed_rate=None, benchmark_id=1, benchmark_multiplier='1.10')).json()
    assert c.post('/api/portfolios/1/consolidate').status_code == 200
    overview = c.get('/api/portfolios/1/overview').json()
    assert overview['summary']['total_value'] is None
    assert overview['fixed_income']['lots'][0]['status'] == 'missing_benchmark'
    assert overview['fixed_income']['lots'][0]['gross_accrued_value'] is None
    with Session(engine) as session:
        assert session.query(Benchmark).count() == 1
    foreign = c.post('/api/portfolios/1/fixed-income/instruments/custom', json={
        'symbol': 'USD-TEST', 'name': 'USD test', 'asset_type': 'FIXED_INCOME', 'currency': 'USD'}).json()
    usd = c.post('/api/portfolios/1/fixed-income/lots', json=lot_payload(
        instrument_id=foreign['id'], product_type='CDB', currency='USD',
        start_date=start.isoformat(), maturity_date=None)).json()
    assert c.post('/api/portfolios/1/consolidate').status_code == 200
    state = c.get(f"/api/portfolios/1/fixed-income/lots/{usd['id']}").json()
    assert state['valuation_status'] == 'missing_fx'
    assert state['current_value'] is not None
    assert state['valuation']['gross_accrued_value'] is not None
    consolidation = c.post('/api/portfolios/1/consolidate').json()
    assert consolidation['history_status'] == 'incomplete'
    history = c.get('/api/portfolios/1/history').json()
    assert any(row['status'] == 'incomplete' and row['market_value'] is None for row in history)


def test_missing_historical_fx_keeps_later_returns_incomplete(client, monkeypatch):
    monkeypatch.setattr('src.consolidation.backfill_rates', lambda *args: None)
    c, engine = client
    start = date.today() - timedelta(days=3)
    instrument = c.post('/api/portfolios/1/fixed-income/instruments/custom', json={
        'symbol': 'USD-GAP', 'name': 'USD gap', 'asset_type': 'FIXED_INCOME',
        'currency': 'USD',
    }).json()
    created = c.post('/api/portfolios/1/fixed-income/lots', json=lot_payload(
        instrument_id=instrument['id'], product_type='CDB', currency='USD',
        start_date=start.isoformat(), maturity_date=None,
        day_count_basis='ACT_365', business_day_calendar='NONE')).json()
    with Session(engine) as session:
        for offset in (1, 2, 3):
            session.add(ExchangeRate(
                currency='USD', rate_type='FX', rate_side='MARKET',
                reference_date=start + timedelta(days=offset),
                rate=Decimal('5'), source='test',
            ))
        session.commit()

    assert c.post('/api/portfolios/1/consolidate').json()['history_status'] == 'incomplete'
    history = c.get('/api/portfolios/1/history').json()
    performance = c.get('/api/portfolios/1/performance',
                        params={'asset_id': created['asset_id']}).json()
    assert history[0]['status'] == performance[0]['status'] == 'incomplete'
    assert history[1]['market_value'] is not None
    assert performance[1]['market_value'] is not None
    assert history[1]['status'] == performance[1]['status'] == 'incomplete_history'
    assert history[1]['cumulative_return_pct'] is None
    assert performance[1]['cumulative_return_pct'] is None


def test_partial_redemption_is_lot_scoped_and_fx_converts_display_only(client):
    c, engine = client
    start = date.today() - timedelta(days=3)
    instrument = c.post('/api/portfolios/1/fixed-income/instruments/custom', json={
        'symbol': 'USD-LOTS', 'name': 'USD lots', 'asset_type': 'FIXED_INCOME', 'currency': 'USD'}).json()
    payload = lot_payload(instrument_id=instrument['id'], product_type='CDB', currency='USD',
                          start_date=start.isoformat(), maturity_date=None,
                          day_count_basis='ACT_365', business_day_calendar='NONE')
    first = c.post('/api/portfolios/1/fixed-income/lots', json=payload).json()
    second = c.post('/api/portfolios/1/fixed-income/lots', json=payload).json()
    movement = c.post(f"/api/portfolios/1/fixed-income/lots/{first['id']}/movements", json={
        'movement_type': 'PARTIAL_REDEMPTION',
        'effective_date': (start + timedelta(days=1)).isoformat(),
        'amount': '400', 'currency': 'USD'}).json()
    assert movement['lot_id'] == first['id']
    with Session(engine) as session:
        for offset in range(4):
            session.add(ExchangeRate(currency='USD', rate_type='FX', rate_side='MARKET',
                                     reference_date=start + timedelta(days=offset),
                                     rate=Decimal('5'), source='test'))
        session.commit()
    assert c.post('/api/portfolios/1/consolidate').status_code == 200
    overview = c.get('/api/portfolios/1/overview').json()
    assert overview['fixed_income']['valuation_status'] == 'complete'
    lots = overview['fixed_income']['lots']
    assert len(lots) == 2
    assert lots[0]['outstanding_principal'] < 1000
    assert lots[1]['outstanding_principal'] == 1000
    assert lots[0]['currency'] == lots[1]['currency'] == 'USD'
    assert abs(Decimal(str(lots[0]['display_value'])) -
               Decimal(str(lots[0]['gross_accrued_value'])) * 5) < Decimal('0.000001')
    assert overview['summary']['total_value'] == overview['fixed_income']['positions'][0]['display_value']
    history = c.post('/api/portfolios/1/consolidate').json()
    assert history['complete'] is True
    assert all(row['status'] == 'complete' for row in c.get('/api/portfolios/1/history').json())
    with Session(engine) as session:
        assert session.get(FixedIncomeLot, first['id']).currency == 'USD'
        assert session.get(FixedIncomeMovement, movement['id']).amount == Decimal('400')


def test_cdi_valuation_reads_only_canonical_stored_observations(client, monkeypatch):
    from src import benchmarks
    from src.fixed_income import _lot_valuation

    c, engine = client
    created = c.post('/api/portfolios/1/fixed-income/lots', json=lot_payload(
        yield_structure='BENCHMARK_MULTIPLE', fixed_rate=None, benchmark_id=1,
        benchmark_multiplier='1.10', business_day_calendar='NONE')).json()
    monkeypatch.setattr(benchmarks, 'fetch_benchmark_history',
                        lambda *_: pytest.fail('valuation fetched benchmark data'))
    with Session(engine) as session:
        lot = session.get(FixedIncomeLot, created['id'])
        missing = _lot_valuation(session, lot, lot.movements, date(2024, 1, 4))
        assert missing['status'] == 'missing_benchmark'
        mapping = BenchmarkProviderMapping(benchmark_id=1, provider='test', series_id='cdi-test',
                                           active=True, is_primary=True)
        session.add(mapping)
        session.flush()
        for day in (date(2024, 1, 2), date(2024, 1, 3)):
            session.add(BenchmarkObservation(
                benchmark_id=1, provider_mapping_id=mapping.id, reference_date=day,
                value=Decimal('0.04'), source='test',
                retrieved_at=datetime(2024, 1, 5, tzinfo=timezone.utc)))
        session.flush()
        valued = _lot_valuation(session, lot, lot.movements, date(2024, 1, 4))
        assert valued['status'] == 'complete'
        assert valued['gross_accrued_value'] == Decimal('1000') * Decimal('1.00044') ** 2
        assert valued['benchmark_start'] == date(2024, 1, 2)
        assert valued['benchmark_end'] == date(2024, 1, 3)


def test_movement_edit_delete_revalidates_later_redemptions_and_history(client):
    c, engine = client
    start = date.today() - timedelta(days=4)
    created = c.post('/api/portfolios/1/fixed-income/lots', json=lot_payload(
        start_date=start.isoformat(), maturity_date=None, fixed_rate='0',
        day_count_basis='ACT_365', business_day_calendar='NONE')).json()
    base = f"/api/portfolios/1/fixed-income/lots/{created['id']}/movements"
    opening = created['movements'][0]
    first = c.post(base, json={'movement_type': 'PARTIAL_REDEMPTION',
        'effective_date': (start + timedelta(days=1)).isoformat(),
        'amount': '400', 'currency': 'BRL'}).json()
    second = c.post(base, json={'movement_type': 'PARTIAL_REDEMPTION',
        'effective_date': (start + timedelta(days=2)).isoformat(),
        'amount': '500', 'currency': 'BRL'}).json()
    assert c.post('/api/portfolios/1/consolidate').json()['complete']
    before = c.get('/api/portfolios/1/history').json()
    assert before[0]['market_value'] == 1000
    assert before[1]['market_value'] == 600
    assert before[2]['market_value'] == 100

    opening_url = f'{base}/{opening["id"]}'
    invalid = c.put(opening_url, json={'movement_type': 'INITIAL_INVESTMENT',
        'effective_date': start.isoformat(), 'amount': '500', 'currency': 'BRL'})
    assert invalid.status_code == 422
    assert str(second['id']) in invalid.text
    assert c.get(base).json()[0]['amount'] == opening['amount']
    assert c.delete(opening_url).status_code == 422

    assert c.delete(f'{base}/{first["id"]}').status_code == 204
    assert [row['id'] for row in c.get(base).json()] == [opening['id'], second['id']]
    lot = c.get(f"/api/portfolios/1/fixed-income/lots/{created['id']}").json()
    assert Decimal(lot['valuation']['outstanding_principal']) == 100
    assert lot['valuation']['pending'] is True
    after = c.get('/api/portfolios/1/history').json()
    assert after[0]['status'] == 'complete'
    assert any(row['status'] != 'complete' for row in after[1:])
    position_pending = c.get('/api/portfolios/1/performance', params={
        'asset_id': created['asset_id']}).json()
    assert position_pending[1]['status'] == 'pending'
    with Session(engine) as session:
        assert session.get(Portfolio, 1).dirty_from == (start + timedelta(days=1))
    assert c.post('/api/portfolios/1/consolidate').status_code == 200
    updated = c.get('/api/portfolios/1/history').json()
    assert all(row['status'] == 'complete' for row in updated)
    assert updated[1]['market_value'] == 1000
    assert updated[2]['market_value'] == 500


def test_full_redemption_is_valued_and_closed_lot_rejects_more_movements(client):
    c, _ = client
    start = date.today() - timedelta(days=3)
    created = c.post('/api/portfolios/1/fixed-income/lots', json=lot_payload(
        start_date=start.isoformat(), maturity_date=None, fixed_rate='0',
        day_count_basis='ACT_365', business_day_calendar='NONE')).json()
    base = f"/api/portfolios/1/fixed-income/lots/{created['id']}/movements"
    partial = c.post(base, json={'movement_type': 'PARTIAL_REDEMPTION',
        'effective_date': (start + timedelta(days=1)).isoformat(),
        'amount': '550', 'currency': 'BRL'})
    assert partial.status_code == 201, partial.text
    full = c.post(base, json={'movement_type': 'FULL_REDEMPTION',
        'effective_date': (start + timedelta(days=2)).isoformat(), 'currency': 'BRL'})
    assert full.status_code == 201, full.text
    assert Decimal(full.json()['amount']) == 450
    assert c.post(base, json={'movement_type': 'PARTIAL_REDEMPTION',
        'effective_date': date.today().isoformat(), 'amount': '1', 'currency': 'BRL'}).status_code == 422
    assert c.put(f"{base}/{partial.json()['id']}", json={
        'movement_type': 'PARTIAL_REDEMPTION',
        'effective_date': (start + timedelta(days=1)).isoformat(),
        'amount': '600', 'currency': 'BRL'}).status_code == 422
    assert c.post('/api/portfolios/1/consolidate').status_code == 200
    lot = c.get(f"/api/portfolios/1/fixed-income/lots/{created['id']}").json()
    assert lot['valuation']['gross_accrued_value'] == 0
    assert lot['valuation']['realized_gain'] == 0


def test_consolidation_populates_canonical_benchmarks_and_inspection_reports_coverage(client, monkeypatch):
    from src import benchmarks, consolidation, position_reporting
    from src.api import routes

    class ValuationDay(date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 29)  # Tuesday: today's CDI is not published.

    for module in (benchmarks, consolidation, position_reporting, routes):
        monkeypatch.setattr(module, 'date', ValuationDay)

    c, engine = client
    start = ValuationDay.today() - timedelta(days=6)
    with Session(engine) as session:
        ipca = Benchmark(code='IPCA', name='IPCA', kind='INFLATION', frequency='MONTHLY',
                         value_type='CHANGE', unit='PERCENT_PER_MONTH', status='ACTIVE')
        session.add(ipca)
        session.flush()
        session.add_all([
            BenchmarkProviderMapping(benchmark_id=1, provider='bcb_sgs', series_id='12',
                                     active=True, is_primary=True),
            BenchmarkProviderMapping(benchmark_id=ipca.id, provider='bcb_sgs', series_id='433',
                                     active=True, is_primary=True),
        ])
        session.commit()

    for changes in ({'yield_structure': 'BENCHMARK_MULTIPLE', 'benchmark_id': 1,
                     'benchmark_multiplier': '1.10'},
                    {'yield_structure': 'BENCHMARK_SPREAD', 'benchmark_id': 2,
                     'benchmark_spread': '0.06'}):
        response = c.post('/api/portfolios/1/fixed-income/lots', json=lot_payload(
            start_date=start.isoformat(), maturity_date=None, fixed_rate=None,
            business_day_calendar='NONE', **changes))
        assert response.status_code == 201, response.text

    assert c.get('/api/portfolios/1/overview').json()['fixed_income']['valuation_status'] == 'pending'
    calls = []

    def fetch(mapping, first, last):
        calls.append((mapping.series_id, first, last))
        days = []
        cursor = first
        while cursor <= last:
            if mapping.series_id == '433' and cursor.day == 1 or mapping.series_id == '12' and cursor.weekday() < 5:
                days.append({'reference_date': ValuationDay(cursor.year, cursor.month, cursor.day),
                             'value': Decimal('0.5' if mapping.series_id == '433' else '0.04'),
                             'source': 'bcb_sgs', 'retrieved_at': datetime.now(timezone.utc)})
            cursor += timedelta(days=1)
        return days

    monkeypatch.setattr(benchmarks, 'fetch_benchmark_history', fetch)
    result = c.post('/api/portfolios/1/consolidate')
    assert result.json()['complete'], result.text
    assert {series for series, _, _ in calls} == {'12', '433'}
    for code in ('CDI', 'IPCA'):
        response = c.get(f'/api/benchmarks/{code}/observations')
        assert response.status_code == 200, response.text
        data = response.json()
        assert data['count'] > 0 and data['earliest'] <= data['latest']
        assert all(row['source'] == 'bcb_sgs' and row['unit'] == data['unit'] for row in data['observations'])
    lots = c.get('/api/portfolios/1/fixed-income/lots',
                 params={'as_of': (ValuationDay.today() - timedelta(days=1)).isoformat()}).json()
    assert all(row['valuation_status'] == 'complete' for row in lots)
    current = c.get('/api/portfolios/1/fixed-income/lots').json()
    assert all(row['valuation_status'] == 'complete' for row in current)
    overview = c.get('/api/portfolios/1/overview').json()
    assert overview['fixed_income']['valuation_status'] == 'complete'
    assert overview['summary']['total_value'] is not None


def test_initial_investment_edit_keeps_contract_date_and_delete_removes_lot(client):
    c, engine = client
    start = date.today() - timedelta(days=3)
    earlier = start - timedelta(days=1)
    created = c.post('/api/portfolios/1/fixed-income/lots', json=lot_payload(
        start_date=start.isoformat(), maturity_date=None, fixed_rate='0')).json()
    opening = created['movements'][0]
    url = f"/api/portfolios/1/fixed-income/lots/{created['id']}/movements/{opening['id']}"
    response = c.put(url, json={'movement_type': 'INITIAL_INVESTMENT',
        'effective_date': earlier.isoformat(), 'amount': '1200', 'currency': 'BRL'})
    assert response.status_code == 200, response.text
    changed = c.get(f"/api/portfolios/1/fixed-income/lots/{created['id']}").json()
    assert changed['start_date'] == earlier.isoformat()
    assert changed['opening_amount'] == '1200.000000000000'
    assert c.delete(url).status_code == 204
    overview = c.get('/api/portfolios/1/overview').json()
    assert overview['fixed_income']['lot_count'] == 0
    assert overview['summary']['total_value'] == 0
    with Session(engine) as session:
        assert session.get(FixedIncomeLot, created['id']) is None
        assert session.query(FixedIncomeMovement).filter_by(lot_id=created['id']).count() == 0


def test_benchmark_redemption_uses_stored_observations_and_rejects_gaps(client):
    c, engine = client
    with Session(engine) as session:
        mapping = BenchmarkProviderMapping(benchmark_id=1, provider='test',
                                           series_id='redemption-test', active=True, is_primary=True)
        session.add(mapping)
        session.flush()
        for day in (2, 3):
            session.add(BenchmarkObservation(benchmark_id=1, provider_mapping_id=mapping.id,
                reference_date=date(2024, 1, day), value=Decimal('10'), source='test',
                retrieved_at=datetime(2024, 1, 5, tzinfo=timezone.utc)))
        session.commit()
    created = c.post('/api/portfolios/1/fixed-income/lots', json=lot_payload(
        maturity_date=None, fixed_rate=None, yield_structure='BENCHMARK_MULTIPLE',
        benchmark_id=1, benchmark_multiplier='1', business_day_calendar='NONE')).json()
    base = f"/api/portfolios/1/fixed-income/lots/{created['id']}/movements"
    first = c.post(base, json={'movement_type': 'PARTIAL_REDEMPTION',
        'effective_date': '2024-01-03', 'amount': '550', 'currency': 'BRL'})
    assert first.status_code == 201, first.text
    assert c.post('/api/portfolios/1/consolidate').status_code == 200
    after = c.get(f"/api/portfolios/1/fixed-income/lots/{created['id']}",
                  params={'as_of': '2024-01-03'}).json()['valuation']
    assert Decimal(str(after['outstanding_principal'])) == 500
    assert Decimal(str(after['gross_accrued_value'])) == 550
    gap = c.post(base, json={'movement_type': 'FULL_REDEMPTION',
        'effective_date': '2024-01-05', 'currency': 'BRL'})
    assert gap.status_code == 422 and 'missing_benchmark' in gap.text
    full = c.post(base, json={'movement_type': 'FULL_REDEMPTION',
        'effective_date': '2024-01-04', 'currency': 'BRL'})
    assert full.status_code == 201, full.text
    assert Decimal(full.json()['amount']) == 605


def test_deleting_required_additional_investment_rejects_dependent_redemption(client):
    c, _ = client
    start = date.today() - timedelta(days=2)
    created = c.post('/api/portfolios/1/fixed-income/lots', json=lot_payload(
        start_date=start.isoformat(), maturity_date=None, fixed_rate='0')).json()
    base = f"/api/portfolios/1/fixed-income/lots/{created['id']}/movements"
    additional = c.post(base, json={'movement_type': 'ADDITIONAL_INVESTMENT',
        'effective_date': start.isoformat(), 'amount': '500', 'currency': 'BRL'}).json()
    redemption = c.post(base, json={'movement_type': 'PARTIAL_REDEMPTION',
        'effective_date': (start + timedelta(days=1)).isoformat(),
        'amount': '1200', 'currency': 'BRL'}).json()
    result = c.delete(f"{base}/{additional['id']}")
    assert result.status_code == 422 and str(redemption['id']) in result.text
    assert [row['id'] for row in c.get(base).json()] == [
        created['movements'][0]['id'], additional['id'], redemption['id']]


@pytest.mark.integration
@pytest.mark.skipif(os.getenv('RUN_DB_TESTS') != '1', reason='Requires a migrated PostgreSQL test database.')
def test_fixed_income_api_persists_lots_and_movements_in_postgres():
    with postgres_engine.connect() as connection:
        outer = connection.begin()

        def override():
            with Session(connection, join_transaction_mode='create_savepoint', expire_on_commit=False) as session:
                yield session

        app.dependency_overrides[get_session] = override
        try:
            with Session(connection, join_transaction_mode='create_savepoint') as session:
                portfolio = Portfolio(name='Fixed-income PostgreSQL test')
                session.add(portfolio)
                session.flush()
                instrument = Instrument(symbol='FI-POSTGRES-TEST', name='Test CDB',
                                        asset_type='FIXED_INCOME', currency='BRL',
                                        portfolio_id=portfolio.id)
                session.add(instrument)
                session.commit()
                portfolio_id, instrument_id = portfolio.id, instrument.id

            with TestClient(app) as c:
                base = f'/api/portfolios/{portfolio_id}/fixed-income/lots'
                response = c.post(base, json=lot_payload(instrument_id=instrument_id))
                assert response.status_code == 201, response.text
                lot_id = response.json()['id']
                response = c.post(f'{base}/{lot_id}/movements', json={
                    'movement_type': 'PARTIAL_REDEMPTION', 'effective_date': '2025-01-02',
                    'amount': '100.25', 'currency': 'BRL',
                })
                assert response.status_code == 201, response.text
                movements = c.get(f'{base}/{lot_id}/movements').json()
                assert [row['movement_type'] for row in movements] == [
                    'INITIAL_INVESTMENT', 'PARTIAL_REDEMPTION']
                assert [Decimal(row['amount']) for row in movements] == [
                    Decimal('1000'), Decimal('100.25')]

            with Session(connection, join_transaction_mode='create_savepoint') as session:
                assert session.get(FixedIncomeLot, lot_id).asset.instrument_id == instrument_id
                assert session.query(FixedIncomeMovement).filter_by(lot_id=lot_id).count() == 2
        finally:
            app.dependency_overrides.clear()
            outer.rollback()
