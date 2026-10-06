"""Local startup must provide a usable login without weakening ordinary startup."""
import os
import re
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.providers import ProviderIdentity
from src.auth.service import cookie_options, resolve_identity
from src.main import app
from src.models import Membership, Portfolio
from tests.test_auth import auth_client  # noqa: F401


@pytest.fixture
def unconfigured_auth(monkeypatch):
    # These are also the effective defaults of an existing pre-authentication .env.
    monkeypatch.setenv('DEV_AUTH_ENABLED', '0')
    monkeypatch.setenv('DEV_AUTH_TOKEN', '')
    monkeypatch.setenv('GOOGLE_CLIENT_ID', '')
    monkeypatch.setenv('SESSION_COOKIE_SECURE', '1')


def test_local_launcher_bootstraps_login_and_restoration_for_existing_user(
    auth_client, unconfigured_auth, monkeypatch, capsys,
):
    client, engine = auth_client
    assert client.get('/api/auth/me').status_code == 401
    config = client.get('/api/auth/config').json()
    assert config['dev_enabled'] is False and config['google_client_id'] is None
    with Session(engine) as session:
        user = resolve_identity(session, ProviderIdentity('LOCAL', 'local', 'Migrated user'))
        household_id = session.scalar(select(Membership.household_id).where(Membership.user_id == user.id))
        session.add(Portfolio(household_id=household_id, name='Retained portfolio'))
        session.commit()
        user_id = user.id

    from scripts import start_local_api
    key = 'synthetic-local-chavé'
    monkeypatch.setattr(start_local_api.getpass, 'getpass', lambda _: key)
    def serve(application, *, host, port):
        assert (application, host, port) == ('src.main:app', '127.0.0.1', 8000)
        assert client.get('/api/auth/config').json()['dev_enabled'] is True
        assert client.get('/api/portfolios').status_code == 401
        assert client.post('/api/auth/dev', json={'username': 'local', 'token': 'wrong'}).status_code == 401
        logged_in = client.post('/api/auth/dev', json={'username': 'local', 'token': key})
        assert logged_in.status_code == 200, logged_in.text
        assert 'Secure;' not in logged_in.headers['set-cookie']
        assert logged_in.json()['user']['id'] == user_id
        assert client.get('/api/auth/me').json() == logged_in.json()
        assert [row['name'] for row in client.get('/api/portfolios').json()] == ['Retained portfolio']
    monkeypatch.setattr(start_local_api.uvicorn, 'run', serve)
    start_local_api.main()
    output = capsys.readouterr()
    assert key not in output.out + output.err


@pytest.mark.parametrize('provider', ['dev', 'google'])
def test_local_launcher_preserves_configured_login(provider, unconfigured_auth, monkeypatch):
    from scripts import start_local_api
    if provider == 'dev':
        monkeypatch.setenv('DEV_AUTH_ENABLED', '1')
        monkeypatch.setenv('DEV_AUTH_TOKEN', 'already-configured-synthetic-key')
    else:
        monkeypatch.setenv('GOOGLE_CLIENT_ID', 'synthetic-client')
    monkeypatch.setattr(start_local_api.getpass, 'getpass', lambda _: pytest.fail('Configured login prompted again'))
    called = []
    monkeypatch.setattr(start_local_api.uvicorn, 'run', lambda *args, **kwargs: called.append((args, kwargs)))
    start_local_api.main()
    assert called == [(('src.main:app',), {'host': '127.0.0.1', 'port': 8000})]
    assert os.environ['SESSION_COOKIE_SECURE'] == '0'
    assert os.environ['DEV_AUTH_ENABLED'] == ('1' if provider == 'dev' else '0')
    assert os.environ['DEV_AUTH_TOKEN'] == ('already-configured-synthetic-key' if provider == 'dev' else '')


@pytest.mark.parametrize('key,message', [('   ', 'vazia'), ('x' * 1025, '1024')])
def test_local_launcher_rejects_invalid_key_before_starting_server(key, message, unconfigured_auth, monkeypatch):
    from scripts import start_local_api
    monkeypatch.setattr(start_local_api.getpass, 'getpass', lambda _: key)
    monkeypatch.setattr(start_local_api.uvicorn, 'run', lambda *a, **k: pytest.fail('Server started without a login'))
    with pytest.raises(SystemExit, match=message):
        start_local_api.main()
    assert os.environ['DEV_AUTH_ENABLED'] == '0'
    assert os.environ['SESSION_COOKIE_SECURE'] == '1'


def test_local_launcher_never_falls_back_to_echoing_a_key(unconfigured_auth, monkeypatch):
    from scripts import start_local_api
    import warnings
    def insecure_prompt(_):
        warnings.warn('Password input may be echoed.', start_local_api.getpass.GetPassWarning)
        pytest.fail('Insecure prompt continued')
    monkeypatch.setattr(start_local_api.getpass, 'getpass', insecure_prompt)
    monkeypatch.setattr(start_local_api.uvicorn, 'run', lambda *a, **k: pytest.fail('Server started without a login'))
    with pytest.raises(SystemExit, match='interativo'):
        start_local_api.main()


def test_ordinary_startup_keeps_production_authentication_defaults(monkeypatch):
    from scripts import start_local_api  # noqa: F401
    monkeypatch.delenv('SESSION_COOKIE_SECURE', raising=False)
    monkeypatch.delenv('DEV_AUTH_ENABLED', raising=False)
    monkeypatch.delenv('DEV_AUTH_TOKEN', raising=False)
    from src.auth.service import dev_enabled
    assert cookie_options()['secure'] is True
    assert not dev_enabled()


@pytest.mark.skipif(not Path('frontend/dist/index.html').is_file(), reason='Requires a built frontend.')
def test_html_is_not_cached_and_references_available_assets():
    with TestClient(app) as client:
        response = client.get('/')
        assert response.status_code == 200
        assert response.headers.get('cache-control') == 'no-store'
        assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', response.text)
        assert assets
        for path in assets:
            assert client.get(path).status_code == 200
        assert client.get('/assets/index-removed-build.js').status_code == 404
