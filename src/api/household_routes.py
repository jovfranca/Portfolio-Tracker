"""Financial-space administration and token invitations (without email delivery)."""
import secrets
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select

from src.auth.dependencies import CurrentUser, DB, require_household_access
from src.auth.service import create_household, digest, expired, now, session_data
from src.models import AuthIdentity, Household, HouseholdInvitation, Membership, User

router = APIRouter(prefix='/api')
Role = Literal['OWNER', 'EDITOR', 'VIEWER']


class SpaceInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)


class RoleInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: Role


class InvitationInput(RoleInput):
    email: str = Field(min_length=3, max_length=254)

    @field_validator('email')
    @classmethod
    def normalize_email(cls, value):
        value = value.strip().lower()
        if value.count('@') != 1 or any(c.isspace() for c in value):
            raise ValueError('Invalid invitation email.')
        local, domain = value.split('@')
        if not local or '.' not in domain or domain.startswith('.') or domain.endswith('.'):
            raise ValueError('Invalid invitation email.')
        return value


class AcceptInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    token: str = Field(min_length=1, max_length=512)


def space_data(session, user, household_id):
    return next(h for h in session_data(session, user)['households'] if h['id'] == household_id)


@router.get('/households')
def households(session: DB, user: CurrentUser):
    return session_data(session, user)['households']


@router.post('/households', status_code=201)
def new_household(payload: SpaceInput, session: DB, user: CurrentUser):
    space = create_household(session, user, payload.name)
    session.commit()
    return space_data(session, user, space.id)


@router.put('/households/{household_id}')
def rename_household(household_id: int, payload: SpaceInput, session: DB, user: CurrentUser):
    require_household_access(session, user, household_id, roles={'OWNER'}, lock=True)
    session.get(Household, household_id).name = payload.name
    session.commit()
    return space_data(session, user, household_id)


@router.get('/households/{household_id}/members')
def members(household_id: int, session: DB, user: CurrentUser):
    require_household_access(session, user, household_id, roles={'OWNER'})
    rows = session.execute(select(Membership, User.display_name).join(User).where(
        Membership.household_id == household_id).order_by(Membership.id))
    return [{'id': m.id, 'user_id': m.user_id, 'display_name': name, 'role': m.role} for m, name in rows]


def editable_member(session, user, household_id, member_id, new_role=None):
    require_household_access(session, user, household_id, roles={'OWNER'}, lock=True)
    member = session.scalar(select(Membership).where(
        Membership.id == member_id, Membership.household_id == household_id))
    if member is None:
        raise HTTPException(404, 'Membership not found.')
    if member.role == 'OWNER' and new_role != 'OWNER':
        owners = session.scalar(select(func.count()).select_from(Membership).where(
            Membership.household_id == household_id, Membership.role == 'OWNER'))
        if owners <= 1:
            raise HTTPException(409, 'A financial space must retain an owner.')
    return member


@router.put('/households/{household_id}/members/{member_id}')
def change_role(household_id: int, member_id: int, payload: RoleInput, session: DB, user: CurrentUser):
    member = editable_member(session, user, household_id, member_id, payload.role)
    member.role = payload.role
    session.commit()
    return {'id': member.id, 'role': member.role}


@router.delete('/households/{household_id}/members/{member_id}', status_code=204)
def remove_member(household_id: int, member_id: int, session: DB, user: CurrentUser):
    session.delete(editable_member(session, user, household_id, member_id))
    session.commit()


@router.post('/households/{household_id}/invitations', status_code=201)
def invite(household_id: int, payload: InvitationInput, session: DB, user: CurrentUser):
    require_household_access(session, user, household_id, roles={'OWNER'}, lock=True)
    token = secrets.token_urlsafe(32)
    invitation = HouseholdInvitation(household_id=household_id, email=payload.email, role=payload.role,
                                     token_hash=digest(token), expires_at=now() + timedelta(days=7))
    session.add(invitation)
    session.commit()
    return {'id': invitation.id, 'token': token, 'expires_at': invitation.expires_at,
            'email': invitation.email, 'role': invitation.role}


@router.delete('/households/{household_id}/invitations/{invitation_id}', status_code=204)
def revoke_invite(household_id: int, invitation_id: int, session: DB, user: CurrentUser):
    require_household_access(session, user, household_id, roles={'OWNER'}, lock=True)
    invitation = session.scalar(select(HouseholdInvitation).where(
        HouseholdInvitation.id == invitation_id, HouseholdInvitation.household_id == household_id))
    if invitation is None:
        raise HTTPException(404, 'Invitation not found.')
    invitation.status = 'REVOKED'
    session.commit()


@router.post('/invitations/accept')
def accept_invite(payload: AcceptInput, session: DB, user: CurrentUser):
    household_id = session.scalar(select(HouseholdInvitation.household_id).where(
        HouseholdInvitation.token_hash == digest(payload.token)))
    if household_id is None:
        raise HTTPException(404, 'Invitation not found or expired.')
    # Use the same household-first lock order as member/invitation administration.
    # This serializes distinct invitations for one membership and avoids a cycle
    # between acceptance's invitation lock and revocation's household lock.
    session.scalar(select(Household).where(Household.id == household_id).with_for_update())
    invitation = session.scalar(select(HouseholdInvitation).where(
        HouseholdInvitation.token_hash == digest(payload.token)).with_for_update())
    if invitation is None or invitation.status != 'PENDING' or expired(invitation.expires_at):
        raise HTTPException(404, 'Invitation not found or expired.')
    identity = session.scalar(select(AuthIdentity).where(
        AuthIdentity.user_id == user.id, func.lower(AuthIdentity.email) == invitation.email,
        AuthIdentity.email_verified.is_(True)))
    if identity is None:
        raise HTTPException(403, 'Sign in with a verified identity matching the invited email.')
    existing = session.scalar(select(Membership).where(
        Membership.household_id == invitation.household_id, Membership.user_id == user.id))
    if existing is None:
        session.add(Membership(household_id=invitation.household_id, user_id=user.id, role=invitation.role))
    invitation.status = 'ACCEPTED'
    session.commit()
    return space_data(session, user, invitation.household_id)
