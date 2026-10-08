"""Authenticated regressions for the four functional acceptance gaps in #41."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models import AuthIdentity, HouseholdInvitation, Membership, Portfolio, Transaction
from tests.test_auth import auth_client, login


def invitation_for_guest(client, engine, role='VIEWER'):
    owner = login(client).json()
    hid = owner['households'][0]['id']
    portfolio = client.post('/api/portfolios', json={'name': 'Shared records'}).json()
    iid = client.post('/api/instruments/custom', json={
        'symbol': 'SHARED-RECORD', 'name': 'Synthetic shared holding', 'currency': 'BRL',
    }).json()['id']
    assert client.post(f"/api/portfolios/{portfolio['id']}/transactions", json={
        'asset': 'SHARED-RECORD', 'instrument_id': iid, 'type': 'Buy', 'broker': 'Synthetic',
        'trade_date': '2024-01-02', 'settlement_date': '2024-01-02',
        'quantity': '2', 'price': '10', 'transaction_currency': 'BRL',
    }).status_code == 201
    invitation = client.post(f'/api/households/{hid}/invitations', json={
        'email': 'guest@example.com', 'role': role,
    }).json()
    guest = login(client, 'guest').json()
    with Session(engine) as session:
        identity = session.scalar(select(AuthIdentity).where(AuthIdentity.user_id == guest['user']['id']))
        identity.email, identity.email_verified = 'guest@example.com', True
        session.commit()
    return owner, guest, portfolio, invitation


def test_invitation_preview_rejection_is_persistent_and_grants_no_membership(auth_client):
    client, engine = auth_client
    assert client.post('/api/invitations/preview', json={'token': 'invalid'}).status_code == 401
    owner, guest, portfolio, invitation = invitation_for_guest(client, engine)
    payload = {'token': invitation['token']}
    preview = client.post('/api/invitations/preview', json=payload)
    assert preview.status_code == 200
    data = preview.json()
    assert data['space'] == {'id': portfolio['household_id'], 'name': 'alice'}
    assert data['inviter'] == {'id': owner['user']['id'], 'display_name': 'alice'}
    assert (data['email'], data['role'], data['status']) == ('guest@example.com', 'VIEWER', 'PENDING')
    assert data['expires_at'] and data['created_at']
    assert 'token_hash' not in data and 'token' not in data
    rejected = client.post('/api/invitations/reject', json=payload)
    assert rejected.status_code == 200
    assert rejected.json()['status'] == 'REJECTED'
    assert client.post('/api/invitations/preview', json=payload).json()['status'] == 'REJECTED'
    assert client.post('/api/invitations/accept', json=payload).status_code == 404
    assert client.post('/api/invitations/reject', json=payload).status_code == 404
    assert client.get('/api/auth/me').json()['households'] == guest['households']
    with Session(engine) as session:
        saved = session.get(HouseholdInvitation, invitation['id'])
        assert saved.status == 'REJECTED' and saved.resolved_at is not None
        assert saved.resolved_by_user_id == guest['user']['id']
        assert session.scalar(select(func.count()).select_from(Portfolio)) == 1
        assert session.scalar(select(func.count()).select_from(Transaction)) == 1
    login(client)
    hid = portfolio['household_id']
    assert client.get(f'/api/households/{hid}/invitations').json() == []
    assert client.delete(f"/api/households/{hid}/invitations/{invitation['id']}").status_code == 409


@pytest.mark.parametrize('terminal', ['ACCEPTED', 'REVOKED', 'EXPIRED'])
def test_invitation_terminal_states_and_invalid_token(auth_client, terminal):
    client, engine = auth_client
    owner, guest, portfolio, invitation = invitation_for_guest(client, engine, 'EDITOR')
    payload = {'token': invitation['token']}
    if terminal == 'ACCEPTED':
        assert client.post('/api/invitations/accept', json=payload).status_code == 200
        shared = client.get('/api/auth/me').json()['households'][0]
        assert shared['role'] == 'EDITOR' and shared['member_count'] == 2
        assert shared['portfolio_count'] == 1 and shared['status'] == 'ACTIVE'
        records = client.get(f"/api/portfolios/{portfolio['id']}/transactions").json()
        assert len(records) == 1 and records[0]['asset'] == 'SHARED-RECORD'
    elif terminal == 'REVOKED':
        login(client)
        assert client.delete(f"/api/households/{portfolio['household_id']}/invitations/{invitation['id']}").status_code == 204
        login(client, 'guest')
        with Session(engine) as session:
            identity = session.scalar(select(AuthIdentity).where(AuthIdentity.user_id == guest['user']['id']))
            identity.email, identity.email_verified = 'guest@example.com', True
            session.commit()
    else:
        with Session(engine) as session:
            session.get(HouseholdInvitation, invitation['id']).expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            session.commit()
    assert client.post('/api/invitations/preview', json=payload).json()['status'] == terminal
    assert client.post('/api/invitations/accept', json=payload).status_code == 404
    assert client.post('/api/invitations/reject', json=payload).status_code == 404
    assert client.post('/api/invitations/preview', json={'token': 'invalid'}).status_code == 404
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Portfolio)) == 1
        assert session.scalar(select(func.count()).select_from(Transaction)) == 1
        count = session.scalar(select(func.count()).select_from(Membership).where(
            Membership.household_id == portfolio['household_id'], Membership.user_id == guest['user']['id']))
        assert count == (1 if terminal == 'ACCEPTED' else 0)


def test_preview_and_reject_require_matching_verified_identity(auth_client):
    client, engine = auth_client
    _, guest, _, invitation = invitation_for_guest(client, engine)
    with Session(engine) as session:
        identity = session.scalar(select(AuthIdentity).where(AuthIdentity.user_id == guest['user']['id']))
        identity.email_verified = False
        session.commit()
    for action in ('preview', 'reject', 'accept'):
        assert client.post('/api/invitations/' + action, json={'token': invitation['token']}).status_code == 403
    login(client, 'stranger')
    for action in ('preview', 'reject', 'accept'):
        assert client.post('/api/invitations/' + action, json={'token': invitation['token']}).status_code == 403


def test_space_projection_counts_roles_status_without_multiplying_joined_counts(auth_client):
    client, engine = auth_client
    alice = login(client).json()
    hid = alice['households'][0]['id']
    for name in ('One', 'Two'):
        assert client.post('/api/portfolios', json={'name': name}).status_code == 201
    second = client.post('/api/households', json={'name': 'Second'}).json()
    bob = login(client, 'bob').json()
    with Session(engine) as session:
        session.add(Membership(user_id=bob['user']['id'], household_id=hid, role='VIEWER'))
        session.commit()
    result = client.get('/api/households').json()
    assert result[0] == {'id': hid, 'name': 'alice', 'role': 'VIEWER',
                         'member_count': 2, 'portfolio_count': 2, 'status': 'ACTIVE'}
    assert second['id'] not in {space['id'] for space in result}
    login(client)
    result = client.get('/api/auth/me').json()['households']
    assert result[0]['member_count'] == result[0]['portfolio_count'] == 2
    assert result[1] == {**second, 'member_count': 1, 'portfolio_count': 0, 'status': 'ACTIVE'}
