"""StorageProvider adapter — see docs/architecture.md on the adapter
boundary and docs/adr/0002-database.md's sibling reasoning for why this
exists as an interface at all: local disk in dev, S3-compatible (Cloudflare
R2 / Backblaze B2) in prod, swappable without touching business logic.

Only the local implementation exists so far — see .env.example, the
S3-compatible adapter is a later phase (not yet scheduled ahead of need).
"""

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


class LocalStorageProvider:
    """Dev-only. Files are written under `base_dir`, named by a random id
    plus their original extension so `put` calls never collide.
    """

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def put(self, *, content: bytes, suggested_name: str) -> str:
        suffix = Path(suggested_name).suffix
        key = f"{uuid.uuid4()}{suffix}"
        path = self.base_dir / key
        path.write_bytes(content)
        return key

    def get(self, *, storage_path: str) -> bytes:
        return (self.base_dir / storage_path).read_bytes()

    def sign_url(self, *, storage_path: str, expires_in: int = 300) -> str:
        # No download/review endpoint exists yet to serve a signed URL
        # against (that starts in Phase 10) — implemented for real then,
        # per docs/security.md's signed/expiring URL requirement.
        raise NotImplementedError("sign_url is implemented starting Phase 10")
