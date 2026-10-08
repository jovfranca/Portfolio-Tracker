"""Real PostgreSQL concurrency coverage for financial-space invitations."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import os
from threading import Barrier, Event
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, event, select, text
from sqlalchemy.orm import Session

from src.api.household_routes import AcceptInput, accept_invite, reject_invite, revoke_invite
from src.auth.providers import ProviderIdentity
from src.auth.service import digest, now, resolve_identity
from src.database import engine
from src.models import AuthIdentity, Household, HouseholdInvitation, Membership, User

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.getenv('RUN_DB_TESTS') != '1', reason='Requires a migrated PostgreSQL test database.')]


@pytest.fixture
def invited_guest():
    suffix = uuid4().hex
    tokens = [uuid4().hex, uuid4().hex]
    with Session(engine) as session:
        owner = resolve_identity(session, ProviderIdentity('LOCAL', 'owner-' + suffix, 'Owner'))
        guest = resolve_identity(session, ProviderIdentity('GOOGLE', 'guest-' + suffix,
                                                        'Guest', suffix + '@gmail.com', True))
        hid = session.scalar(select(Membership.household_id).where(Membership.user_id == owner.id))
        guest_hid = session.scalar(select(Membership.household_id).where(Membership.user_id == guest.id))
        owner_id, guest_id = owner.id, guest.id
        for token in tokens:
            session.add(HouseholdInvitation(household_id=hid, email=suffix + '@gmail.com', role='EDITOR',
                                           token_hash=digest(token), expires_at=now() + timedelta(days=1)))
        session.commit()

    try:
        yield owner_id, guest_id, hid, tokens
    finally:
        # Only rows created by this case are removed; no financial records exist.
        with Session(engine) as session:
            for model, clause in (
                (HouseholdInvitation, HouseholdInvitation.household_id == hid),
                (Membership, Membership.user_id.in_([owner_id, guest_id])),
                (AuthIdentity, AuthIdentity.user_id.in_([owner_id, guest_id])),
                (User, User.id.in_([owner_id, guest_id])),
                (Household, Household.id.in_([hid, guest_hid])),
            ):
                session.execute(delete(model).where(clause))
            session.commit()


def test_concurrent_invitations_create_one_membership(invited_guest):
    _, guest_id, hid, tokens = invited_guest
    # Force both requests to begin together. A short database-side delay on the
    # membership lookup makes the pre-fix check-then-insert race reproducible.
    ready = Barrier(2)
    def accept(token):
        with engine.connect() as connection:
            def delay_membership(conn, cursor, statement, parameters, context, executemany):
                if statement.lstrip().startswith('SELECT memberships.'):
                    cursor.execute('SELECT pg_sleep(0.2)')
            event.listen(connection, 'before_cursor_execute', delay_membership)
            with Session(connection) as session:
                session.execute(text("SET LOCAL lock_timeout = '5s'"))
                guest = session.get(User, guest_id)
                ready.wait(timeout=5)
                return accept_invite(AcceptInput(token=token), session, guest)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(accept, tokens))
    assert all(row['id'] == hid and row['role'] == 'EDITOR' for row in results)
    with Session(engine) as session:
        memberships = list(session.scalars(select(Membership).where(
            Membership.household_id == hid, Membership.user_id == guest_id)))
        assert len(memberships) == 1
        assert list(session.scalars(select(HouseholdInvitation.status).where(
            HouseholdInvitation.household_id == hid))) == ['ACCEPTED', 'ACCEPTED']


def test_revocation_serializes_with_acceptance_without_deadlock(invited_guest):
    owner_id, guest_id, hid, tokens = invited_guest
    lookup_started = Event()
    def accept():
        with engine.connect() as connection:
            def invitation_lookup(conn, cursor, statement, parameters, context, executemany):
                if statement.lstrip().startswith('SELECT household_invitations.'):
                    lookup_started.set()
            event.listen(connection, 'after_cursor_execute', invitation_lookup)
            with Session(connection) as session:
                session.execute(text("SET LOCAL lock_timeout = '5s'"))
                guest = session.get(User, guest_id)
                try:
                    accept_invite(AcceptInput(token=tokens[0]), session, guest)
                except HTTPException as error:
                    return error.status_code
                return 200
    with ThreadPoolExecutor(max_workers=1) as pool:
        with Session(engine) as session:
            session.execute(text("SET LOCAL lock_timeout = '1s'"))
            session.scalar(select(Household).where(Household.id == hid).with_for_update())
            invitation_id = session.scalar(select(HouseholdInvitation.id).where(
                HouseholdInvitation.token_hash == digest(tokens[0])))
            owner = session.get(User, owner_id)
            attempt = pool.submit(accept)
            assert lookup_started.wait(timeout=5)
            revoke_invite(hid, invitation_id, session, owner)
        assert attempt.result(timeout=10) == 404
    with Session(engine) as session:
        assert session.scalar(select(Membership).where(
            Membership.household_id == hid, Membership.user_id == guest_id)) is None


def test_accept_and_reject_serialize_to_one_terminal_decision(invited_guest):
    _, guest_id, hid, tokens = invited_guest
    ready = Barrier(2)
    def decide(action):
        with Session(engine) as session:
            session.execute(text("SET LOCAL lock_timeout = '5s'"))
            guest = session.get(User, guest_id)
            ready.wait(timeout=5)
            try:
                action(AcceptInput(token=tokens[0]), session, guest)
                return 200
            except HTTPException as error:
                return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(decide, [accept_invite, reject_invite]))
    assert sorted(results) == [200, 404]
    with Session(engine) as session:
        invitation = session.scalar(select(HouseholdInvitation).where(
            HouseholdInvitation.token_hash == digest(tokens[0])))
        assert invitation.status in {'ACCEPTED', 'REJECTED'}
        assert invitation.resolved_at is not None and invitation.resolved_by_user_id == guest_id
        member = session.scalar(select(Membership).where(
            Membership.household_id == hid, Membership.user_id == guest_id))
        assert (member is not None) == (invitation.status == 'ACCEPTED')
