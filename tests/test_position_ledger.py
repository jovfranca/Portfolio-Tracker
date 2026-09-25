from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace as Obj

import pytest

from src.domain import portfolio_day, position_history, position_now, summary_totals


def tx(identifier, kind, day, quantity, price, currency='BRL', broker='A', fee=0):
    return Obj(id=identifier, type=kind, trade_date=date(2024, 1, day),
               settlement_date=date(2024, 1, day), date_time=datetime(2024, 1, day),
               quantity=Decimal(str(quantity)), price=Decimal(str(price)),
               transaction_currency=currency, broker=broker, brokerage_fee=Decimal(str(fee)),
               other_fees=Decimal('0'))


def quote(day, price, currency='BRL'):
    return Obj(date=date(2024, 1, day), close=Decimal(str(price)), currency=currency)


def event(identifier, kind, day, amount=None, factor=None, currency='BRL'):
    return Obj(id=identifier, origin='manual', event_type=kind,
               effective_date=date(2024, 1, day), amount_per_unit=amount,
               conversion_factor=factor, currency=currency)


def rates(*pairs):
    return {(currency, date(2024, 1, day)): Decimal(str(factor))
            for currency, day, factor in pairs}


def test_canonical_position_cross_currency_sale_and_missing_fx():
    rows = [tx(1, 'Buy', 1, 10, 10), tx(2, 'Sell', 3, 4, 30, 'USD')]
    fx = rates(('USD', 3, 5))
    result = position_now(rows, [], quote(3, 25), 'BRL', fx)
    assert result['quantity'] == 6
    assert result['remaining_acquisition_cost'] == 60
    assert result['realized_gain'] == 560
    assert result['unrealized_gain'] == 90
    assert result['total_gain'] == 650
    assert result['status'] == 'complete'
    incomplete = position_now(rows, [], quote(3, 25), 'BRL', {})
    assert incomplete['quantity'] == 6
    assert incomplete['realized_gain'] is None
    assert incomplete['status'] == 'missing_fx'


def test_additional_purchase_does_not_erase_earlier_return():
    rows = [tx(1, 'Buy', 1, 10, 10), tx(2, 'Buy', 3, 10, 11)]
    history = position_history(rows, [], [quote(1, 10), quote(2, 11), quote(3, 11)], 'BRL', {})
    assert [row['cumulative_return_pct'] for row in history] == [0, 10, 10]
    assert history[-1]['daily_return_pct'] == 0
    assert history[-1]['remaining_acquisition_cost'] == 210


def test_sale_liquidation_reopening_and_fees_chain_return():
    rows = [tx(1, 'Buy', 1, 10, 10, fee=2), tx(2, 'Sell', 2, 5, 12, fee=1),
            tx(3, 'Sell', 3, 5, 12, fee=1), tx(4, 'Buy', 4, 2, 12)]
    series = position_history(rows, [], [quote(i, 12 if i > 1 else 10) for i in range(1, 5)], 'BRL', {})
    assert series[2]['quantity'] == series[2]['remaining_acquisition_cost'] == 0
    assert series[2]['realized_gain'] == 16
    assert series[3]['quantity'] == 2
    assert series[3]['remaining_acquisition_cost'] == 24
    assert series[3]['realized_gain'] == 16
    assert series[3]['daily_return_pct'] == 0
    assert series[3]['cumulative_return_pct'] == series[2]['cumulative_return_pct']


def test_income_increases_total_pnl_and_return_without_changing_cost():
    rows = [tx(1, 'Buy', 1, 10, 10)]
    events = [event(1, 'DIVIDEND', 2, Decimal('1')),
              event(2, 'JCP', 3, Decimal('0.5'))]
    series = position_history(rows, events, [quote(1, 10), quote(2, 10), quote(3, 10)], 'BRL', {})
    assert series[1]['gross_income'] == 10
    assert series[1]['total_gain'] == 10
    assert series[1]['daily_return_pct'] == 10
    assert series[2]['gross_income'] == 15
    assert series[2]['remaining_acquisition_cost'] == 100
    assert series[2]['cumulative_return_pct'] == Decimal('15.5')


def test_splits_do_not_create_return_and_oversell_is_rejected():
    rows = [tx(1, 'Buy', 1, 10, 10)]
    split = event(1, 'STOCK_SPLIT', 2, factor=Decimal('2'))
    series = position_history(rows, [split], [quote(1, 10), quote(2, 5)], 'BRL', {})
    assert series[1]['quantity'] == 20
    assert series[1]['average_cost'] == 5
    assert series[1]['cumulative_return_pct'] == 0
    bad = rows + [tx(2, 'Sell', 3, 11, 10)]
    with pytest.raises(ValueError, match='excede'):
        position_history(bad, [], [quote(1, 10), quote(3, 10)], 'BRL', {})
    with pytest.raises(ValueError, match='excede'):
        position_now(bad, [], quote(3, 10), 'BRL', {})


def test_reporting_currency_fx_changes_return_and_income():
    rows = [tx(1, 'Buy', 1, 1, 10, 'USD')]
    prices = [quote(1, 10, 'USD'), quote(2, 10, 'USD')]
    fx = rates(('USD', 1, 5), ('USD', 2, 6))
    usd = position_history(rows, [], prices, 'USD', fx)
    brl = position_history(rows, [], prices, 'BRL', fx)
    assert usd[-1]['cumulative_return_pct'] == 0
    assert brl[-1]['cumulative_return_pct'] == 20
    assert brl[-1]['market_value'] == 60
    assert brl[-1]['unrealized_gain'] == 10


def test_missing_quote_and_fx_expose_explicit_incomplete_status():
    rows = [tx(1, 'Buy', 1, 1, 10, 'USD')]
    series = position_history(rows, [], [quote(2, 11, 'USD')], 'BRL', {})
    assert series[0]['status'] == 'missing_price_and_fx'
    assert series[1]['status'] == 'missing_fx'
    assert series[1]['total_gain'] is None


def test_later_quote_does_not_hide_an_incomplete_return_history():
    rows = [tx(1, 'Buy', 1, 1, 10)]
    series = position_history(rows, [], [quote(1, 10), quote(3, 12)], 'BRL', {})
    assert series[1]['status'] == 'missing_price'
    assert series[2]['market_value'] == 12
    assert series[2]['cumulative_return_pct'] is None
    assert series[2]['status'] == 'incomplete_history'


def test_portfolio_totals_never_add_an_unknown_reporting_value():
    positions = [
        {'acquisition_cost': Decimal('10'), 'display_value': Decimal('12'),
         'realized_gain': Decimal('1'), 'unrealized_gain': Decimal('2'),
         'gross_income': Decimal('3'), 'current_total_gain': Decimal('6')},
        {'acquisition_cost': None, 'display_value': None, 'realized_gain': None,
         'unrealized_gain': None, 'gross_income': None, 'current_total_gain': None},
    ]
    assert summary_totals(positions)['total_gain'] is None
    assert summary_totals(positions)['priced_value'] == 12


def test_portfolio_daily_return_chains_from_aggregated_flows():
    rows = [Obj(status='complete', remaining_acquisition_cost=Decimal('210'),
                market_value=Decimal('220'), realized_gain=Decimal('0'),
                unrealized_gain=Decimal('10'), gross_income=Decimal('0'),
                total_gain=Decimal('10'), net_flow=Decimal('110'), purchases=Decimal('110'), daily_income=Decimal('0'))]
    result = portfolio_day(rows, Decimal('110'), Decimal('1.1'))
    assert result['daily_return_pct'] == 0
    assert result['cumulative_return_pct'] == 10


def test_same_day_round_trip_preserves_return_at_position_and_portfolio_level():
    rows = [tx(1, 'Buy', 2, 10, 10), tx(2, 'Sell', 2, 10, 12)]
    daily = position_history(rows, [], [], 'BRL', {})[0]
    assert daily['realized_gain'] == 20
    assert daily['cumulative_return_pct'] == 20
    total = portfolio_day([Obj(**daily)], Decimal('0'), Decimal('1'))
    assert total['cumulative_return_pct'] == 20


def test_weekend_split_does_not_reuse_presplit_close():
    rows = [tx(1, 'Buy', 5, 10, 10)]
    events = [event(1, 'STOCK_SPLIT', 6, factor=Decimal('2'))]
    series = position_history(rows, events, [quote(5, 10)], 'BRL', {}, end=date(2024, 1, 7))
    assert series[1]['quantity'] == 20
    assert series[1]['market_value'] is None
    assert series[2]['market_value'] is None
    assert series[1]['status'] == 'missing_price'
    resumed = position_history([], [], [quote(5, 10)], 'BRL', {},
                               start=date(2024, 1, 7), end=date(2024, 1, 7),
                               initial_state=series[1]['ledger_state'])
    assert resumed[0]['market_value'] is None
