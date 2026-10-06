"""Seed a real backend session for existing financial regression fixtures."""
import secrets
from datetime import timedelta

from src.auth.providers import ProviderIdentity
from src.auth.service import SESSION_COOKIE, digest, now, resolve_identity
from src.models import AuthSession


def authenticate(client, session):
    user = resolve_identity(session, ProviderIdentity('LOCAL', 'local', 'Local user'))
    token = secrets.token_urlsafe(32)
    session.add(AuthSession(user_id=user.id, token_hash=digest(token), expires_at=now() + timedelta(days=1)))
    session.commit()
    client.cookies.set(SESSION_COOKIE, token)
    client.headers['X-Aurion-Request'] = '1'
