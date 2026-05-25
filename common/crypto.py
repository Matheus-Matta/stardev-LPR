import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet_key() -> bytes:
    configured = settings.FIELD_ENCRYPTION_KEY.encode()
    try:
        Fernet(configured)
        return configured
    except (ValueError, TypeError):
        digest = hashlib.sha256(configured).digest()
        return base64.urlsafe_b64encode(digest)


def encrypt_text(value: str) -> str:
    if not value:
        return ""
    return Fernet(_fernet_key()).encrypt(value.encode()).decode()


def decrypt_text(value: str) -> str:
    if not value:
        return ""
    try:
        return Fernet(_fernet_key()).decrypt(value.encode()).decode()
    except InvalidToken:
        return ""

