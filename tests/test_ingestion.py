"""Tier 1 (docs/testing-strategy.md): pure functions, no I/O, no DB."""

import hashlib

import pytest

from app.ingestion import (
    FileTooLarge,
    UnsupportedFileType,
    check_size,
    content_hash,
    sniff_mime_type,
)

PDF_BYTES = b"%PDF-1.4\n%rest of a fake pdf"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"rest of a fake png"
TEXT_BYTES = b"just some plain text, not a real document"


def test_sniffs_pdf_by_content_not_extension():
    assert sniff_mime_type(PDF_BYTES) == "application/pdf"


def test_sniffs_png():
    assert sniff_mime_type(PNG_BYTES) == "image/png"


def test_rejects_unrecognized_content():
    with pytest.raises(UnsupportedFileType):
        sniff_mime_type(TEXT_BYTES)


def test_rejects_content_that_only_claims_to_be_a_pdf_by_name():
    # The whole point: a .pdf-named file with the wrong bytes must fail —
    # sniff_mime_type never sees a filename at all.
    with pytest.raises(UnsupportedFileType):
        sniff_mime_type(b"not actually a pdf despite the filename")


def test_check_size_allows_content_within_limit():
    check_size(b"x" * 100, max_bytes=200)  # should not raise


def test_check_size_rejects_content_over_limit():
    with pytest.raises(FileTooLarge):
        check_size(b"x" * 300, max_bytes=200)


def test_content_hash_is_sha256_of_the_bytes():
    assert content_hash(PDF_BYTES) == hashlib.sha256(PDF_BYTES).hexdigest()


def test_content_hash_differs_for_different_content():
    assert content_hash(PDF_BYTES) != content_hash(PNG_BYTES)
