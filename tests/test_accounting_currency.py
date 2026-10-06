"""Regression coverage for per-position accounting and display currencies."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import importlib
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from src import consolidation
from src.market_prices import accounting_currency
from src.models import (Asset, Broker, ExchangeRate, FixedIncomeLot, Instrument, Portfolio, PortfolioSnapshot,
                        PositionInvalidation, PositionSnapshot, ProviderInstrument, Transaction, UserCorporateEvent,
                        UserDefinedPrice)
from tests.test_targeted_consolidation import sqlite_engine


@pytest.mark.parametrize(('asset_type', 'native', 'quote', 'expected'), [
    ('STOCK', 'USD', 'USD', 'USD'),
    ('ETF', 'BRL', 'BRL', 'BRL'),
    ('CRYPTO', None, 'USD', 'USD'),
])
def test_provider_accounting_currency_follows_primary_quote(asset_type, native, quote, expected):
    with Session(sqlite_engine()) as session:
        portfolio = Portfolio(household_id=1, name='Accounting', display_currency='EUR')
        instrument = Instrument(symbol='TEST', asset_type=asset_type, currency=native)
        session.add_all([portfolio, instrument])
        session.flush()
        asset = Asset(portfolio_id=portfolio.id, instrument_id=instrument.id, ticker='TEST')
        session.add_all([asset, ProviderInstrument(
            instrument_id=instrument.id, provider='yfinance', provider_symbol='TEST-USD',
            quote_currency=quote, active=True, is_primary=True,
        )])
        session.flush()
        assert accounting_currency(session, asset) == expected


def test_manual_and_fixed_income_accounting_currencies_are_explicit():
    with Session(sqlite_engine()) as session:
        portfolio = Portfolio(household_id=1, name='Manual')
        manual = Instrument(symbol='MANUAL', asset_type='OTHER', currency='EUR')
        unknown = Instrument(symbol='UNKNOWN', asset_type='OTHER')
        session.add_all([portfolio, manual, unknown])
        session.flush()
        manual_asset = Asset(portfolio_id=portfolio.id, instrument_id=manual.id, ticker='MANUAL')
        unknown_asset = Asset(portfolio_id=portfolio.id, instrument_id=unknown.id, ticker='UNKNOWN')
        session.add_all([manual_asset, unknown_asset])
        session.flush()
        assert accounting_currency(session, manual_asset) == 'EUR'
        with pytest.raises(ValueError, match='accounting currency'):
            accounting_currency(session, unknown_asset)

        fixed = Instrument(symbol='BOND', asset_type='FIXED_INCOME', currency='BRL')
        broker = Broker(name='A')
        session.add_all([fixed, broker])
        session.flush()
        fixed_asset = Asset(portfolio_id=portfolio.id, instrument_id=fixed.id, ticker='BOND')
        session.add(fixed_asset)
        session.flush()
        session.add(FixedIncomeLot(
            asset_id=fixed_asset.id, product_type='BOND', issuer='Issuer', broker_id=broker.id,
            currency='USD', start_date=date.today(), yield_structure='FIXED_RATE',
            fixed_rate=Decimal('0.1'), day_count_basis='ACT_365', compounding='COMPOUND',
            business_day_calendar='BR',
        ))
        session.flush()
        assert accounting_currency(session, fixed_asset) == 'USD'


def test_ambiguous_provider_mapping_cannot_fall_back_to_native_currency():
    with Session(sqlite_engine()) as session:
        portfolio = Portfolio(household_id=1, name='Ambiguous')
        instrument = Instrument(symbol='DUAL', asset_type='STOCK', currency='EUR')
        session.add_all([portfolio, instrument])
        session.flush()
        asset = Asset(portfolio_id=portfolio.id, instrument_id=instrument.id, ticker='DUAL')
        session.add(asset)
        for currency in ('USD', 'BRL'):
            session.add(ProviderInstrument(instrument_id=instrument.id, provider='yfinance',
                provider_symbol=f'DUAL-{currency}', quote_currency=currency, active=True, is_primary=False))
        session.flush()
        with pytest.raises(ValueError, match='accounting currency'):
            accounting_currency(session, asset)


@pytest.mark.parametrize(('trade_currency', 'expected_cost'), [
    ('USD', Decimal('10')),
    ('BRL', Decimal('2')),
])
def test_manual_priced_position_persists_its_price_currency(monkeypatch, trade_currency, expected_cost):
    engine = sqlite_engine()
    first = date.today() - timedelta(days=1)
    monkeypatch.setattr(consolidation, 'get_latest', lambda *args: SimpleNamespace(
        price=SimpleNamespace(close=Decimal('12')), stale=False))
    monkeypatch.setattr(consolidation, 'get_actions', lambda *args: SimpleNamespace(
        complete=True, missing_ranges=[]))
    with Session(engine) as session:
        portfolio = Portfolio(household_id=1, name='Private', display_currency='BRL')
        instrument = Instrument(symbol='PRIVATE', asset_type='OTHER', currency='USD')
        session.add_all([portfolio, instrument])
        session.flush()
        asset = Asset(portfolio_id=portfolio.id, instrument_id=instrument.id, ticker='PRIVATE')
        session.add(asset)
        session.flush()
        session.add(Transaction(
            portfolio_id=portfolio.id, instrument_id=instrument.id,
            date_time=datetime.combine(first, time.min), trade_date=first,
            settlement_date=first, type='Buy', asset='PRIVATE', broker='A',
            allocation_class='Other', transaction_currency=trade_currency,
            fx_rate=5 if trade_currency == 'USD' else 1,
            quantity=1, price=10, brokerage_fee=0, other_fees=0,
        ))
        session.add(UserDefinedPrice(asset_id=asset.id, reference_date=first,
                                     price=12, currency='USD', source='manual'))
        for day in (first, date.today()):
            session.add(ExchangeRate(currency='USD', rate_type='FX', rate_side='MARKET',
                                     reference_date=day, rate=5, source='test'))
        session.flush()
        consolidation.consolidate(session, portfolio.id)
        snapshot = session.scalar(select(PositionSnapshot).where(
            PositionSnapshot.instrument_id == instrument.id))
        assert snapshot.reporting_currency == 'USD'
        assert snapshot.remaining_acquisition_cost == expected_cost
        assert snapshot.market_value == 12
        assert Decimal(snapshot.ledger_state['brokers']['A']['cost']) == expected_cost
        # A pricing currency edit changes the checkpoint unit, unlike a price correction.
        for price in session.scalars(select(UserDefinedPrice).where(UserDefinedPrice.asset_id == asset.id)):
            price.currency = 'EUR'
        for day in (first, date.today()):
            session.add(ExchangeRate(currency='EUR', rate_type='FX', rate_side='MARKET',
                                     reference_date=day, rate=6, source='test'))
        session.flush()
        assert session.scalar(select(PositionInvalidation.dirty_from).where(
            PositionInvalidation.instrument_id == instrument.id)) == first
        consolidation.consolidate(session, portfolio.id)
        session.flush()
        rebuilt = session.scalar(select(PositionSnapshot).where(PositionSnapshot.instrument_id == instrument.id))
        assert rebuilt.reporting_currency == 'EUR'
        assert abs(rebuilt.remaining_acquisition_cost - expected_cost * 5 / 6) < Decimal('0.000000001')
        extra_price = UserDefinedPrice(asset_id=asset.id, reference_date=date.today(),
                                      price=13, currency='EUR', source='manual')
        session.add(extra_price)
        session.flush()
        old_price = session.scalar(select(UserDefinedPrice).where(
            UserDefinedPrice.asset_id == asset.id, UserDefinedPrice.reference_date == first))
        session.delete(old_price)
        session.flush()
        assert session.scalar(select(PositionInvalidation.id).where(
            PositionInvalidation.instrument_id == instrument.id)) is None


@pytest.mark.parametrize(('asset_type', 'native_currency'), [('CRYPTO', None), ('STOCK', 'USD')])
def test_foreign_canonical_snapshot_uses_settlement_fx_and_survives_display_switch(
        monkeypatch, asset_type, native_currency):
    engine = sqlite_engine()
    first = date.today() - timedelta(days=2)
    event_day = first + timedelta(days=1)
    monkeypatch.setattr(consolidation, 'get_history', lambda *args: SimpleNamespace(missing_ranges=[]))
    monkeypatch.setattr(consolidation, 'get_actions', lambda *args: SimpleNamespace(
        complete=True, missing_ranges=[]))
    monkeypatch.setattr(consolidation, 'get_latest', lambda *args: SimpleNamespace(
        price=SimpleNamespace(close=Decimal('20')), stale=False))
    with Session(engine) as session:
        portfolio = Portfolio(household_id=1, name='Mixed', display_currency='BRL')
        instrument = Instrument(symbol='COIN', asset_type=asset_type, currency=native_currency)
        session.add_all([portfolio, instrument])
        session.flush()
        asset = Asset(portfolio_id=portfolio.id, instrument_id=instrument.id, ticker='COIN')
        session.add_all([asset, ProviderInstrument(
            instrument_id=instrument.id, provider='yfinance', provider_symbol='COIN-USD',
            quote_currency='USD', active=True, is_primary=True,
        )])
        local = Instrument(symbol='LOCAL', asset_type='STOCK', currency='BRL')
        session.add(local)
        session.flush()
        local_asset = Asset(portfolio_id=portfolio.id, instrument_id=local.id, ticker='LOCAL')
        session.add_all([local_asset, ProviderInstrument(
            instrument_id=local.id, provider='yfinance', provider_symbol='LOCAL.SA',
            quote_currency='BRL', active=True, is_primary=True,
        )])
        session.flush()
        session.add(Transaction(
            portfolio_id=portfolio.id, instrument_id=instrument.id,
            date_time=datetime.combine(first, time.min), trade_date=first,
            settlement_date=first, type='Buy', asset='COIN', broker='A',
            allocation_class='Crypto', transaction_currency='BRL', fx_rate=1,
            quantity=2, price=50, brokerage_fee=0, other_fees=0,
        ))
        session.add(Transaction(
            portfolio_id=portfolio.id, instrument_id=local.id,
            date_time=datetime.combine(first, time.min), trade_date=first,
            settlement_date=first, type='Buy', asset='LOCAL', broker='A',
            allocation_class='Stocks', transaction_currency='BRL', fx_rate=1,
            quantity=1, price=10, brokerage_fee=0, other_fees=0,
        ))
        session.add(UserDefinedPrice(asset_id=asset.id, reference_date=first,
                                     price=20, currency='USD', source='manual'))
        session.add(UserDefinedPrice(asset_id=asset.id, reference_date=event_day,
                                     price=20, currency='USD', source='manual'))
        for day in (first, event_day):
            session.add(UserDefinedPrice(asset_id=local_asset.id, reference_date=day,
                                         price=10, currency='BRL', source='manual'))
        session.add(UserCorporateEvent(
            asset_id=asset.id, event_type='DIVIDEND', effective_date=event_day,
            amount_per_unit=3, currency='EUR', source='manual',
        ))
        for day in (first, event_day, date.today()):
            for currency, rate in (('USD', 5), ('EUR', 6)):
                session.add(ExchangeRate(currency=currency, rate_type='FX', rate_side='MARKET',
                                         reference_date=day, rate=rate, source='test'))
        session.flush()
        assert consolidation.consolidate(session, portfolio.id)['complete']
        snapshot = session.scalar(select(PositionSnapshot).where(
            PositionSnapshot.portfolio_id == portfolio.id,
            PositionSnapshot.instrument_id == instrument.id).order_by(PositionSnapshot.date.desc()))
        assert snapshot.reporting_currency == 'USD'
        assert snapshot.remaining_acquisition_cost == 20
        assert snapshot.average_cost == 10
        assert snapshot.market_value == 40
        assert snapshot.gross_income == Decimal('7.2')
        assert snapshot.cumulative_return_pct == 136
        assert Decimal(snapshot.ledger_state['brokers']['A']['cost']) == 20
        local_snapshot = session.scalar(select(PositionSnapshot).where(
            PositionSnapshot.instrument_id == local.id).order_by(PositionSnapshot.date.desc()))
        assert local_snapshot.reporting_currency == 'BRL'
        assert local_snapshot.remaining_acquisition_cost == 10
        assert local_snapshot.market_value == 10
        local_checkpoint = local_snapshot.id
        snapshot_id, state = snapshot.id, snapshot.ledger_state.copy()
        for display in ('USD', 'EUR', 'BRL'):
            portfolio.display_currency = display
            session.flush()
            projected = consolidation.position_series(session, portfolio.id, instrument.id)
            expected = {'USD': 40, 'EUR': Decimal('100') / 3, 'BRL': 200}[display]
            assert abs(projected[-1]['market_value'] - expected) < Decimal('0.0000000001')
            assert snapshot.id == snapshot_id
            assert snapshot.ledger_state == state
            assert portfolio.dirty_from is None
            portfolio_total = consolidation.portfolio_series(session, portfolio.id)[-1]['market_value']
            expected_total = expected + {'USD': 2, 'EUR': Decimal('10') / 6,
                                         'BRL': 10}[display]
            assert abs(portfolio_total - expected_total) < Decimal('0.0000000001')
        mapping = session.scalar(select(ProviderInstrument).where(
            ProviderInstrument.instrument_id == instrument.id))
        mapping.quote_currency = 'EUR'
        for price in session.scalars(select(UserDefinedPrice).where(UserDefinedPrice.asset_id == asset.id)):
            price.currency = 'EUR'
        session.flush()
        assert session.scalar(select(PositionInvalidation.dirty_from).where(
            PositionInvalidation.instrument_id == instrument.id)) == first
        assert consolidation.consolidate(session, portfolio.id)['complete']
        session.flush()
        rebuilt = session.scalar(select(PositionSnapshot).where(
            PositionSnapshot.instrument_id == instrument.id).order_by(PositionSnapshot.date.desc()))
        assert rebuilt.reporting_currency == 'EUR'
        assert abs(rebuilt.remaining_acquisition_cost - Decimal('100') / 6) < Decimal('0.000000001')
        assert session.get(PositionSnapshot, local_checkpoint).reporting_currency == 'BRL'


def test_accounting_currency_migration_invalidates_old_brl_history(monkeypatch):
    engine = sqlite_engine()
    first = date.today() - timedelta(days=2)
    with Session(engine) as session:
        portfolio = Portfolio(household_id=1, name='Old', display_currency='BRL', history_built_through=first)
        instrument = Instrument(symbol='FOREIGN', asset_type='STOCK', currency='USD')
        session.add_all([portfolio, instrument])
        session.flush()
        session.add(Asset(portfolio_id=portfolio.id, instrument_id=instrument.id, ticker='FOREIGN'))
        session.add(Transaction(
            portfolio_id=portfolio.id, instrument_id=instrument.id,
            date_time=datetime.combine(first, time.min), trade_date=first,
            settlement_date=first, type='Buy', asset='FOREIGN', broker='A',
            allocation_class='Stocks', transaction_currency='USD', fx_rate=5,
            quantity=1, price=10, brokerage_fee=0, other_fees=0,
        ))
        session.add(PositionSnapshot(
            portfolio_id=portfolio.id, instrument_id=instrument.id, date=first,
            reporting_currency='BRL', quantity=1, market_value=50,
            status='complete', ledger_state={'brokers': {}},
        ))
        session.add(PortfolioSnapshot(
            portfolio_id=portfolio.id, date=first, reporting_currency='BRL',
            market_value=50, status='complete',
        ))
        session.commit()
        migration = importlib.import_module('migrations.versions.0024_position_accounting_currency')
        monkeypatch.setattr(migration.op, 'execute', lambda sql: session.execute(text(sql)))
        migration.upgrade()
        session.expire_all()
        assert session.scalar(select(func.count()).select_from(PositionSnapshot)) == 0
        assert session.scalar(select(func.count()).select_from(PortfolioSnapshot)) == 0
        assert session.scalar(select(PositionInvalidation.dirty_from).where(
            PositionInvalidation.instrument_id == instrument.id)) == first
        assert session.get(Portfolio, portfolio.id).history_built_through is None
