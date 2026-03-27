import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet() -> Fernet:
    key = os.getenv("TENANT_TOKEN_ENCRYPTION_KEY", "").strip()
    if not key:
        digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(digest).decode("utf-8")
    return Fernet(key.encode("utf-8"))


def encrypt_secret(raw_value: str) -> str:
    if not raw_value:
        return ""
    return _fernet().encrypt(raw_value.encode("utf-8")).decode("utf-8")


def decrypt_secret(enc_value: str) -> str:
    if not enc_value:
        return ""
    try:
        return _fernet().decrypt(enc_value.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return ""
