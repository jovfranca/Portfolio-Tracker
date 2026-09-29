from datetime import date
from decimal import Decimal
from types import SimpleNamespace as Row

from src.domain import fixed_income_valuation


def lot(**changes):
    values = dict(currency='BRL', start_date=date(2024, 1, 2), maturity_date=None,
                  yield_structure='FIXED_RATE', fixed_rate=Decimal('0.12'),
                  benchmark_id=None, benchmark=None, benchmark_multiplier=None,
                  benchmark_spread=None, day_count_basis='ACT_365',
                  compounding='COMPOUND', business_day_calendar='NONE',
                  benchmark_lag_months=0)
    values.update(changes)
    return Row(**values)


def movement(identifier, kind, day, amount):
    return Row(id=identifier, movement_type=kind, effective_date=date(2024, 1, day),
               amount=Decimal(str(amount)), currency='BRL')


def observation(day, value):
    return Row(reference_date=date(2024, 1, day), value=Decimal(str(value)))


def test_fixed_rate_accrues_and_partial_redemption_preserves_other_lots():
    terms = lot()
    opening = movement(1, 'INITIAL_INVESTMENT', 2, 1000)
    first = fixed_income_valuation(terms, [opening], date(2024, 1, 3))
    expected = Decimal('1000') * Decimal('1.12') ** (Decimal('1') / 365)
    assert abs(first['gross_accrued_value'] - expected) < Decimal('0.000001')
    redemption = movement(2, 'PARTIAL_REDEMPTION', 3, 500)
    reduced = fixed_income_valuation(terms, [opening, redemption], date(2024, 1, 3))
    assert reduced['gross_accrued_value'] == first['gross_accrued_value'] - 500
    assert reduced['outstanding_principal'] < 1000
    assert fixed_income_valuation(terms, [opening], date(2024, 1, 3)) == first
    closed = fixed_income_valuation(terms, [opening, movement(3, 'FULL_REDEMPTION', 3, 1100)], date(2024, 1, 3))
    assert closed['outstanding_principal'] == closed['gross_accrued_value'] == 0
    matured = fixed_income_valuation(lot(maturity_date=date(2024, 1, 3)),
                                     [opening, movement(4, 'MATURITY', 3, 1100)], date(2024, 1, 4))
    assert matured['status'] == 'complete'
    assert matured['gross_accrued_value'] == 0


def test_cdi_multiple_uses_daily_rate_and_missing_day_fails_closed():
    terms = lot(yield_structure='BENCHMARK_MULTIPLE', fixed_rate=None, benchmark_id=1,
                benchmark=Row(code='CDI', frequency='DAILY', unit='PERCENT_PER_DAY'),
                benchmark_multiplier=Decimal('1.10'), day_count_basis='BUS_252')
    rows = [movement(1, 'INITIAL_INVESTMENT', 2, 1000)]
    missing = fixed_income_valuation(terms, rows, date(2024, 1, 4), [observation(3, '0.04')])
    assert missing['status'] == 'missing_benchmark'
    assert missing['gross_accrued_value'] is None
    complete = fixed_income_valuation(terms, rows, date(2024, 1, 4),
                                      [observation(3, '0.04'), observation(4, '0.05')])
    assert complete['gross_accrued_value'] == 1000 * Decimal('1.00044') * Decimal('1.00055')


def test_ipca_spread_uses_monthly_change_and_contractual_spread():
    terms = lot(yield_structure='BENCHMARK_SPREAD', fixed_rate=None, benchmark_id=2,
                benchmark=Row(code='IPCA', frequency='MONTHLY', unit='PERCENT_PER_MONTH'),
                benchmark_spread=Decimal('0.06'))
    rows = [movement(1, 'INITIAL_INVESTMENT', 2, 1000)]
    dec_observation = Row(reference_date=date(2023, 12, 1), value=Decimal('0.31'))
    complete = fixed_income_valuation(terms, rows, date(2024, 1, 3),
                                      [dec_observation])
    expected_day = Decimal('1.0031') ** (Decimal('1') / 31) * Decimal('1.06') ** (Decimal('1') / 365)
    assert abs(complete['gross_accrued_value'] - 1000 * expected_day) < Decimal('0.000001')
    assert complete['benchmark_start'] == date(2023, 12, 1)


def test_missing_maturity_movement_and_invalid_ledger_are_incomplete():
    opening = movement(1, 'INITIAL_INVESTMENT', 2, 1000)
    terms = lot(maturity_date=date(2024, 1, 3))
    expired = fixed_income_valuation(terms, [opening], date(2024, 1, 4))
    assert expired['status'] == 'missing_maturity_movement'
    assert expired['gross_accrued_value'] is None
    bad = fixed_income_valuation(lot(), [opening, movement(2, 'PARTIAL_REDEMPTION', 3, 2000)],
                                 date(2024, 1, 3))
    assert bad['status'] == 'invalid_movements'
    assert bad['gross_accrued_value'] is None


def test_maturity_movement_must_match_contractual_maturity_date():
    opening = movement(1, 'INITIAL_INVESTMENT', 2, 1000)
    early_maturity = movement(2, 'MATURITY', 3, 1000)
    valued = fixed_income_valuation(
        lot(maturity_date=date(2024, 1, 5)),
        [opening, early_maturity], date(2024, 1, 6),
    )
    assert valued['status'] == 'invalid_movements'
    assert valued['gross_accrued_value'] is None
