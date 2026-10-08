"""Monetary period performance uses the existing return numerator and dated flows."""
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.domain import fixed_income_valuation, period_summary, position_history


def trade(day, kind, quantity, price, fee=0, currency='BRL', fx=1):
    return SimpleNamespace(id=day.day, type=kind, quantity=Decimal(str(quantity)),
        price=Decimal(str(price)), brokerage_fee=Decimal(str(fee)), other_fees=Decimal('0'),
        transaction_currency=currency, fx_rate=Decimal(str(fx)), broker='Synthetic',
        trade_date=day, settlement_date=day)


def quote(day, price, currency='BRL'):
    return SimpleNamespace(date=day, close=Decimal(str(price)), currency=currency)


def test_period_result_includes_sale_fees_income_and_excludes_purchases():
    first = date(2024, 1, 1)
    rows = position_history([
        trade(first, 'Buy', 10, 10, fee=2),
        trade(first + timedelta(days=1), 'Buy', 5, 12),
        trade(first + timedelta(days=2), 'Sell', 5, 14, fee=1),
    ], [SimpleNamespace(id=1, event_type='DIVIDEND', effective_date=first + timedelta(days=2),
        currency='BRL', amount_per_unit=Decimal('1'))], [
        quote(first, 10), quote(first + timedelta(days=1), 12), quote(first + timedelta(days=2), 14),
    ], 'BRL', {}, start=first, end=first + timedelta(days=2))
    # Day 2: 180 - 100 - 60 = 20. Day 3: 140 + 15 - 180 + 69 = 44.
    result = period_summary(rows, first + timedelta(days=1), first + timedelta(days=2))
    assert result['monetary_result'] == Decimal('64')
    assert result['net_contributions'] == Decimal('-9')
    assert result['reporting_currency'] == 'BRL'
    assert result['start_date'] == first + timedelta(days=1)
    assert result['end_date'] == first + timedelta(days=2)
    assert period_summary(rows)['monetary_result'] == Decimal('62')  # opening purchase fee


def test_period_result_uses_dated_display_fx_and_reports_zero_for_only_capital_movement():
    day = date(2024, 1, 1)
    rows = position_history([trade(day, 'Buy', 1, 10, currency='USD'),
        trade(day + timedelta(days=1), 'Buy', 1, 10, currency='USD')], [],
        [quote(day, 10, 'USD'), quote(day + timedelta(days=1), 10, 'USD')], 'EUR', {
            ('USD', day): Decimal('2'), ('USD', day + timedelta(days=1)): Decimal('3'),
        }, start=day, end=day + timedelta(days=1))
    assert period_summary(rows, day, day)['monetary_result'] == 0
    assert period_summary(rows, day + timedelta(days=1))['monetary_result'] == 10
    assert period_summary(rows)['reporting_currency'] == 'EUR'


@pytest.mark.parametrize('field', ['market_value', 'net_flow', 'daily_income'])
def test_period_result_never_substitutes_zero_for_missing_inputs(field):
    rows = [{'date': date(2024, 1, 1), 'reporting_currency': 'BRL', 'status': 'complete',
             'market_value': Decimal('100'), 'net_flow': Decimal('100'),
             'daily_income': Decimal('0'), 'daily_return_pct': Decimal('0')}]
    rows[0][field] = None
    assert period_summary(rows)['monetary_result'] is None
    assert period_summary(rows)['status'] == 'incomplete'


def test_period_result_requires_opening_snapshot_continuity_and_requested_end_coverage():
    rows = [{'date': date(2024, 1, day), 'reporting_currency': 'BRL', 'status': 'complete',
             'market_value': Decimal('100'), 'net_flow': Decimal('0'),
             'daily_income': Decimal('0'), 'daily_return_pct': Decimal('0')} for day in (1, 2, 3)]
    rows[0]['status'] = 'pending'
    assert period_summary(rows, date(2024, 1, 2), date(2024, 1, 3))['monetary_result'] is None
    rows[0]['status'] = 'complete'
    assert period_summary(rows, date(2024, 1, 2), date(2024, 1, 4))['monetary_result'] is None
    assert period_summary([rows[0], rows[2]])['monetary_result'] is None
    rows[2]['reporting_currency'] = 'USD'
    assert period_summary(rows)['monetary_result'] is None
    assert period_summary(rows)['net_contributions'] is None


def test_truncated_inception_series_must_not_assume_a_zero_opening_value():
    rows = [{'date': date(2024, 1, 2), 'reporting_currency': 'BRL', 'status': 'complete',
             'market_value': Decimal('110'), 'net_flow': Decimal('0'),
             'daily_income': Decimal('0'), 'daily_return_pct': Decimal('10')}]
    result = period_summary(rows, inception_date=date(2024, 1, 1))
    assert result['monetary_result'] is None and result['status'] == 'incomplete'
    assert result['return_pct'] is None


def test_period_result_fixed_income_contribution_partial_and_full_redemption():
    from tests.test_fixed_income_valuation import lot
    def movement(kind, day, amount):
        return SimpleNamespace(id=day.day, movement_type=kind, effective_date=day,
                               amount=Decimal(str(amount)), currency='BRL')
    first = date(2024, 1, 1)
    contract = lot(start_date=first, fixed_rate=Decimal('0.365'), compounding='SIMPLE', day_count_basis='ACT_365')
    movements = [movement('INITIAL_INVESTMENT', first, 100),
                 movement('ADDITIONAL_INVESTMENT', first + timedelta(days=1), 50),
                 movement('PARTIAL_REDEMPTION', first + timedelta(days=2), 20)]
    rows = []
    for offset in range(3):
        day = first + timedelta(days=offset)
        value = fixed_income_valuation(contract, movements, day)
        flow = sum((m.amount if 'INVESTMENT' in m.movement_type else -m.amount
                    for m in movements if m.effective_date == day), Decimal('0'))
        rows.append({'date': day, 'reporting_currency': 'BRL', 'status': value['status'],
                     'market_value': value['gross_accrued_value'], 'net_flow': flow,
                     'daily_income': Decimal('0'), 'daily_return_pct': Decimal('0')})
    result = period_summary(rows, first + timedelta(days=1))
    assert result['monetary_result'] == rows[-1]['market_value'] - Decimal('100') - Decimal('30')
    assert result['monetary_result'] > 0
    final_day = first + timedelta(days=3)
    final_value = fixed_income_valuation(contract, movements, final_day)['gross_accrued_value']
    movements.append(movement('FULL_REDEMPTION', final_day, final_value))
    value = fixed_income_valuation(contract, movements, final_day)
    rows.append({'date': final_day, 'reporting_currency': 'BRL', 'status': value['status'],
                 'market_value': value['gross_accrued_value'], 'net_flow': -final_value,
                 'daily_income': Decimal('0'), 'daily_return_pct': Decimal('0')})
    assert period_summary(rows)['monetary_result'] == final_value + 20 - 150
