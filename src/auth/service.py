"""Server-validated opaque sessions and provider-independent user provisioning."""
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import delete, select

from src.models import AuthIdentity, AuthSession, Household, Membership, User

SESSION_COOKIE = 'aurion_session'
CHALLENGE_COOKIE = 'aurion_challenge'
SESSION_SECONDS = 7 * 24 * 60 * 60


def now():
    return datetime.now(timezone.utc)


def expired(value):
    return value.replace(tzinfo=timezone.utc) <= now() if value.tzinfo is None else value <= now()


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def cookie_options():
    return {'httponly': True, 'secure': os.getenv('SESSION_COOKIE_SECURE', '1') != '0',
            'samesite': 'lax', 'path': '/api/auth'}


def dev_enabled():
    return os.getenv('DEV_AUTH_ENABLED') == '1' and bool(os.getenv('DEV_AUTH_TOKEN'))


def create_household(session, user, name):
    household = Household(name=name)
    session.add(household)
    session.flush()
    session.add(Membership(user_id=user.id, household_id=household.id, role='OWNER'))
    session.flush()
    return household


def resolve_identity(session, identity, *, link_user=None):
    existing = session.scalar(select(AuthIdentity).where(
        AuthIdentity.provider == identity.provider, AuthIdentity.provider_subject == identity.subject))
    if existing is not None:
        if link_user is not None and link_user.id != existing.user_id:
            raise HTTPException(409, 'Identity already linked to another user.')
        user = session.get(User, existing.user_id)
        existing.email = identity.email
        existing.email_verified = identity.email_verified
    else:
        user = link_user
        if user is None:
            user = User(display_name=identity.display_name[:120])
            session.add(user)
            session.flush()
            create_household(session, user, user.display_name)
        session.add(AuthIdentity(user_id=user.id, provider=identity.provider,
                                 provider_subject=identity.subject, email=identity.email,
                                 email_verified=identity.email_verified))
    if not user.active:
        raise HTTPException(401, 'User is disabled.')
    session.flush()
    return user


def session_data(session, user):
    rows = session.execute(select(Household, Membership.role).join(
        Membership, Membership.household_id == Household.id).where(
        Membership.user_id == user.id).order_by(Household.id))
    identities = session.scalars(select(AuthIdentity).where(
        AuthIdentity.user_id == user.id).order_by(AuthIdentity.id))
    return {'user': {'id': user.id, 'display_name': user.display_name,
                     'identities': [{'provider': identity.provider, 'email': identity.email,
                                     'email_verified': identity.email_verified} for identity in identities]},
            'households': [{'id': h.id, 'name': h.name, 'role': role} for h, role in rows]}


def establish_session(session, request, response, user):
    old = request.cookies.get(SESSION_COOKIE)
    if old:
        session.execute(delete(AuthSession).where(AuthSession.token_hash == digest(old)))
    session.execute(delete(AuthSession).where(AuthSession.expires_at <= now()))
    token = secrets.token_urlsafe(32)
    session.add(AuthSession(user_id=user.id, token_hash=digest(token),
                            expires_at=now() + timedelta(seconds=SESSION_SECONDS)))
    session.commit()
    options = cookie_options() | {'path': '/api'}
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_SECONDS, **options)
    return session_data(session, user)
