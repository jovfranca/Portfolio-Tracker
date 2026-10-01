"""SQLite coverage for the canonical replay boundary; no provider or PostgreSQL required."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import CheckConstraint, MetaData, create_engine, select
from sqlalchemy.orm import Session
import pytest

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


def test_pending_reads_do_not_replay_changed_activity(monkeypatch):
    """A provider correction can make pending activity invalid until reviewed."""
    from src.models import UserCorporateEvent
    engine = sqlite_engine()
    first = date.today() - timedelta(days=3)
    monkeypatch.setattr(consolidation, 'get_history', lambda *args: SimpleNamespace(missing_ranges=[]))
    monkeypatch.setattr(consolidation, 'get_actions', lambda *args: SimpleNamespace(
        complete=True, missing_ranges=[]))
    monkeypatch.setattr(consolidation, 'get_latest', lambda *args: SimpleNamespace(
        price=SimpleNamespace(close=Decimal('10')), stale=False))
    with Session(engine) as session:
        portfolio = Portfolio(name='Pending')
        instrument = Instrument(symbol='PENDING', currency='BRL', asset_type='OTHER')
        session.add_all([portfolio, instrument])
        session.flush()
        asset = Asset(portfolio_id=portfolio.id, instrument_id=instrument.id, ticker='PENDING')
        session.add(asset)
        session.flush()
        for offset, kind, quantity in ((0, 'Buy', 10), (2, 'Sell', 5)):
            day = first + timedelta(days=offset)
            session.add(Transaction(
                portfolio_id=portfolio.id, instrument_id=instrument.id,
                date_time=datetime.combine(day, time.min), trade_date=day,
                settlement_date=day, type=kind, asset='PENDING', broker='A',
                allocation_class='Other', transaction_currency='BRL', fx_rate=1,
                quantity=quantity, price=10, brokerage_fee=0, other_fees=0))
        session.add(UserDefinedPrice(asset_id=asset.id, reference_date=first,
                                     price=10, currency='BRL', source='manual'))
        session.flush()
        assert consolidation.consolidate(session, portfolio.id)['complete']
        session.add(UserCorporateEvent(asset_id=asset.id, event_type='REVERSE_SPLIT',
            effective_date=first + timedelta(days=1), conversion_factor=Decimal('0.1'), source='manual'))
        session.flush()
        # Source replay would now oversell. Ordinary reads must retain the saved state.
        history = consolidation.position_series(session, portfolio.id, instrument.id)
        assert history[0]['status'] == 'complete'
        assert history[-1]['status'] == 'pending'
        assert history[-1]['quantity'] == 5
        assert history[-1]['market_value'] == 50
        overview = get_overview(session, portfolio.id)
        assert overview['positions'][0]['quantity'] == 5
        assert overview['positions'][0]['status'] == 'pending'


def test_equity_invalidation_does_not_hide_clean_fixed_income_history(monkeypatch):
    import src.fixed_income as fixed_income
    first = date.today() - timedelta(days=2)
    with Session(sqlite_engine()) as session:
        portfolio = Portfolio(name='Mixed', history_built_through=first)
        equity = Instrument(symbol='EQ', asset_type='STOCK', currency='BRL')
        bond = Instrument(symbol='FI', asset_type='FIXED_INCOME', currency='BRL')
        session.add_all([portfolio, equity, bond])
        session.flush()
        asset = Asset(portfolio_id=portfolio.id, instrument_id=equity.id, ticker='EQ')
        session.add(asset)
        session.flush()
        from src.domain import PositionLedger
        ledger = PositionLedger('BRL', {})
        ledger.brokers = {'A': {'quantity': Decimal('1'), 'cost': Decimal('10')}}
        session.add(PositionSnapshot(
            portfolio_id=portfolio.id, instrument_id=equity.id, date=first,
            reporting_currency='BRL', quantity=1, remaining_acquisition_cost=10, average_cost=10,
            market_value=10, realized_gain=0, unrealized_gain=0, gross_income=0, total_gain=0,
            net_flow=10, purchases=10, daily_income=0, status='complete', ledger_state=ledger.state()))
        session.add(UserDefinedPrice(asset_id=asset.id, reference_date=first, price=10,
                                     currency='BRL', source='manual'))
        consolidation.mark_dirty(session, portfolio.id, first, equity.id)
        session.flush()
        monkeypatch.setattr(fixed_income, 'list_lots', lambda *args: [SimpleNamespace(
            start_date=first, asset=SimpleNamespace(instrument_id=bond.id))])
        monkeypatch.setattr(fixed_income, 'daily_position_rows', lambda *args: [SimpleNamespace(
            status='complete', remaining_acquisition_cost=Decimal('100'), market_value=Decimal('100'),
            realized_gain=Decimal('0'), unrealized_gain=Decimal('0'), gross_income=Decimal('0'),
            total_gain=Decimal('0'), net_flow=Decimal('100'), purchases=Decimal('100'), daily_income=Decimal('0'))])
        history = consolidation.portfolio_series(session, portfolio.id)
        assert history[-1]['market_value'] == 110
        assert history[-1]['status'] == 'incomplete'


def test_legacy_import_keeps_foreign_catalog_prices_as_audit_only(monkeypatch):
    from src import import_legacy
    from src.instruments import create_instrument
    from src.market_prices import get_quote_history
    from src.schemas import QuoteInput
    with Session(sqlite_engine()) as session:
        portfolio = Portfolio(name='Legacy audit')
        session.add(portfolio)
        session.flush()
        instrument = create_instrument(session, symbol='FOREIGN', currency='USD',
            asset_type='STOCK', provider_symbol='FOREIGN', quote_currency='USD')
        monkeypatch.setattr(import_legacy, 'read_transactions', lambda _: ('a' * 64, []))
        monkeypatch.setattr(import_legacy, 'read_assets', lambda _: [
            (SimpleNamespace(ticker='FOREIGN'), [QuoteInput(date=date(2024, 1, 2), close=12, currency='BRL')])])
        monkeypatch.setattr(import_legacy, 'get_overview', lambda *args: (_ for _ in ()).throw(
            AssertionError('legacy write calculated overview')), raising=False)
        import_legacy.import_transactions(session, 'synthetic', portfolio.id, 'synthetic')
        price = session.scalar(select(UserDefinedPrice))
        assert price.source == 'legacy'
        assert price.currency == 'BRL'
        assert price.retrieved_at is None
        asset = session.scalar(select(Asset).where(Asset.instrument_id == instrument.id))
        assert get_quote_history(session, asset) == []


def test_legacy_import_still_rejects_oversells_without_overview(monkeypatch):
    from src import import_legacy
    from src.schemas import TransactionInput
    with Session(sqlite_engine()) as session:
        portfolio = Portfolio(name='Invalid legacy')
        session.add(portfolio)
        session.flush()
        monkeypatch.setattr(import_legacy, 'read_transactions', lambda _: ('b' * 64, [
            TransactionInput(asset='SELL', trade_date=date(2024, 1, 2), settlement_date=date(2024, 1, 2),
                type='Sell', quantity=1, price=10, broker='A', transaction_currency='BRL')]))
        with pytest.raises(ValueError, match='excede'):
            import_legacy.import_transactions(session, 'synthetic', portfolio.id)
