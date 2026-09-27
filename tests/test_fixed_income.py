from decimal import Decimal
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import CheckConstraint, MetaData, create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.database import Base, engine as postgres_engine, get_session
from src.main import app
from src.models import Benchmark, FixedIncomeLot, FixedIncomeMovement, Instrument, Portfolio, PortfolioSnapshot


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
            Instrument(symbol='CDB-ISSUER', name='Issuer CDB', asset_type='FIXED_INCOME', currency='BRL'),
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


def test_independent_lots_and_authoritative_opening_movements(client):
    c, engine = client
    first = c.post('/api/portfolios/1/fixed-income/lots', json=lot_payload()).json()
    second = c.post('/api/portfolios/1/fixed-income/lots', json=lot_payload(
        start_date='2024-02-02', fixed_rate='0.13', opening_amount='2000')).json()
    assert first['id'] != second['id']
    assert first['asset_id'] == second['asset_id']
    assert first['instrument_id'] == second['instrument_id'] == 1
    assert first['current_value'] is None and first['valuation_status'] == 'pending'
    assert first['business_day_calendar'] == 'BR' and first['benchmark_lag_months'] == 0
    assert first['movements'][0]['amount'] == '1000.000000000000'
    assert [x['id'] for x in c.get('/api/portfolios/1/fixed-income/lots').json()] == [first['id'], second['id']]
    assert c.get(f"/api/portfolios/1/fixed-income/lots/{first['id']}").json()['fixed_rate'] == '0.120000000000'
    with Session(engine) as session:
        assert session.query(FixedIncomeLot).count() == 2
        assert session.query(FixedIncomeMovement).count() == 2
    overview = c.get('/api/portfolios/1/overview').json()
    assert overview['fixed_income']['valuation_status'] == 'pending'
    assert overview['summary']['total_value'] is None
    assert overview['summary']['total_gain'] is None
    assert overview['summary']['gross_income'] is None
    consolidation = c.post('/api/portfolios/1/consolidate').json()
    assert consolidation['complete'] is False
    assert 'pendente' in consolidation['message']


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
    response = c.post('/api/instruments/custom', json={
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


def test_portfolio_history_never_reports_equity_only_values_as_complete_after_lot_start(client):
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
    history = c.get('/api/portfolios/1/history').json()
    assert history[0]['status'] == 'complete'
    assert Decimal(str(history[0]['market_value'])) == Decimal('100')
    assert history[1]['status'] == 'incomplete'
    for field in ('remaining_acquisition_cost', 'market_value', 'realized_gain',
                  'unrealized_gain', 'gross_income', 'total_gain',
                  'daily_return_pct', 'cumulative_return_pct'):
        assert history[1][field] is None, field


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
                instrument = Instrument(symbol='FI-POSTGRES-TEST', name='Test CDB',
                                        asset_type='FIXED_INCOME', currency='BRL')
                session.add_all([portfolio, instrument])
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
