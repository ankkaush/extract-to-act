"""StorageProvider adapter — see docs/architecture.md on the adapter
boundary and docs/adr/0002-database.md's sibling reasoning for why this
exists as an interface at all: local disk in dev, S3-compatible (Cloudflare
R2 / Backblaze B2) in prod, swappable without touching business logic.

Only the local implementation exists so far — see .env.example, the
S3-compatible adapter is a later phase (not yet scheduled ahead of need).

`sign_url`/`verify_signed_url` implement docs/security.md's "signed,
short-lived storage URLs" control, wired up for real starting Phase 10
(the review UI is the first thing that needs to show a reviewer the
original file). The signature is a plain HMAC-SHA256 over the storage
path and expiry, keyed by APP_SECRET_KEY — sufficient for a single-tenant
MVP; a cloud storage backend's own native presigned-URL support replaces
this outright when that adapter is built.
"""

import hashlib
import hmac
import time
import uuid
from pathlib import Path
from typing import Protocol


class StorageProvider(Protocol):
    def put(self, *, content: bytes, suggested_name: str) -> str:
        """Store content, return a storage_path that `get` can resolve later."""
        ...

    def get(self, *, storage_path: str) -> bytes:
        """Retrieve previously stored content by its storage_path."""
        ...

    def sign_url(self, *, storage_path: str, expires_in: int = 300) -> str:
        """Return a short-lived, signed URL for the given storage_path."""
        ...


def _signature(storage_path: str, expires: int, secret_key: str) -> str:
    message = f"{storage_path}:{expires}".encode()
    return hmac.new(secret_key.encode(), message, hashlib.sha256).hexdigest()


def verify_signed_url(*, storage_path: str, expires: int, signature: str, secret_key: str) -> bool:
    """Recomputes the HMAC and checks it hasn't expired. Used by the
    unauthenticated GET /files/{storage_path} route (app/routers/files.py)
    — the signature itself is the authorization there, not the bearer
    token every other route requires, so a signed URL works dropped
    straight into a reviewer's browser or an <img>/<iframe> src.
    """
    if expires < int(time.time()):
        return False
    expected = _signature(storage_path, expires, secret_key)
    return hmac.compare_digest(expected, signature)


class LocalStorageProvider:
    """Dev-only. Files are written under `base_dir`, named by a random id
    plus their original extension so `put` calls never collide.
    """

    def __init__(self, base_dir: Path, secret_key: str):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._secret_key = secret_key

    def put(self, *, content: bytes, suggested_name: str) -> str:
        suffix = Path(suggested_name).suffix
        key = f"{uuid.uuid4()}{suffix}"
        path = self.base_dir / key
        path.write_bytes(content)
        return key

    def get(self, *, storage_path: str) -> bytes:
        return (self.base_dir / storage_path).read_bytes()

    def sign_url(self, *, storage_path: str, expires_in: int = 300) -> str:
        expires = int(time.time()) + expires_in
        signature = _signature(storage_path, expires, self._secret_key)
        return f"/files/{storage_path}?expires={expires}&signature={signature}"
