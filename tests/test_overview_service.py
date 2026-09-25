from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace as Obj

from src import services


def test_future_settlement_marks_cost_fx_missing_instead_of_crashing(monkeypatch):
    transaction = Obj(id=1, type='Buy', transaction_currency='USD', fx_rate=Decimal('5'),
                      settlement_date=date.today() + timedelta(days=2))
    monkeypatch.setattr(services, 'get_portfolio', lambda *args: Obj(display_currency='EUR'))
    class Session:
        def __init__(self):
            self.results = iter([[transaction], []])
        def scalars(self, query):
            return next(self.results)
    def convert(*args, **kwargs):
        raise ValueError('A data de referência não pode estar no futuro.')
    monkeypatch.setattr(services, 'convert_amount', convert)
    monkeypatch.setattr(services, 'overview', lambda txs, assets, currency, factors, costs: costs)
    assert services.get_overview(Session(), 1) == {}
