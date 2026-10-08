"""Authenticated HTTP sessions, financial-space roles and isolation."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.database import get_session
from src.main import app
from src.models import AuthIdentity, AuthSession, HouseholdInvitation, Membership, User
from tests.test_targeted_consolidation import sqlite_engine


@pytest.fixture
def auth_client(monkeypatch):
    monkeypatch.setenv('DEV_AUTH_ENABLED', '1')
    monkeypatch.setenv('DEV_AUTH_TOKEN', 'synthetic-development-key')
    monkeypatch.setenv('SESSION_COOKIE_SECURE', '0')
    monkeypatch.setattr('src.api.market_data.fetch_history', lambda *a, **k: [])
    adapted = sqlite_engine()
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    from sqlalchemy import MetaData
    schema = MetaData()
    schema.reflect(adapted)
    schema.create_all(engine)
    adapted.dispose()

    def override():
        with Session(engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_session] = override
    try:
        with TestClient(app, base_url='http://localhost', headers={'X-Aurion-Request': '1'}) as client:
            yield client, engine
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def login(client, username='alice', **extra):
    return client.post('/api/auth/dev', json={
        'username': username, 'token': 'synthetic-development-key', **extra,
    })


def test_session_login_restore_logout_and_invalid_login(auth_client):
    c, engine = auth_client
    assert c.get('/api/portfolios').status_code == 401
    assert login(c, token='wrong').status_code == 401
    result = login(c).json()
    assert result['user']['display_name'] == 'alice'
    assert result['households'][0]['role'] == 'OWNER'
    assert c.get('/api/auth/me').json() == result
    cookie = c.cookies.get('aurion_session')
    with Session(engine) as session:
        assert session.scalar(select(AuthSession)).token_hash != cookie
        assert len(list(session.scalars(select(User)))) == 1
    assert c.post('/api/auth/logout').status_code == 204
    assert c.get('/api/auth/me').status_code == 401
    c.cookies.set('aurion_session', cookie)
    assert c.get('/api/auth/me').status_code == 401
    assert login(c).json()['user']['id'] == result['user']['id']


def test_session_exposes_only_current_users_linked_identity_metadata(auth_client, monkeypatch):
    from src.auth.providers import ProviderIdentity
    c, engine = auth_client
    alice = login(c).json()
    assert alice['user']['identities'] == [
        {'provider': 'LOCAL', 'email': None, 'email_verified': False},
    ]
    # An email on a local identity must not imply a linked Google account.
    with Session(engine) as session:
        local = session.scalar(select(AuthIdentity).where(AuthIdentity.user_id == alice['user']['id']))
        local.email = 'alice@gmail.com'
        session.commit()
    assert [i['provider'] for i in c.get('/api/auth/me').json()['user']['identities']] == ['LOCAL']
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'synthetic.apps.googleusercontent.com')
    monkeypatch.setattr('src.auth.providers.verify_google', lambda credential, nonce: ProviderIdentity(
        'GOOGLE', 'private-provider-subject', 'Google Alice', 'alice@gmail.com', True))
    c.get('/api/auth/config')
    linked = c.post('/api/auth/google/link', json={'credential': 'synthetic-credential'}).json()
    assert linked['user']['id'] == alice['user']['id']
    assert linked['households'] == alice['households']
    assert linked['user']['identities'] == [
        {'provider': 'LOCAL', 'email': 'alice@gmail.com', 'email_verified': False},
        {'provider': 'GOOGLE', 'email': 'alice@gmail.com', 'email_verified': True},
    ]
    assert c.get('/api/auth/me').json() == linked
    assert login(c, 'bob').json()['user']['identities'] == [
        {'provider': 'LOCAL', 'email': None, 'email_verified': False},
    ]


def test_pending_invitation_list_is_private_filtered_and_contains_no_tokens(auth_client):
    c, engine = auth_client
    assert c.get('/api/households/1/invitations').status_code == 401
    alice = login(c).json()
    hid = alice['households'][0]['id']
    invitations = [c.post(f'/api/households/{hid}/invitations', json={
        'email': f'invited{i}@gmail.com', 'role': 'EDITOR',
    }).json() for i in range(4)]
    other = c.post('/api/households', json={'name': 'Other'}).json()['id']
    c.post(f'/api/households/{other}/invitations', json={'email': 'other@gmail.com', 'role': 'OWNER'})
    with Session(engine) as session:
        session.get(HouseholdInvitation, invitations[1]['id']).status = 'ACCEPTED'
        session.get(HouseholdInvitation, invitations[2]['id']).status = 'REVOKED'
        session.get(HouseholdInvitation, invitations[3]['id']).expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
    result = c.get(f'/api/households/{hid}/invitations')
    assert result.status_code == 200
    pending = result.json()
    assert len(pending) == 1
    assert set(pending[0]) == {'id', 'email', 'role', 'expires_at'}
    assert {key: pending[0][key] for key in ('id', 'email', 'role')} == {
        key: invitations[0][key] for key in ('id', 'email', 'role')}
    # SQLite's test adapter drops timezone metadata; PostgreSQL retains it.
    assert datetime.fromisoformat(pending[0]['expires_at']).replace(tzinfo=timezone.utc) == datetime.fromisoformat(
        invitations[0]['expires_at'])
    assert c.delete(f"/api/households/{hid}/invitations/{invitations[0]['id']}").status_code == 204
    assert c.get(f'/api/households/{hid}/invitations').json() == []
    bob = login(c, 'bob').json()
    assert c.get(f'/api/households/{hid}/invitations').status_code == 404
    with Session(engine) as session:
        member = Membership(user_id=bob['user']['id'], household_id=hid, role='EDITOR')
        session.add(member)
        session.commit()
        member_id = member.id
    for role in ('EDITOR', 'VIEWER'):
        with Session(engine) as session:
            session.get(Membership, member_id).role = role
            session.commit()
        assert c.get(f'/api/households/{hid}/invitations').status_code == 403


def test_cookie_rotation_disabled_users_and_expiration(auth_client):
    c, engine = auth_client
    uid = login(c).json()['user']['id']
    assert login(c).status_code == 200
    with Session(engine) as session:
        assert len(list(session.scalars(select(AuthSession)))) == 1
        user = session.get(User, uid)
        user.active = False
        session.commit()
    assert c.get('/api/portfolios').status_code == 401
    assert login(c).status_code == 401
    with Session(engine) as session:
        session.get(User, uid).active = True
        session.scalar(select(AuthSession)).expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
    assert c.get('/api/auth/me').status_code == 401


def test_csrf_origin_dev_configuration_and_impersonation(auth_client, monkeypatch):
    c, _ = auth_client
    assert c.post('/api/auth/dev', json={'username': 'alice', 'token': 'x'},
                  headers={'X-Aurion-Request': ''}).status_code == 403
    assert c.post('/api/auth/dev', json={}, headers={'Origin': 'https://evil.example'}).status_code == 403
    monkeypatch.setenv('DEV_AUTH_ENABLED', '0')
    assert login(c).status_code == 404
    monkeypatch.setenv('DEV_AUTH_ENABLED', '1')
    assert login(c, user_id=123).status_code == 422


def test_spaces_roles_shared_records_and_revocation(auth_client):
    c, engine = auth_client
    alice = login(c).json()
    family = c.post('/api/households', json={'name': 'Family'}).json()
    c.headers['X-Household-ID'] = str(family['id'])
    p = c.post('/api/portfolios', json={'name': 'Shared'}).json()
    assert p['household_id'] == family['id']
    bob = login(c, 'bob').json()
    assert c.get(f"/api/portfolios/{p['id']}/transactions").status_code == 404
    with Session(engine) as session:
        member = Membership(user_id=bob['user']['id'], household_id=family['id'], role='EDITOR')
        session.add(member)
        session.commit()
        member_id = member.id
    assert len(c.get('/api/auth/me').json()['households']) == 2
    assert c.put(f"/api/portfolios/{p['id']}", json={'name': 'Edited by Bob'}).status_code == 200
    assert c.put(f"/api/households/{family['id']}", json={'name': 'Forbidden'}).status_code == 403
    with Session(engine) as session:
        session.get(Membership, member_id).role = 'VIEWER'
        session.commit()
    assert c.put(f"/api/portfolios/{p['id']}", json={'name': 'Forbidden'}).status_code == 403
    assert c.get('/api/portfolios').json()[0]['name'] == 'Edited by Bob'
    with Session(engine) as session:
        session.delete(session.get(Membership, member_id))
        session.commit()
    assert c.get(f"/api/portfolios/{p['id']}/transactions").status_code == 404
    login(c)
    assert c.get('/api/portfolios').json()[0]['name'] == 'Edited by Bob'
    assert c.put(f"/api/households/{family['id']}", json={'name': 'Our Family'}).status_code == 200
    c.headers['X-Household-ID'] = str(alice['households'][0]['id'])
    assert c.get('/api/portfolios').json() == []


@pytest.mark.parametrize('suffix,method', [
    ('/transactions', 'get'), ('/transactions/999', 'delete'),
    ('/assets/999/quote', 'get'), ('/assets/999/corporate-events', 'get'),
    ('/assets/999/corporate-events/999', 'delete'), ('/transactions/import-preview', 'post'),
    ('/fixed-income/lots', 'get'), ('/fixed-income/lots/999/movements', 'get'),
    ('/history', 'get'), ('/performance', 'get'), ('/consolidate', 'post'),
])
def test_indirect_resource_paths_cannot_cross_spaces(auth_client, suffix, method):
    c, _ = auth_client
    login(c)
    pid = c.post('/api/portfolios', json={'name': 'Private'}).json()['id']
    login(c, 'bob')
    assert getattr(c, method)(f'/api/portfolios/{pid}' + suffix).status_code == 404
    assert c.get('/api/portfolios').json() == []
    assert c.get(f'/api/instruments/search?q=ABC&portfolio_id={pid}').status_code == 404


def test_private_instruments_cannot_be_selected_or_resolved_across_spaces(auth_client):
    c, _ = auth_client
    login(c)
    instrument = c.post('/api/instruments/custom', json={
        'symbol': 'PRIVATE', 'name': 'Alice contract', 'asset_type': 'OTHER', 'currency': 'BRL',
    }).json()
    login(c, 'bob')
    pid = c.post('/api/portfolios', json={'name': 'Bob'}).json()['id']
    payload = {'asset': 'PRIVATE', 'instrument_id': instrument['id'], 'type': 'Buy',
               'trade_date': '2024-01-02', 'settlement_date': '2024-01-02',
               'broker': 'A', 'quantity': 1, 'price': 1, 'transaction_currency': 'BRL'}
    assert c.post(f'/api/portfolios/{pid}/transactions', json=payload).status_code == 404
    payload.pop('instrument_id')
    assert c.post(f'/api/portfolios/{pid}/transactions', json=payload).status_code == 422
    own = c.post('/api/instruments/custom', json={
        'symbol': 'PRIVATE', 'name': 'Bob contract', 'asset_type': 'OTHER', 'currency': 'BRL',
    })
    assert own.status_code == 201
    assert own.json()['id'] != instrument['id']


def test_migrated_private_instruments_remain_searchable_only_in_their_space(auth_client):
    from src.models import Instrument
    c, engine = auth_client
    alice = login(c).json()
    hid = alice['households'][0]['id']
    with Session(engine) as session:
        instrument = Instrument(symbol='LEGACY-PRIVATE', name='Retained investment',
                                asset_type='OTHER', currency='BRL', origin='MIGRATED', household_id=hid)
        session.add(instrument)
        session.commit()
        iid = instrument.id
    results = c.get('/api/instruments/search?q=LEGACY-PRIVATE').json()
    assert [row['instrument_id'] for row in results] == [iid]
    login(c, 'bob')
    assert c.get('/api/instruments/search?q=LEGACY-PRIVATE').json() == []


def test_invitations_verified_identity_single_use_and_last_owner(auth_client, monkeypatch):
    c, engine = auth_client
    alice = login(c).json()
    hid = alice['households'][0]['id']
    invite = c.post(f'/api/households/{hid}/invitations', json={
        'email': 'bob@example.com', 'role': 'EDITOR',
    }).json()
    bob = login(c, 'bob').json()
    assert c.post('/api/invitations/accept', json={'token': invite['token']}).status_code == 403
    with Session(engine) as session:
        identity = session.scalar(select(AuthIdentity).where(AuthIdentity.provider_subject == 'bob'))
        identity.email = 'bob@example.com'
        identity.email_verified = True
        session.commit()
    accepted = c.post('/api/invitations/accept', json={'token': invite['token']})
    assert accepted.status_code == 200
    assert accepted.json()['id'] == hid
    assert c.get('/api/auth/me').json()['households'] == [
        {'id': hid, 'name': alice['households'][0]['name'], 'role': 'EDITOR',
         'member_count': 2, 'portfolio_count': 0, 'status': 'ACTIVE'},
        *bob['households'],
    ]
    assert c.post('/api/invitations/accept', json={'token': invite['token']}).status_code == 404
    login(c)
    members = c.get(f'/api/households/{hid}/members').json()
    owner = next(x for x in members if x['role'] == 'OWNER')
    assert c.delete(f"/api/households/{hid}/members/{owner['id']}").status_code == 409
    assert c.put(f"/api/households/{hid}/members/{owner['id']}", json={'role': 'VIEWER'}).status_code == 409


def test_owner_membership_changes_refresh_roles_and_revoke_access(auth_client):
    c, engine = auth_client
    alice = login(c).json()
    hid = alice['households'][0]['id']
    bob = login(c, 'bob').json()
    with Session(engine) as session:
        member = Membership(user_id=bob['user']['id'], household_id=hid, role='EDITOR')
        session.add(member)
        session.commit()
        member_id = member.id
    login(c)
    assert c.put(f'/api/households/{hid}/members/{member_id}', json={'role': 'OWNER'}).status_code == 200
    members = c.get(f'/api/households/{hid}/members').json()
    assert next(m for m in members if m['id'] == member_id)['role'] == 'OWNER'
    own = next(m for m in members if m['user_id'] == alice['user']['id'])
    assert c.put(f"/api/households/{hid}/members/{own['id']}", json={'role': 'VIEWER'}).status_code == 200
    assert c.get('/api/auth/me').json()['households'][0]['role'] == 'VIEWER'
    assert c.get(f'/api/households/{hid}/members').status_code == 200
    login(c, 'bob')
    assert c.delete(f"/api/households/{hid}/members/{own['id']}").status_code == 204
    assert len(c.get('/api/auth/me').json()['households']) == 2
    assert login(c).json()['households'] == []
    assert c.get(f'/api/households/{hid}/members').status_code == 404


@pytest.mark.parametrize('role', ['EDITOR', 'VIEWER'])
def test_members_can_view_roster_without_administration_permissions(auth_client, role):
    c, engine = auth_client
    alice = login(c).json()
    hid = alice['households'][0]['id']
    bob = login(c, 'bob').json()
    assert c.get(f'/api/households/{hid}/members').status_code == 404
    with Session(engine) as session:
        member = Membership(user_id=bob['user']['id'], household_id=hid, role=role)
        session.add(member)
        session.commit()
        member_id = member.id
    roster = c.get(f'/api/households/{hid}/members')
    assert roster.status_code == 200
    assert [(m['display_name'], m['role']) for m in roster.json()] == [('alice', 'OWNER'), ('bob', role)]
    assert c.put(f'/api/households/{hid}/members/{member_id}', json={'role': 'OWNER'}).status_code == 403
    assert c.delete(f'/api/households/{hid}/members/{member_id}').status_code == 403
    assert c.get(f'/api/households/{hid}/invitations').status_code == 403
    with Session(engine) as session:
        session.delete(session.get(Membership, member_id))
        session.commit()
    assert c.get(f'/api/households/{hid}/members').status_code == 404


def test_google_verified_subject_resolution_and_linking(auth_client, monkeypatch):
    from src.auth.providers import ProviderIdentity
    c, engine = auth_client
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'synthetic.apps.googleusercontent.com')
    monkeypatch.setattr('src.auth.providers.verify_google', lambda credential, nonce: ProviderIdentity(
        'GOOGLE', credential, 'Google Alice', 'alice@example.com', True))
    def google(subject, path='/api/auth/google'):
        c.get('/api/auth/config')
        return c.post(path, json={'credential': subject})
    first = google('stable-subject').json()
    assert first['households'][0]['role'] == 'OWNER'
    c.post('/api/auth/logout')
    assert google('stable-subject').json()['user']['id'] == first['user']['id']
    assert google('other-subject').json()['user']['id'] != first['user']['id']
    local = login(c).json()
    assert google('new-linked-subject', '/api/auth/google/link').json()['user']['id'] == local['user']['id']
    c.post('/api/auth/logout')
    assert google('new-linked-subject').json()['user']['id'] == local['user']['id']


def test_google_nonce_is_single_use_and_identity_link_conflicts(auth_client, monkeypatch):
    from src.auth.providers import ProviderIdentity
    c, _ = auth_client
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'synthetic.apps.googleusercontent.com')
    monkeypatch.setattr('src.auth.providers.verify_google', lambda credential, nonce: ProviderIdentity(
        'GOOGLE', credential, 'Google user'))
    c.get('/api/auth/config')
    nonce = c.cookies.get('aurion_challenge')
    assert c.post('/api/auth/google', json={'credential': 'subject'}).status_code == 200
    c.cookies.set('aurion_challenge', nonce)
    assert c.post('/api/auth/google', json={'credential': 'subject'}).status_code == 401
    c.cookies.delete('aurion_challenge', domain='', path='/')
    login(c)
    c.get('/api/auth/config')
    assert c.post('/api/auth/google/link', json={'credential': 'subject'}).status_code == 409


def test_google_rejects_invalid_and_replayed_challenges(auth_client, monkeypatch):
    c, _ = auth_client
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'synthetic.apps.googleusercontent.com')
    assert c.post('/api/auth/google', json={'credential': 'invalid'}).status_code == 401
    c.get('/api/auth/config')
    def invalid(*args):
        raise ValueError('Invalid token')
    monkeypatch.setattr('src.auth.providers.verify_google', invalid)
    assert c.post('/api/auth/google', json={'credential': 'invalid'}).status_code == 401


def test_secure_cookie_flags_and_tampered_session(auth_client, monkeypatch):
    c, _ = auth_client
    monkeypatch.setenv('SESSION_COOKIE_SECURE', '1')
    result = login(c)
    cookie = result.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'Secure' in cookie and 'SameSite=lax' in cookie and 'Path=/api' in cookie
    assert 'no-store' in result.headers['cache-control']
    c.cookies.clear()
    c.cookies.set('aurion_session', 'tampered')
    assert c.get('/api/auth/me').status_code == 401


def test_expired_revoked_invitations_and_nonowner_admin(auth_client):
    c, engine = auth_client
    alice = login(c).json()
    hid = alice['households'][0]['id']
    invitations = [c.post(f'/api/households/{hid}/invitations', json={
        'email': 'bob@gmail.com', 'role': 'VIEWER',
    }).json() for _ in range(2)]
    with Session(engine) as session:
        session.get(HouseholdInvitation, invitations[0]['id']).expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        assert session.get(HouseholdInvitation, invitations[1]['id']).token_hash != invitations[1]['token']
        session.commit()
    assert c.delete(f"/api/households/{hid}/invitations/{invitations[1]['id']}").status_code == 204
    bob = login(c, 'bob').json()
    with Session(engine) as session:
        session.add(Membership(user_id=bob['user']['id'], household_id=hid, role='EDITOR'))
        identity = session.scalar(select(AuthIdentity).where(AuthIdentity.provider_subject == 'bob'))
        identity.email, identity.email_verified = 'bob@gmail.com', True
        session.commit()
    for invitation in invitations:
        assert c.post('/api/invitations/accept', json={'token': invitation['token']}).status_code == 404
    assert c.post(f'/api/households/{hid}/invitations', json={'email': 'eve@gmail.com', 'role': 'OWNER'}).status_code == 403
    assert c.get(f'/api/households/{hid}/members').status_code == 200


def test_actual_nested_ids_and_shared_financial_edits(auth_client):
    from src.models import Asset, Instrument, TransactionImport, UserDefinedPrice
    c, engine = auth_client
    alice = login(c).json()
    hid = alice['households'][0]['id']
    pid = c.post('/api/portfolios', json={'name': 'Alice'}).json()['id']
    with Session(engine) as session:
        instrument = Instrument(symbol='PUBLIC', asset_type='STOCK', currency='BRL', origin='CATALOG')
        session.add(instrument)
        session.commit()
        iid = instrument.id
    payload = {'asset': 'PUBLIC', 'instrument_id': iid, 'type': 'Buy', 'trade_date': '2024-01-02',
               'settlement_date': '2024-01-02', 'broker': 'A', 'quantity': 2, 'price': 10,
               'transaction_currency': 'BRL'}
    tx = c.post(f'/api/portfolios/{pid}/transactions', json=payload).json()
    with Session(engine) as session:
        aid = session.scalar(select(Asset.id).where(Asset.portfolio_id == pid))
    assert c.put(f'/api/portfolios/{pid}/assets/{aid}/quote', json={'date': '2024-01-02', 'close': 12}).status_code == 200
    event = c.post(f'/api/portfolios/{pid}/assets/{aid}/corporate-events', json={
        'event_type': 'DIVIDEND', 'effective_date': '2024-01-03', 'amount_per_unit': 1, 'currency': 'BRL',
    }).json()
    imported = c.post(f'/api/portfolios/{pid}/transactions/import', json={
        'digest': 'a' * 64, 'filename': 'synthetic.csv', 'rows': [payload],
    })
    assert imported.status_code == 201, imported.text
    bob = login(c, 'bob').json()
    bpid = c.post('/api/portfolios', json={'name': 'Bob'}).json()['id']
    assert c.post(f'/api/portfolios/{bpid}/transactions', json=payload).status_code == 201
    with Session(engine) as session:
        baid = session.scalar(select(Asset.id).where(Asset.portfolio_id == bpid))
    assert c.delete(f"/api/portfolios/{bpid}/transactions/{tx['id']}").status_code == 404
    assert c.delete(f"/api/portfolios/{bpid}/assets/{baid}/corporate-events/{event['id']}").status_code == 404
    assert c.get(f'/api/portfolios/{bpid}/assets/{aid}/history').status_code == 404
    assert c.put(f'/api/portfolios/{bpid}/assets/{aid}/quote', json={'date': '2024-01-02', 'close': 999}).status_code == 404
    assert c.post(f'/api/portfolios/{pid}/transactions/import', json={
        'digest': 'a' * 64, 'filename': 'synthetic.csv', 'rows': [payload],
    }).status_code == 404
    with Session(engine) as session:
        session.add(Membership(user_id=bob['user']['id'], household_id=hid, role='EDITOR'))
        assert session.scalar(select(UserDefinedPrice).where(UserDefinedPrice.asset_id == aid)).price == 12
        assert session.scalar(select(TransactionImport).where(TransactionImport.portfolio_id == pid)) is not None
        session.commit()
    updated = c.put(f"/api/portfolios/{pid}/transactions/{tx['id']}", json={**payload, 'price': 15})
    assert updated.status_code == 200, updated.text
    login(c)
    from decimal import Decimal
    records = c.get(f'/api/portfolios/{pid}/transactions').json()
    assert Decimal(next(row for row in records if row['id'] == tx['id'])['price']) == 15
