"""Tier 1 (docs/testing-strategy.md): pure HMAC signing/verification
logic in app/storage.py, no I/O — the actual file-serving endpoint is
covered by the integration tests in tests/test_review_api.py.
"""

import time

# _signature is private, imported directly here to test the exact
# primitive verify_signed_url is built on.
from app.storage import LocalStorageProvider, _signature, verify_signed_url

SECRET = "test-secret"


def test_signature_verifies_when_unmodified():
    expires = int(time.time()) + 300
    signature = _signature("some/path.pdf", expires, SECRET)

    assert verify_signed_url(
        storage_path="some/path.pdf", expires=expires, signature=signature, secret_key=SECRET
    )


def test_signature_rejected_for_wrong_secret():
    expires = int(time.time()) + 300
    signature = _signature("some/path.pdf", expires, "a-different-secret")

    assert not verify_signed_url(
        storage_path="some/path.pdf", expires=expires, signature=signature, secret_key=SECRET
    )


def test_signature_rejected_when_path_tampered():
    expires = int(time.time()) + 300
    signature = _signature("some/path.pdf", expires, SECRET)

    assert not verify_signed_url(
        storage_path="other/path.pdf", expires=expires, signature=signature, secret_key=SECRET
    )


def test_signature_rejected_when_expiry_tampered():
    expires = int(time.time()) + 300
    signature = _signature("some/path.pdf", expires, SECRET)

    assert not verify_signed_url(
        storage_path="some/path.pdf", expires=expires + 1000, signature=signature, secret_key=SECRET
    )


def test_expired_link_rejected_even_with_correct_signature():
    expires = int(time.time()) - 1
    signature = _signature("some/path.pdf", expires, SECRET)

    assert not verify_signed_url(
        storage_path="some/path.pdf", expires=expires, signature=signature, secret_key=SECRET
    )


def test_provider_verifies_its_own_signed_url_regardless_of_any_other_secret(tmp_path):
    """Regression test: app/routers/files.py used to verify against
    get_settings().app_secret_key instead of the actual injected
    StorageProvider's own key — invisible in production (both read the
    same setting) but a real bug wherever the two diverge, e.g. under a
    test override, or in CI where APP_SECRET_KEY isn't set at all. A
    provider must always be able to verify a URL it signed itself,
    using no external secret source.
    """
    provider = LocalStorageProvider(base_dir=tmp_path, secret_key="whatever-this-provider-uses")
    signed_url = provider.sign_url(storage_path="some/path.pdf", expires_in=300)

    query = signed_url.split("?", 1)[1]
    params = dict(pair.split("=") for pair in query.split("&"))

    assert provider.verify_signed_url(
        storage_path="some/path.pdf", expires=int(params["expires"]), signature=params["signature"]
    )

    # A provider configured with a *different* secret must reject the
    # same URL — proves verification genuinely depends on the
    # instance's own key, not some shared/global fallback.
    other_provider = LocalStorageProvider(base_dir=tmp_path, secret_key="a-different-key")
    assert not other_provider.verify_signed_url(
        storage_path="some/path.pdf", expires=int(params["expires"]), signature=params["signature"]
    )
