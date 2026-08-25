"""Tier 1 (docs/testing-strategy.md): pure HMAC signing/verification
logic in app/storage.py, no I/O — the actual file-serving endpoint is
covered by the integration tests in tests/test_review_api.py.
"""

import time

# _signature is private, imported directly here to test the exact
# primitive verify_signed_url is built on.
from app.storage import _signature, verify_signed_url

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
