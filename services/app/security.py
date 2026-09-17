import hashlib
import hmac
import json
import secrets
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet

from app.config import get_settings

password_hasher = PasswordHasher()
_DUMMY_HASH = password_hasher.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, encoded: str | None) -> bool:
    try:
        valid = password_hasher.verify(encoded or _DUMMY_HASH, password)
        return bool(encoded) and valid
    except (VerificationError, InvalidHashError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token(session_token: str) -> str:
    return hmac.new(
        get_settings().encryption_key(), session_token.encode(), hashlib.sha256
    ).hexdigest()


def encrypt_secrets(value: dict[str, Any]) -> str:
    return Fernet(get_settings().encryption_key()).encrypt(json.dumps(value).encode()).decode()


def decrypt_secrets(value: str) -> dict[str, Any]:
    return json.loads(Fernet(get_settings().encryption_key()).decrypt(value.encode()))
