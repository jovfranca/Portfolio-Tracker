from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.domain import annualized_period_return, period_return_series, cdi_return_series
from tests.test_auth import auth_client, login


def rows(days=365):
    return [{'date': date(2023, 1, 1) + timedelta(days=i), 'status': 'complete',
             'daily_return_pct': Decimal('10') if i == 0 else Decimal('0')}
            for i in range(days)]


def test_annualization_uses_complete_effective_calendar_days():
    summary = {'status': 'complete', 'return_pct': Decimal('10'),
               'coverage_start': date(2023, 1, 1), 'coverage_end': date(2023, 12, 31)}
    assert annualized_period_return(summary) == Decimal('10')
    summary['coverage_end'] = date(2023, 6, 30)
    assert annualized_period_return(summary) > Decimal('20')
    summary['status'] = 'incomplete'
    assert annualized_period_return(summary) is None


@pytest.mark.parametrize('value, expected', [(None, None), ('-101', None), ('-100', Decimal('-100')), ('0', Decimal('0'))])
def test_annualization_unknown_loss_and_zero(value, expected):
    assert annualized_period_return({'status': 'complete', 'return_pct': value,
        'coverage_start': date(2023, 1, 1), 'coverage_end': date(2023, 12, 31)}) == expected


def test_period_series_chains_and_never_bridges_missing_days_or_pending_returns():
    data = rows(4)
    data[1]['daily_return_pct'] = Decimal('10')
    assert [r['return_pct'] for r in period_return_series(data)] == [10, 21, 21, 21]
    assert period_return_series(data, data[1]['date'])[0]['return_pct'] == 10
    data[1]['status'] = 'pending'
    assert [r['return_pct'] for r in period_return_series(data)] == [10, None, None, None]
    assert [r['return_pct'] for r in period_return_series([data[0], data[2]])] == [10, None]


def test_cdi_comparison_compounds_stored_business_observations_and_marks_gaps():
    dates = [date(2024, 1, 5) + timedelta(days=i) for i in range(4)]
    obs = {dates[0]: Decimal('1'), dates[-1]: Decimal('2')}
    assert [r['return_pct'] for r in cdi_return_series(dates, obs)] == [1, 1, 1, Decimal('3.02')]
    assert cdi_return_series(dates, {dates[0]: Decimal('1')})[-1]['return_pct'] is None
    assert cdi_return_series([date(2024, 1, 1)], {})[0]['return_pct'] == 0  # BR holiday


def test_cdi_comparison_includes_business_days_between_available_chart_dates():
    # Portfolio snapshots may have gaps. CDI must still account for every
    # intervening business observation rather than silently losing its return.
    friday, monday, tuesday = date(2024, 1, 5), date(2024, 1, 8), date(2024, 1, 9)
    observations = {friday: Decimal('1'), monday: Decimal('2'), tuesday: Decimal('3')}
    assert cdi_return_series([friday, tuesday], observations)[-1]['return_pct'] == Decimal('6.1106')
    del observations[monday]
    assert cdi_return_series([friday, tuesday], observations)[-1]['return_pct'] is None


def test_analytics_contract_is_authenticated_and_truthful_about_unsupported_benchmarks(auth_client):
    client, _ = auth_client
    login(client)
    pid = client.post('/api/portfolios', json={'name': 'Overview analytics', 'display_currency': 'USD'}).json()['id']
    result = client.get(f'/api/portfolios/{pid}/analytics?include_series=true&benchmark_codes=CDI,SPX').json()
    assert result['annualized_return_pct'] is None
    assert result['return_series'] == []
    assert [b['status'] for b in result['benchmarks']] == ['unsupported', 'unsupported']
    login(client, 'stranger')
    assert client.get(f'/api/portfolios/{pid}/analytics?include_series=true').status_code == 404


def test_analytics_returns_rebased_series_and_stored_cdi_without_provider_calls(auth_client, monkeypatch):
    from types import SimpleNamespace
    from sqlalchemy.orm import Session
    from src.benchmark_catalog import seed_catalog
    client, engine = auth_client
    login(client)
    pid = client.post('/api/portfolios', json={'name': 'BRL comparison'}).json()['id']
    with Session(engine) as session:
        seed_catalog(session)
        session.commit()
    data = [{'date': date(2024, 1, d), 'status': 'complete', 'daily_return_pct': Decimal('1'),
             'net_flow': Decimal('100') if d == 5 else Decimal('0'), 'daily_income': Decimal('0'),
             'market_value': Decimal('101') + (d - 5), 'reporting_currency': 'BRL'} for d in (5, 6, 7, 8)]
    monkeypatch.setattr('src.api.routes.portfolio_series', lambda *args: data)
    monkeypatch.setattr('src.api.market_data.fetch_benchmark_history', lambda *args: pytest.fail('Read-only comparison called a provider'))
    observations = [SimpleNamespace(reference_date=date(2024, 1, 5), value=Decimal('0.1')),
                    SimpleNamespace(reference_date=date(2024, 1, 8), value=Decimal('0.2'))]
    monkeypatch.setattr('src.benchmarks.stored_observations', lambda *args: observations)
    result = client.get(f'/api/portfolios/{pid}/analytics?end_date=2024-01-08&include_series=true&benchmark_codes=CDI,CDI').json()
    assert result['annualized_return_pct'] > result['return_pct']
    assert result['return_series'][-1]['return_pct'] == pytest.approx(4.060401)
    assert len(result['benchmarks']) == 1
    assert result['benchmarks'][0]['status'] == 'complete'
    assert result['benchmarks'][0]['return_pct'] == pytest.approx(0.3002)
    observations.pop()
    result = client.get(f'/api/portfolios/{pid}/analytics?end_date=2024-01-08&include_series=true&benchmark_codes=CDI').json()
    assert result['benchmarks'][0]['status'] == 'incomplete'
    assert result['benchmarks'][0]['return_pct'] is None
    assert result['benchmarks'][0]['series'][-1]['return_pct'] is None
