"""Exercise Google's actual JWT verifier with synthetic signed tokens and local keys."""
import time

import pytest

from src.auth.providers import verify_google


@pytest.fixture
def google_token(monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from google.auth import crypt, jwt

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'synthetic-client')
    monkeypatch.setattr('google.oauth2.id_token._fetch_certs', lambda *a: {'test-key': public})
    def signed(**extra):
        claims = {'iss': 'https://accounts.google.com', 'aud': 'synthetic-client', 'sub': 'stable-subject',
                  'iat': int(time.time()) - 10, 'exp': int(time.time()) + 300, 'nonce': 'challenge',
                  'name': 'Test user', 'email': 'alice@gmail.com', 'email_verified': True, **extra}
        return jwt.encode(crypt.RSASigner.from_string(private, key_id='test-key'), claims).decode()
    return signed


def test_valid_google_signature_subject_and_email_authority(google_token):
    identity = verify_google(google_token(), 'challenge')
    assert identity.provider == 'GOOGLE'
    assert identity.subject == 'stable-subject'
    assert identity.email_verified
    assert not verify_google(google_token(email='alice@example.com'), 'challenge').email_verified
    assert verify_google(google_token(email='alice@example.com', hd='example.com'), 'challenge').email_verified


@pytest.mark.parametrize('claims', [
    {'aud': 'wrong-client'}, {'iss': 'https://evil.example'}, {'exp': 1},
    {'nonce': 'other-challenge'}, {'sub': ''},
])
def test_google_rejects_wrong_audience_issuer_expiry_nonce_or_subject(google_token, claims):
    with pytest.raises(ValueError):
        verify_google(google_token(**claims), 'challenge')


def test_google_rejects_tampered_signature(google_token):
    credential = google_token()
    header, payload, signature = credential.split('.')
    with pytest.raises(ValueError):
        verify_google('.'.join((header, payload, ('a' if signature[0] != 'a' else 'b') + signature[1:])), 'challenge')
