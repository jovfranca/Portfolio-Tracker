from datetime import date
from decimal import Decimal

from src.domain import period_summary


def test_period_summary_chains_existing_daily_returns_and_sums_known_flows():
    rows = [
        {'date': date(2024, 1, 1), 'status': 'complete', 'daily_return_pct': Decimal('20'), 'net_flow': Decimal('100')},
        {'date': date(2024, 1, 2), 'status': 'complete', 'daily_return_pct': Decimal('10'), 'net_flow': Decimal('50')},
        {'date': date(2024, 1, 3), 'status': 'complete', 'daily_return_pct': Decimal('-10'), 'net_flow': Decimal('-20')},
    ]
    for row, value in zip(rows, ['120', '187', '148.3']):
        row.update(reporting_currency='BRL', market_value=Decimal(value), daily_income=Decimal('0'))
    assert period_summary(rows, date(2024, 1, 2), date(2024, 1, 3)) == {
        'return_pct': Decimal('-1'), 'net_contributions': Decimal('30'), 'status': 'complete',
        'monetary_result': Decimal('-1.7'), 'reporting_currency': 'BRL',
        'start_date': date(2024, 1, 2), 'end_date': date(2024, 1, 3),
        'coverage_start': date(2024, 1, 2), 'coverage_end': date(2024, 1, 3),
    }


def test_period_summary_never_bridges_unknown_returns_or_pending_sources():
    rows = [{'date': date(2024, 1, 2), 'status': 'pending',
             'daily_return_pct': None, 'net_flow': Decimal('100')}]
    assert period_summary(rows, None, None) == {
        'return_pct': None, 'net_contributions': None, 'status': 'incomplete',
        'monetary_result': None, 'reporting_currency': None,
        'start_date': date(2024, 1, 2), 'end_date': date(2024, 1, 2),
        'coverage_start': date(2024, 1, 2), 'coverage_end': date(2024, 1, 2),
    }
    assert period_summary([], None, None)['return_pct'] is None


def test_period_summary_does_not_replace_unknown_cash_flows_with_zero():
    rows = [{'date': date(2024, 1, 2), 'status': 'complete',
             'daily_return_pct': Decimal('2'), 'net_flow': None}]
    result = period_summary(rows)
    assert result['net_contributions'] is None
    assert result['return_pct'] == Decimal('2')
