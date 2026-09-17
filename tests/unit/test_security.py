import pytest
from cryptography.fernet import InvalidToken

from app.security import decrypt_secrets, encrypt_secrets


def test_authenticated_secret_storage():
    secret = {"token": "private-test-value", "password": "another-private-value"}
    ciphertext = encrypt_secrets(secret)
    assert secret["token"] not in ciphertext
    assert decrypt_secrets(ciphertext) == secret
    with pytest.raises(InvalidToken):
        decrypt_secrets(ciphertext[:20] + "AAAA" + ciphertext[24:])
