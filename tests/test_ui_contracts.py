"""UI projections preserve the authenticated financial-space boundary."""
from tests.test_auth import auth_client, login


def test_instrument_pages_include_private_identity_without_cross_space_leaks(auth_client):
    client, _ = auth_client
    assert client.get('/api/instruments').status_code == 401
    alice = login(client).json()
    first_space = alice['households'][0]['id']
    first = client.post('/api/instruments/custom', json={
        'symbol': 'PRIVATE-A', 'name': 'Private A', 'currency': 'BRL',
    }).json()
    second_space = client.post('/api/households', json={'name': 'Second'}).json()['id']
    client.headers['X-Household-ID'] = str(second_space)
    second = client.post('/api/instruments/custom', json={
        'symbol': 'PRIVATE-B', 'name': 'Private B', 'currency': 'BRL',
    }).json()
    result = client.get('/api/instruments').json()
    assert second['id'] in {row['id'] for row in result}
    assert first['id'] not in {row['id'] for row in result}
    assert client.get(f"/api/instruments/{first['id']}").status_code == 404
    client.headers['X-Household-ID'] = str(first_space)
    detail = client.get(f"/api/instruments/{first['id']}").json()
    assert detail['symbol'] == 'PRIVATE-A'
    assert detail['origin'] == 'CUSTOM'
    assert isinstance(detail['aliases'], list)
    assert isinstance(detail['mappings'], list)
    login(client, 'bob')
    client.headers.pop('X-Household-ID')
    assert client.get(f"/api/instruments/{first['id']}").status_code == 404


def test_api_product_identity_is_quintrion():
    from src.main import app
    assert app.title == 'Quintrion'


def test_overview_exposes_canonical_identity_for_alias_transaction_details(auth_client):
    client, _ = auth_client
    login(client)
    pid = client.post('/api/portfolios', json={'name': 'Alias portfolio'}).json()['id']
    iid = client.post('/api/instruments/custom', json={
        'symbol': 'CANONICAL', 'name': 'Canonical identity', 'currency': 'BRL',
    }).json()['id']
    tx = client.post(f'/api/portfolios/{pid}/transactions', json={
        'asset': 'ALIAS', 'instrument_id': iid, 'type': 'Buy', 'broker': 'Example',
        'trade_date': '2024-01-02', 'settlement_date': '2024-01-02',
        'quantity': '2', 'price': '10', 'transaction_currency': 'BRL',
    })
    assert tx.status_code == 201, tx.text
    assert tx.json()['asset'] == 'ALIAS'
    position = client.get(f'/api/portfolios/{pid}/overview').json()['positions'][0]
    assert position['asset'] == 'CANONICAL'
    assert position['instrument_id'] == iid
    assert position['status'] == 'pending'


def test_invalid_import_retains_raw_fields_for_server_validated_correction():
    from src.transaction_import import preview_import
    result = preview_import(object(), 'bad.csv', (
        'ticker,broker,type,trade_date,settlement_date,quantity,unit_price,transaction_currency\n'
        'TEST,Example,Buy,2024-01-02,2024-01-03,invalid,20,BRL\n'
    ).encode())
    row = result['rows'][0]
    assert not row['valid']
    assert row['raw']['quantity'] == 'invalid'
    assert row['raw']['asset'] == 'TEST'
    assert 'data' not in row


def test_period_analytics_is_scoped_and_validates_range(auth_client, monkeypatch):
    from datetime import date
    from decimal import Decimal
    client, _ = auth_client
    login(client)
    portfolio_id = client.post('/api/portfolios', json={'name': 'Synthetic'}).json()['id']
    assert client.get(f'/api/portfolios/{portfolio_id}/analytics?start_date=2024-01-03&end_date=2024-01-02').status_code == 422
    # Preserve the real authorization boundary while replacing only history data.
    def series(session, pid):
        from src.services import get_portfolio
        get_portfolio(session, pid)
        return [{'date': date(2024, 1, 2), 'status': 'complete',
                 'daily_return_pct': Decimal('10'), 'net_flow': Decimal('50')}]
    monkeypatch.setattr('src.api.routes.portfolio_series', series)
    assert client.get(f'/api/portfolios/{portfolio_id}/analytics').json() == {
        'return_pct': 10, 'net_contributions': 50, 'status': 'complete',
    }
    login(client, 'bob')
    assert client.get(f'/api/portfolios/{portfolio_id}/analytics').status_code == 404


def test_spa_deep_links_preserve_api_and_asset_404s(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path
    from fastapi.testclient import TestClient
    dist = tmp_path / 'frontend' / 'dist'
    (dist / 'assets').mkdir(parents=True)
    (dist / 'brand').mkdir()
    (dist / 'index.html').write_text('<title>Quintrion</title>', encoding='utf-8')
    (dist / 'brand' / 'quintrion_favicon.ico').write_bytes(b'icon')
    monkeypatch.setattr('src.config.ROOT', tmp_path)
    spec = importlib.util.spec_from_file_location('ui_assembly', Path(__file__).parents[1] / 'src/main.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with TestClient(module.app) as client:
        for path in ['/overview', '/positions/12', '/fixed-income/3', '/transactions/import',
                     '/settings/spaces/2/members', '/account/preferences']:
            response = client.get(path)
            assert response.status_code == 200
            assert response.text == '<title>Quintrion</title>'
        for path in ['/api/nonexistent', '/assets/missing.js', '/brand/missing.svg']:
            assert client.get(path).status_code == 404
        assert client.get('/favicon.ico').content == b'icon'
