from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace as Obj

from src import position_reporting


def test_future_settlement_marks_cost_fx_missing_instead_of_crashing(monkeypatch):
    transaction = Obj(id=1, type='Buy', transaction_currency='USD', fx_rate=Decimal('5'),
                      settlement_date=date.today() + timedelta(days=2))
    def no_future_conversion(*args, **kwargs):
        raise AssertionError('Future settlement cannot resolve reporting FX yet')
    monkeypatch.setattr(position_reporting, 'convert_amount', no_future_conversion)
    assert position_reporting.reporting_factors(None, 'EUR', [transaction], [], []) == {}
