"""Central access checks, evaluated again on every authenticated request."""
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database import get_session
from src.models import AuthSession, Household, Membership, Portfolio, User
from src.auth.service import SESSION_COOKIE, digest, expired

DB = Annotated[Session, Depends(get_session)]
WRITE_ROLES = {'OWNER', 'EDITOR'}


def current_user(request: Request, session: DB):
    token = request.cookies.get(SESSION_COOKIE)
    saved = session.scalar(select(AuthSession).where(AuthSession.token_hash == digest(token))) if token else None
    user = session.get(User, saved.user_id) if saved is not None and not expired(saved.expires_at) else None
    if user is None or not user.active:
        raise HTTPException(401, 'Authentication required.')
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_household_access(session, user, household_id, *, roles=None, lock=False):
    # Lock the household for membership administration, serializing last-owner checks.
    if lock:
        session.scalar(select(Household).where(Household.id == household_id).with_for_update())
    membership = session.scalar(select(Membership).where(
        Membership.user_id == user.id, Membership.household_id == household_id))
    if membership is None:
        raise HTTPException(404, 'Financial space not found.')
    if roles is not None and membership.role not in roles:
        raise HTTPException(403, 'Insufficient financial-space permissions.')
    return membership


def selected_household(request, session, user):
    supplied = request.headers.get('X-Household-ID')
    if supplied:
        try:
            hid = int(supplied)
        except ValueError:
            raise HTTPException(422, 'Invalid financial-space identifier.') from None
        require_household_access(session, user, hid)
        return hid
    ids = list(session.scalars(select(Membership.household_id).where(
        Membership.user_id == user.id).order_by(Membership.household_id)))
    if not ids:
        raise HTTPException(404, 'Financial space not found.')
    if len(ids) > 1:
        raise HTTPException(422, 'Select a financial space.')
    return ids[0]


def financial_access(request: Request, session: DB, user: CurrentUser):
    portfolio_id = request.path_params.get('portfolio_id') or request.query_params.get('portfolio_id')
    write = request.method not in {'GET', 'HEAD', 'OPTIONS'}
    if portfolio_id is not None:
        try:
            portfolio = session.get(Portfolio, int(portfolio_id))
        except ValueError:
            raise HTTPException(422, 'Invalid portfolio identifier.') from None
        if portfolio is None:
            raise HTTPException(404, 'Portfolio not found.')
        membership = require_household_access(session, user, portfolio.household_id,
                                             roles=WRITE_ROLES if write else None)
        session.info['household_id'] = membership.household_id
    elif request.url.path in {'/api/portfolios', '/api/instruments/custom'} and write:
        hid = selected_household(request, session, user)
        require_household_access(session, user, hid, roles=WRITE_ROLES)
        session.info['household_id'] = hid
    else:
        session.info['household_ids'] = list(session.scalars(select(Membership.household_id).where(
            Membership.user_id == user.id)))
        if request.headers.get('X-Household-ID'):
            session.info['household_id'] = selected_household(request, session, user)
    return user
