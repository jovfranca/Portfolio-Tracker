from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace as Obj

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.api import routes
from src.corporate_actions import get_actions, get_stored_actions, store_provider_actions
from src.database import Base
from src.domain import cost_and_quantity, corporate_event_effects, historical_profitability, overview
from src.models import (
    Asset, CorporateAction, CorporateActionCoverage, Instrument, MarketPrice,
    MarketPriceCoverage, Portfolio, ProviderInstrument, UserCorporateEvent,
)
from src.schemas import CorporateEventInput


@pytest.fixture
def action_session():
    engine = create_engine('sqlite://')
    for table in [
        Portfolio.__table__, Instrument.__table__, ProviderInstrument.__table__,
        Asset.__table__, CorporateAction.__table__, CorporateActionCoverage.__table__,
        UserCorporateEvent.__table__, MarketPrice.__table__, MarketPriceCoverage.__table__,
    ]:
        table.create(engine)
    with Session(engine) as session:
        instrument = Instrument(symbol='TEST', currency='USD', asset_type='STOCK')
        first = Portfolio(name='First')
        second = Portfolio(name='Second')
        session.add_all([instrument, first, second])
        session.flush()
        session.add(ProviderInstrument(
            instrument_id=instrument.id, provider='yfinance', provider_symbol='TEST',
            quote_currency='USD', active=True, is_primary=True,
        ))
        session.add_all([
            Asset(portfolio_id=first.id, instrument_id=instrument.id, ticker='TEST'),
            Asset(portfolio_id=second.id, instrument_id=instrument.id, ticker='TEST'),
        ])
        session.flush()
        yield session


def _provider_row(day, *, dividend='0', split='0'):
    return {
        'date': day, 'price': Decimal('10'), 'currency': 'USD',
        'dividends': Decimal(dividend), 'stock_splits': Decimal(split),
        'source': 'yfinance',
        'retrieved_at': datetime(2024, 2, 1, tzinfo=timezone.utc),
    }


def test_provider_actions_are_shared_and_empty_coverage_is_cached(action_session):
    first, second = list(action_session.scalars(select(Asset).order_by(Asset.id)))
    calls = []

    def fetch(symbol, currency, start, end):
        calls.append((start, end))
        return [_provider_row(date(2024, 1, 8), dividend='0.50', split='2')]

    result = get_actions(action_session, first, date(2024, 1, 8), date(2024, 1, 9), fetch)
    cached = get_actions(
        action_session, second, date(2024, 1, 8), date(2024, 1, 9),
        lambda *args: pytest.fail('covered action range was fetched again'),
    )
    assert result.complete and cached.complete
    assert [row.event_type for row in cached.actions] == ['STOCK_SPLIT', 'DIVIDEND']
    assert len(calls) == 1
    assert action_session.scalar(select(func.count()).select_from(CorporateAction)) == 2
    assert action_session.scalar(select(func.count()).select_from(CorporateActionCoverage)) == 1

    empty_calls = []
    empty = lambda *args: empty_calls.append(args) or []
    get_actions(action_session, first, date(2024, 1, 10), date(2024, 1, 10), empty)
    get_actions(action_session, second, date(2024, 1, 10), date(2024, 1, 10), empty)
    assert len(empty_calls) == 1


def test_manual_event_is_private_and_overrides_equivalent_provider_action(action_session):
    first, second = list(action_session.scalars(select(Asset).order_by(Asset.id)))
    values = {
        'event_type': 'DIVIDEND', 'effective_date': date(2024, 1, 8),
        'payment_date': date(2024, 1, 15), 'amount_per_unit': Decimal('0.50'),
        'conversion_factor': None, 'currency': 'USD', 'source': 'yfinance',
        'provider_event_id': None,
        'retrieved_at': datetime(2024, 2, 1, tzinfo=timezone.utc),
    }
    store_provider_actions(action_session, first.instrument_id, [values])
    action_session.add(UserCorporateEvent(
        asset_id=first.id, event_type='DIVIDEND', effective_date=date(2024, 1, 8),
        payment_date=date(2024, 1, 15), amount_per_unit=Decimal('0.75'),
        currency='USD', source='manual', notes='Broker correction',
    ))
    action_session.flush()

    first_actions = get_stored_actions(action_session, first)
    second_actions = get_stored_actions(action_session, second)
    assert [(row.origin, row.amount_per_unit) for row in first_actions] == [
        ('manual', Decimal('0.750000000000')),
    ]
    assert [(row.origin, row.amount_per_unit) for row in second_actions] == [
        ('provider', Decimal('0.500000000000')),
    ]

    changed = values | {'amount_per_unit': Decimal('9.99')}
    assert store_provider_actions(action_session, first.instrument_id, [changed]) == 0


def test_manual_reverse_split_replaces_provider_split_on_same_day(action_session):
    asset = action_session.scalar(select(Asset).order_by(Asset.id))
    day = date(2024, 1, 8)
    store_provider_actions(action_session, asset.instrument_id, [{
        'event_type': 'STOCK_SPLIT', 'effective_date': day,
        'payment_date': None, 'amount_per_unit': None,
        'conversion_factor': Decimal('2'), 'currency': None,
        'source': 'yfinance', 'provider_event_id': None,
        'retrieved_at': datetime(2024, 2, 1, tzinfo=timezone.utc),
    }])
    action_session.add(UserCorporateEvent(
        asset_id=asset.id, event_type='REVERSE_SPLIT', effective_date=day,
        conversion_factor=Decimal('0.5'), source='manual',
    ))
    action_session.flush()

    events = get_stored_actions(action_session, asset)
    assert [(event.origin, event.event_type) for event in events] == [
        ('manual', 'REVERSE_SPLIT'),
    ]
    action_session.add(UserCorporateEvent(
        asset_id=asset.id, event_type='STOCK_SPLIT', effective_date=day,
        conversion_factor=Decimal('2'), source='manual',
    ))
    with pytest.raises(IntegrityError):
        action_session.flush()


def test_provider_identifier_added_later_does_not_duplicate_historical_event(action_session):
    asset = action_session.scalar(select(Asset).order_by(Asset.id))
    values = {
        'event_type': 'DIVIDEND', 'effective_date': date(2024, 1, 8),
        'payment_date': None, 'amount_per_unit': Decimal('0.50'),
        'conversion_factor': None, 'currency': 'USD', 'source': 'yfinance',
        'provider_event_id': None,
        'retrieved_at': datetime(2024, 2, 1, tzinfo=timezone.utc),
    }
    assert store_provider_actions(action_session, asset.instrument_id, [values]) == 1
    assert store_provider_actions(
        action_session, asset.instrument_id,
        [values | {'provider_event_id': 'dividend-123'}],
    ) == 0
    assert len(get_stored_actions(action_session, asset)) == 1


def test_changed_provider_identifier_and_payment_date_cannot_double_apply_event(action_session):
    asset = action_session.scalar(select(Asset).order_by(Asset.id))
    values = {
        'event_type': 'DIVIDEND', 'effective_date': date(2024, 1, 8),
        'payment_date': None, 'amount_per_unit': Decimal('0.50'),
        'conversion_factor': None, 'currency': 'USD', 'source': 'yfinance',
        'provider_event_id': 'old-id',
        'retrieved_at': datetime(2024, 2, 1, tzinfo=timezone.utc),
    }
    assert store_provider_actions(action_session, asset.instrument_id, [values]) == 1
    correction = values | {
        'provider_event_id': 'new-id', 'payment_date': date(2024, 1, 15),
        'amount_per_unit': Decimal('0.75'),
    }
    assert store_provider_actions(action_session, asset.instrument_id, [correction]) == 0
    assert len(get_stored_actions(action_session, asset)) == 1
    assert get_stored_actions(action_session, asset)[0].amount_per_unit == Decimal('0.50')


def test_provider_split_correction_cannot_apply_opposite_split_as_second_event(action_session):
    asset = action_session.scalar(select(Asset).order_by(Asset.id))
    values = {
        'event_type': 'STOCK_SPLIT', 'effective_date': date(2024, 1, 8),
        'payment_date': None, 'amount_per_unit': None,
        'conversion_factor': Decimal('2'), 'currency': None,
        'source': 'yfinance', 'provider_event_id': None,
        'retrieved_at': datetime(2024, 2, 1, tzinfo=timezone.utc),
    }
    assert store_provider_actions(action_session, asset.instrument_id, [values]) == 1
    assert store_provider_actions(action_session, asset.instrument_id, [
        values | {'event_type': 'REVERSE_SPLIT', 'conversion_factor': Decimal('0.5')},
    ]) == 0
    assert len(get_stored_actions(action_session, asset)) == 1


@pytest.mark.parametrize('invalid', [
    {'dividends': Decimal('NaN')}, {'stock_splits': Decimal('-2')},
])
def test_invalid_action_metadata_does_not_mark_provider_range_covered(action_session, invalid):
    asset = action_session.scalar(select(Asset).order_by(Asset.id))
    day = date(2024, 1, 8)
    result = get_actions(
        action_session, asset, day, day,
        lambda *args: [_provider_row(day) | invalid],
    )
    assert not result.complete
    assert not result.actions
    assert action_session.scalar(select(func.count()).select_from(CorporateActionCoverage)) == 0


def _transaction(identifier, kind, quantity, price, day):
    return Obj(
        id=identifier, type=kind, quantity=Decimal(quantity), price=Decimal(price),
        trade_date=day, date_time=datetime.combine(day, datetime.min.time()),
    )


def _event(identifier, event_type, day, *, factor=None, amount=None, currency=None):
    return Obj(
        id=identifier, event_type=event_type, effective_date=day,
        conversion_factor=Decimal(factor) if factor else None,
        amount_per_unit=Decimal(amount) if amount else None, currency=currency,
    )


def test_split_and_income_use_opening_position_and_preserve_basis():
    split_day = date(2024, 1, 2)
    transactions = [
        _transaction(1, 'Buy', '10', '20', date(2024, 1, 1)),
        _transaction(2, 'Buy', '5', '12', split_day),
    ]
    events = [
        _event(1, 'STOCK_SPLIT', split_day, factor='2'),
        _event(2, 'DIVIDEND', split_day, amount='1', currency='USD'),
    ]
    average, quantity = cost_and_quantity(transactions, events)
    effects = corporate_event_effects(transactions, events)

    assert quantity == Decimal('25')
    assert average == Decimal('10.4')
    assert average * quantity == Decimal('260.0')
    assert effects[0]['quantity_before'] == 10
    assert effects[0]['quantity_after'] == 20
    assert effects[0]['average_cost_after'] == 10
    assert effects[1]['eligible_quantity'] == 20
    assert effects[1]['gross_amount'] == 20

    series = historical_profitability(
        transactions, [Obj(date=split_day, close=Decimal('12'))], events,
    )
    assert series[0]['unrealized_gain'] == 40
    assert series[0]['income_by_currency'] == {'USD': Decimal('20')}


def test_reverse_split_preserves_remaining_acquisition_cost():
    transactions = [_transaction(1, 'Buy', '20', '5', date(2024, 1, 1))]
    events = [_event(1, 'REVERSE_SPLIT', date(2024, 1, 2), factor='0.25')]
    average, quantity = cost_and_quantity(transactions, events)
    assert (average, quantity) == (Decimal('20'), Decimal('5.00'))
    assert average * quantity == Decimal('100.00')


@pytest.mark.parametrize('event_type,factor', [
    ('STOCK_SPLIT', '0.5'), ('REVERSE_SPLIT', '2'),
])
def test_split_type_requires_factor_in_the_matching_direction(event_type, factor):
    with pytest.raises(ValueError, match='fator'):
        CorporateEventInput(
            event_type=event_type, effective_date=date(2024, 1, 2),
            conversion_factor=factor,
        )


def test_legacy_quote_metadata_cannot_apply_an_event_by_itself():
    transactions = [_transaction(1, 'Buy', '10', '20', date(2024, 1, 1))]
    quote = Obj(
        date=date(2024, 1, 2), close=Decimal('20'),
        dividends=Decimal('5'), stock_splits=Decimal('2'),
    )
    assert cost_and_quantity(transactions) == (Decimal('20'), Decimal('10'))
    assert historical_profitability(transactions, [quote])[0]['total_gain'] == 0


def test_income_effect_does_not_claim_unknown_tax_or_net_amount():
    transactions = [_transaction(1, 'Buy', '10', '20', date(2024, 1, 1))]
    events = [_event(1, 'DIVIDEND', date(2024, 1, 2), amount='1', currency='USD')]

    effect = corporate_event_effects(transactions, events)[0]

    assert effect['gross_amount'] == Decimal('10')
    assert effect['withholding_tax'] is None
    assert effect['net_amount'] is None


def test_event_effect_does_not_mix_average_costs_from_different_currencies():
    transactions = [
        _transaction(1, 'Buy', '10', '20', date(2024, 1, 1)),
        _transaction(2, 'Buy', '10', '100', date(2024, 1, 2)),
    ]
    transactions[0].transaction_currency = 'USD'
    transactions[1].transaction_currency = 'BRL'
    events = [_event(1, 'STOCK_SPLIT', date(2024, 1, 3), factor='2')]

    effect = corporate_event_effects(transactions, events)[0]

    assert effect['eligible_quantity'] == Decimal('20')
    assert effect['quantity_after'] == Decimal('40')
    assert effect['average_cost_before'] is None
    assert effect['average_cost_after'] is None


def test_overview_does_not_value_post_split_shares_with_pre_split_price():
    transaction = _transaction(1, 'Buy', '10', '20', date(2024, 1, 1))
    transaction.asset = 'TEST'
    transaction.broker = 'Example'
    transaction.allocation_class = 'Stocks'
    transaction.transaction_currency = 'USD'
    split = _event(1, 'STOCK_SPLIT', date(2024, 1, 3), factor='2')
    asset = Obj(
        id=1, ticker='TEST', transaction_currency='USD',
        history=[Obj(date=date(2024, 1, 2), close=Decimal('20'))],
        corporate_events=[split],
    )

    result = overview([transaction], [asset], display_currency='USD')

    assert result['positions'][0]['quantity'] == 20
    assert result['positions'][0]['total_value'] is None
    assert result['assets'][0]['total_value'] is None
    assert result['summary']['total_value'] is None
    assert result['positions'][0]['current_price'] is None
    assert result['positions'][0]['unrealized_gain'] is None
    assert result['positions'][0]['current_total_gain'] is None
    assert result['positions'][0]['current_accumulated_profitability'] is None
    assert result['assets'][0]['current_price'] is None

    asset.history.append(Obj(date=date(2024, 1, 3), close=Decimal('10')))
    current = overview([transaction], [asset], display_currency='USD')
    assert current['positions'][0]['total_value'] == Decimal('200')
    assert current['summary']['total_value'] == Decimal('200')


def test_activity_route_orders_same_day_events_by_calculation_order(monkeypatch):
    transaction = _transaction(1, 'Buy', '10', '20', date(2024, 1, 1))
    transaction.trade_date = date(2024, 1, 1)
    transaction.transaction_currency = 'USD'
    transaction.broker = 'Example'
    transaction.allocation_class = 'Stocks'
    dividend = _event(1, 'DIVIDEND', date(2024, 1, 2), amount='1', currency='USD')
    split = _event(2, 'STOCK_SPLIT', date(2024, 1, 2), factor='2')
    for event in (dividend, split):
        event.payment_date = None
        event.source = 'manual'
        event.origin = 'manual'
        event.retrieved_at = None
        event.notes = ''
    monkeypatch.setattr(routes, 'get_asset', lambda *args: Obj(instrument_id=1))
    monkeypatch.setattr(routes, 'get_stored_actions', lambda *args: [dividend, split])
    session = Obj(scalars=lambda statement: [transaction])

    activity = routes.asset_activity(1, 1, session)

    assert [row.get('event_type', row.get('type')) for row in activity] == [
        'Buy', 'STOCK_SPLIT', 'DIVIDEND',
    ]
    assert activity[-1]['eligible_quantity'] == Decimal('20')
