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

    def verify_signed_url(self, *, storage_path: str, expires: int, signature: str) -> bool:
        """Verify a URL this same provider signed. Deliberately a method,
        not a standalone function taking a secret_key parameter — the
        caller (app/routers/files.py) must verify against *this*
        provider's own key, not a separately-fetched settings value that
        could silently diverge from what actually signed the URL (e.g.
        under a test override). See verify_signed_url() below for the
        pure primitive this delegates to.
        """
        ...


def _signature(storage_path: str, expires: int, secret_key: str) -> str:
    message = f"{storage_path}:{expires}".encode()
    return hmac.new(secret_key.encode(), message, hashlib.sha256).hexdigest()


def verify_signed_url(*, storage_path: str, expires: int, signature: str, secret_key: str) -> bool:
    """Recomputes the HMAC and checks it hasn't expired. The pure
    primitive `LocalStorageProvider.verify_signed_url` delegates to —
    call that method (via the injected StorageProvider dependency) in
    application code, not this function directly with a
    separately-fetched secret_key. A real bug shipped exactly that way
    once: app/routers/files.py used to call this with
    `get_settings().app_secret_key` instead of the actual provider
    instance's own key, which happened to match in production (both
    ultimately read the same setting) but silently diverged under a
    test override, passing locally and failing in CI where
    APP_SECRET_KEY isn't set at all. Kept as a standalone function
    for direct Tier 1 testing (tests/test_storage_signing.py) — see
    docs/security.md.
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

    def verify_signed_url(self, *, storage_path: str, expires: int, signature: str) -> bool:
        return verify_signed_url(
            storage_path=storage_path,
            expires=expires,
            signature=signature,
            secret_key=self._secret_key,
        )
