"""Upload validation for Phase 4. Deliberately narrow: this checks whether
a file is safe and plausible to accept at all (type, size) — not whether
it's a *good* invoice, which is Phase 7's deterministic validation and
Phase 5/6's extraction confidence. See docs/security.md on why file-type
checking is content-sniffed, not extension-based.
"""

import hashlib


class UnsupportedFileType(Exception):
    pass


class FileTooLarge(Exception):
    pass


# Magic-byte signatures for the file types this system accepts. Checked
# against actual bytes, never the filename or the client-supplied
# Content-Type header, both of which are easy to spoof.
_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "application/pdf": (b"%PDF-",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/tiff": (b"II*\x00", b"MM\x00*"),
}


def sniff_mime_type(content: bytes) -> str:
    """Return the detected MIME type, or raise UnsupportedFileType.

    Only the types above are ever accepted, regardless of what the
    uploader claims — see docs/security.md, "malicious or oversized
    upload".
    """
    for mime_type, signatures in _SIGNATURES.items():
        if content.startswith(signatures):
            return mime_type
    raise UnsupportedFileType("File content does not match a supported type (PDF, PNG, JPEG, TIFF)")


def check_size(content: bytes, *, max_bytes: int) -> None:
    if len(content) > max_bytes:
        raise FileTooLarge(f"File exceeds the {max_bytes} byte limit")


def content_hash(content: bytes) -> str:
    """SHA-256 of the raw bytes. Stored on the document now; used for
    exact-duplicate detection starting Phase 9.
    """
    return hashlib.sha256(content).hexdigest()
