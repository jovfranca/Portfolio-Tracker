"""SQLite coverage for the canonical replay boundary; no provider or PostgreSQL required."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import CheckConstraint, MetaData, create_engine, select
from sqlalchemy.orm import Session

from src.database import Base
from src.models import (Asset, Instrument, Portfolio, PositionInvalidation,
                        PositionSnapshot, Transaction, UserDefinedPrice)
from src import consolidation
from src.position_reporting import get_overview
from src.api import routes
from src.schemas import TransactionSelectionInput


def sqlite_engine():
    engine = create_engine('sqlite://')
    metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        table.to_metadata(metadata)
    transactions = metadata.tables['transactions']
    for constraint in list(transactions.constraints):
        if isinstance(constraint, CheckConstraint) and '~' in str(constraint.sqltext):
            transactions.constraints.remove(constraint)
    metadata.create_all(engine)
    return engine


def test_transaction_writes_validate_one_position_without_building_overview(monkeypatch):
    engine = sqlite_engine()
    monkeypatch.setattr(routes, 'get_overview', lambda *_: (_ for _ in ()).throw(
        AssertionError('write built overview')))
    with Session(engine) as session:
        portfolio = Portfolio(name='Writes')
        instrument = Instrument(symbol='PETR4', currency='BRL', asset_type='STOCK')
        other = Instrument(symbol='ARKK', currency='BRL', asset_type='STOCK')
        session.add_all([portfolio, instrument, other])
        session.commit()
        payload = TransactionSelectionInput(
            instrument_id=instrument.id, asset='PETR4', trade_date=date.today(),
            settlement_date=date.today(), type='Buy', broker='A', quantity=2,
            price=10, transaction_currency='BRL',
        )
        created = routes.add_transaction(portfolio.id, payload, session)
        assert created.id is not None
        assert session.scalar(select(PositionInvalidation.instrument_id).where(
            PositionInvalidation.portfolio_id == portfolio.id)) == instrument.id
        routes.edit_transaction(portfolio.id, created.id, payload.model_copy(update={
            'quantity': Decimal('3')}), session)
        routes.edit_transaction(portfolio.id, created.id, payload.model_copy(update={
            'asset': 'ARKK', 'instrument_id': other.id}), session)
        assert set(session.scalars(select(PositionInvalidation.instrument_id).where(
            PositionInvalidation.portfolio_id == portfolio.id))) == {instrument.id, other.id}
        routes.delete_transaction(portfolio.id, created.id, session)
        assert session.get(Portfolio, portfolio.id).dirty_from == date.today()


def test_dirty_trade_replays_only_its_instrument_and_currency_switch_keeps_checkpoints(monkeypatch):
    engine = sqlite_engine()
    calls = []

    def history(session, asset, start, end):
        calls.append(asset.instrument.symbol)
        return SimpleNamespace(missing_ranges=[])

    monkeypatch.setattr(consolidation, 'get_history', history)
    monkeypatch.setattr(consolidation, 'get_actions', lambda *args: SimpleNamespace(
        complete=True, missing_ranges=[]))
    monkeypatch.setattr(consolidation, 'get_latest', lambda *args: SimpleNamespace(
        price=SimpleNamespace(close=Decimal('10')), stale=False))
    first = date.today() - timedelta(days=2)
    with Session(engine) as session:
        portfolio = Portfolio(name='Targeted', display_currency='BRL')
        session.add(portfolio)
        session.flush()
        trades = {}
        for symbol in ('PETR4', 'ARKK'):
            instrument = Instrument(symbol=symbol, currency='BRL', asset_type='STOCK')
            session.add(instrument)
            session.flush()
            asset = Asset(portfolio_id=portfolio.id, instrument_id=instrument.id, ticker=symbol)
            session.add(asset)
            session.flush()
            trade = Transaction(
                portfolio_id=portfolio.id, instrument_id=instrument.id,
                date_time=datetime.combine(first, time.min), trade_date=first,
                settlement_date=first, type='Buy', asset=symbol, broker='A',
                allocation_class='Stocks', transaction_currency='BRL', fx_rate=1,
                quantity=1, price=10, brokerage_fee=0, other_fees=0,
            )
            session.add(trade)
            trades[symbol] = trade
            for offset in range(3):
                session.add(UserDefinedPrice(asset_id=asset.id,
                    reference_date=first + timedelta(days=offset), price=10,
                    currency='BRL', source='manual'))
        session.flush()
        assert consolidation.consolidate(session, portfolio.id)['complete']
        session.flush()
        arkk_ids = list(session.scalars(select(PositionSnapshot.id).where(
            PositionSnapshot.portfolio_id == portfolio.id,
            PositionSnapshot.instrument_id == trades['ARKK'].instrument_id,
        ).order_by(PositionSnapshot.date)))
        calls.clear()
        trades['PETR4'].quantity = 2
        session.flush()
        dirty = list(session.scalars(select(PositionInvalidation.instrument_id).where(
            PositionInvalidation.portfolio_id == portfolio.id)))
        assert dirty == [trades['PETR4'].instrument_id]
        assert portfolio.dirty_from == first
        assert consolidation.consolidate(session, portfolio.id)['complete']
        session.flush()
        assert calls == ['PETR4']
        assert list(session.scalars(select(PositionSnapshot.id).where(
            PositionSnapshot.portfolio_id == portfolio.id,
            PositionSnapshot.instrument_id == trades['ARKK'].instrument_id,
        ).order_by(PositionSnapshot.date))) == arkk_ids
        checkpoints = list(session.scalars(select(PositionSnapshot.id).where(
            PositionSnapshot.portfolio_id == portfolio.id).order_by(PositionSnapshot.id)))
        built_through = portfolio.history_built_through
        portfolio.display_currency = 'USD'
        session.flush()
        assert portfolio.dirty_from is None
        assert portfolio.history_built_through == built_through
        assert list(session.scalars(select(PositionSnapshot.id).where(
            PositionSnapshot.portfolio_id == portfolio.id).order_by(PositionSnapshot.id))) == checkpoints
        session.delete(trades['PETR4'])
        session.flush()
        stale = next(row for row in get_overview(session, portfolio.id)['positions']
                     if row['asset'] == 'PETR4')
        assert stale['quantity'] == 2
        assert stale['status'] == 'pending'
