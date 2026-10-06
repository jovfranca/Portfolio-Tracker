"""External identity verification, isolated from financial application code."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderIdentity:
    provider: str
    subject: str
    display_name: str
    email: str | None = None
    email_verified: bool = False


def verify_google(credential, nonce):
    from google.auth.transport.requests import Request
    from google.auth.exceptions import GoogleAuthError, TransportError
    from google.oauth2.id_token import verify_oauth2_token

    client_id = os.environ['GOOGLE_CLIENT_ID']
    try:
        claims = verify_oauth2_token(credential, Request(), client_id)
    except TransportError:
        raise
    except GoogleAuthError:
        raise ValueError('Invalid Google identity.') from None
    if (claims.get('iss') not in {'accounts.google.com', 'https://accounts.google.com'}
            or claims.get('nonce') != nonce or not claims.get('sub')):
        raise ValueError('Invalid Google identity.')
    email = claims.get('email')
    # Google is authoritative for Gmail and Workspace emails, not arbitrary third-party addresses.
    verified = bool(claims.get('email_verified') and email and
                    (email.lower().endswith('@gmail.com') or claims.get('hd')))
    return ProviderIdentity('GOOGLE', claims['sub'], claims.get('name') or 'Google user', email, verified)
