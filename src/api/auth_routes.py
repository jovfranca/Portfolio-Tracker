"""Login, logout and restoration of backend-authenticated application sessions."""
import os
import secrets
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from src.auth import providers
from src.auth.dependencies import CurrentUser, DB
from src.auth.service import (
    CHALLENGE_COOKIE, SESSION_COOKIE, cookie_options, dev_enabled, digest,
    establish_session, expired, now, resolve_identity, session_data,
)
from src.models import AuthChallenge, AuthSession

router = APIRouter(prefix='/api/auth')


class DevLogin(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=1, max_length=120, pattern=r'^[a-zA-Z0-9_.-]+$')
    token: str = Field(min_length=1, max_length=1024)


class GoogleLogin(BaseModel):
    model_config = ConfigDict(extra='forbid')
    credential: str = Field(min_length=1, max_length=16384)


@router.get('/config')
def auth_config(request: Request, response: Response, session: DB):
    response.headers['Cache-Control'] = 'no-store'
    client_id = os.getenv('GOOGLE_CLIENT_ID', '').strip()
    nonce = None
    if client_id:
        old = request.cookies.get(CHALLENGE_COOKIE)
        if old:
            session.execute(delete(AuthChallenge).where(AuthChallenge.token_hash == digest(old)))
        session.execute(delete(AuthChallenge).where(AuthChallenge.expires_at <= now()))
        nonce = secrets.token_urlsafe(32)
        session.add(AuthChallenge(token_hash=digest(nonce), expires_at=now() + timedelta(minutes=10)))
        session.commit()
        response.set_cookie(CHALLENGE_COOKIE, nonce, max_age=600, **cookie_options())
    return {'google_client_id': client_id or None, 'google_nonce': nonce,
            'dev_enabled': dev_enabled() and request.url.hostname in {'localhost', '127.0.0.1', '::1'}}


@router.get('/me')
def me(response: Response, session: DB, user: CurrentUser):
    response.headers['Cache-Control'] = 'no-store'
    return session_data(session, user)


def provision(session, identity, *, link_user=None):
    try:
        with session.begin_nested():
            return resolve_identity(session, identity, link_user=link_user)
    except IntegrityError:
        # Concurrent first logins converge on the unique provider/subject identity.
        return resolve_identity(session, identity, link_user=link_user)


@router.post('/dev')
def dev_login(payload: DevLogin, request: Request, response: Response, session: DB):
    if not dev_enabled() or request.url.hostname not in {'localhost', '127.0.0.1', '::1'}:
        raise HTTPException(404, 'Development authentication is disabled.')
    if not secrets.compare_digest(payload.token.encode('utf-8'), os.environ['DEV_AUTH_TOKEN'].encode('utf-8')):
        raise HTTPException(401, 'Invalid development credentials.')
    user = provision(session, providers.ProviderIdentity('LOCAL', payload.username, payload.username))
    return establish_session(session, request, response, user)


def google_identity(payload: GoogleLogin, request: Request, session: DB):
    if not os.getenv('GOOGLE_CLIENT_ID'):
        raise HTTPException(503, 'Google authentication is not configured.')
    nonce = request.cookies.get(CHALLENGE_COOKIE)
    challenge = session.scalar(select(AuthChallenge).where(
        AuthChallenge.token_hash == digest(nonce)).with_for_update()) if nonce else None
    if challenge is None or expired(challenge.expires_at):
        raise HTTPException(401, 'Google login challenge expired. Reload the login screen.')
    try:
        identity = providers.verify_google(payload.credential, nonce)
    except ValueError:
        raise HTTPException(401, 'Invalid Google credentials.') from None
    except Exception:
        # Provider exceptions can contain token-bearing request information; never return/log them.
        raise HTTPException(503, 'Google identity verification is unavailable.') from None
    session.delete(challenge)
    session.flush()
    return identity


VerifiedGoogle = Annotated[providers.ProviderIdentity, Depends(google_identity)]


@router.post('/google')
def google_login(request: Request, response: Response, session: DB, identity: VerifiedGoogle):
    user = provision(session, identity)
    response.delete_cookie(CHALLENGE_COOKIE, **cookie_options())
    return establish_session(session, request, response, user)


@router.post('/google/link')
def link_google(request: Request, response: Response, session: DB, user: CurrentUser, identity: VerifiedGoogle):
    provision(session, identity, link_user=user)
    response.delete_cookie(CHALLENGE_COOKIE, **cookie_options())
    return establish_session(session, request, response, user)


@router.post('/logout', status_code=204)
def logout(request: Request, response: Response, session: DB):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        session.execute(delete(AuthSession).where(AuthSession.token_hash == digest(token)))
    session.commit()
    response.delete_cookie(SESSION_COOKIE, **(cookie_options() | {'path': '/api'}))
