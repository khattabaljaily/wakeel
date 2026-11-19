"""Encryption of the private files (stamps, signatures, logos, letterheads, library documents) on disk.

Each company has its own key, derived from one master key (HKDF-SHA256, with the company id), and every file is sealed
with AES-256-GCM, which also detects any change to it. The master key lives in secrets.json, never next to the files:
whoever copies only the files (a stolen disk, a backup) cannot read them. IF THE MASTER KEY IS LOST THE FILES ARE LOST."""
import base64
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.core.exceptions import ImproperlyConfigured

MAGIC = b'WKLENC\x01'        # 'WKLENC' + format version 1
NONCE = 12
SALT = b'wakeel-file-encryption-v1'


class CorruptFile(OSError):
    """The file does not decrypt: wrong key, another company's file, or it was changed."""


def load_key(value: str, dev: bool, secret_key: str) -> bytes:
    """The master key from secrets.json (urlsafe base64 of 32 bytes). Without one, development and tests use a key made
    from SECRET_KEY; production refuses to start, so files are never stored in the clear by accident."""
    if value:
        try:
            key = base64.urlsafe_b64decode(value.encode())
        except Exception as exc:
            raise ImproperlyConfigured('FILE_ENCRYPTION_KEY in secrets.json is not valid base64.') from exc
        if len(key) != 32:
            raise ImproperlyConfigured('FILE_ENCRYPTION_KEY must be 32 bytes (run: manage.py make_file_key).')
        return key
    if dev:
        return hashlib.sha256(b'wakeel-dev-file-key:' + secret_key.encode()).digest()
    raise ImproperlyConfigured('FILE_ENCRYPTION_KEY is missing in secrets.json (create one with: manage.py make_file_key).')


def new_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def company_key(master: bytes, company_id: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=SALT, info=f'company:{company_id}'.encode()).derive(master)


def is_encrypted(blob: bytes) -> bool:
    return blob.startswith(MAGIC)


def encrypt(master: bytes, company_id: int, plain: bytes) -> bytes:
    nonce = os.urandom(NONCE)
    return MAGIC + nonce + AESGCM(company_key(master, company_id)).encrypt(nonce, plain, f'company:{company_id}'.encode())


def decrypt(master: bytes, company_id: int, blob: bytes) -> bytes:
    try:
        return AESGCM(company_key(master, company_id)).decrypt(
            blob[len(MAGIC):len(MAGIC) + NONCE], blob[len(MAGIC) + NONCE:], f'company:{company_id}'.encode())
    except InvalidTag as exc:
        raise CorruptFile('The file could not be decrypted.') from exc
