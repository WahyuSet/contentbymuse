import base64
import hashlib

from cryptography.fernet import Fernet


def _fernet(app_secret_key: str) -> Fernet:
    # Kunci Fernet diturunkan dari APP_SECRET_KEY agar .env tetap satu string bebas.
    digest = hashlib.sha256(app_secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plain: str, app_secret_key: str) -> bytes:
    return _fernet(app_secret_key).encrypt(plain.encode("utf-8"))


def decrypt_secret(encrypted: bytes, app_secret_key: str) -> str:
    return _fernet(app_secret_key).decrypt(encrypted).decode("utf-8")
