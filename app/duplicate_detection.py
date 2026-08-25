"""Deterministic duplicate detection — see PLAN.md Phase 9 and
docs/reliability.md, idempotency scenario 2.

Two independent checks, run at different points in the pipeline:

- **Exact file-hash match** (`find_exact_hash_duplicate`) — checked at
  `RECEIVED`, before extraction ever runs, so a re-upload of literally
  the same bytes never spends a paid extraction call. This is distinct
  from Phase 4's request-level idempotency key: that catches the same
  HTTP request retried, this catches the same file submitted through a
  genuinely different request (two people upload it, a supplier
  double-sends). See docs/state-machine.md's `RECEIVED → DUPLICATE`.

- **Content-level match** (`find_content_duplicate`) — checked during
  `VALIDATING`, since it needs extracted fields. Catches the same
  invoice arriving as a *different* file (re-scanned, re-typed).

Both are exact-after-normalization comparisons on a specific field
combination, not probabilistic fuzzy scoring across everything — the
invoice_number match anchors the content-level check precisely enough
that two genuinely different same-day, same-vendor invoices are never
confused with each other. See docs/reliability.md's stated design:
"fuzzy match on vendor + invoice number + amount + date".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from app.vendor_matching import normalize_vendor_name

# Matches app/validation.py's ARITHMETIC_TOLERANCE — the same rounding
# tolerance applies here for the same reason (currency arithmetic).
AMOUNT_TOLERANCE = 0.02


def normalize_invoice_number(invoice_number: str) -> str:
    return invoice_number.strip().lower()


@dataclass
class DuplicateMatch:
    is_duplicate: bool
    matched_document_id: uuid.UUID | None = None
    reason: str | None = None


def find_exact_hash_duplicate(
    content_hash: str, existing_documents: list[tuple[uuid.UUID, str]]
) -> DuplicateMatch:
    """`existing_documents` is `[(document_id, content_hash), ...]` for
    prior documents eligible to match against — the caller is
    responsible for excluding `FAILED` documents (a technically-failed
    prior attempt should not block a legitimate retry) and the document
    being checked itself. Pure function, no DB dependency.
    """
    for document_id, existing_hash in existing_documents:
        if existing_hash == content_hash:
            return DuplicateMatch(
                is_duplicate=True,
                matched_document_id=document_id,
                reason=f"identical file content already submitted as document {document_id}",
            )
    return DuplicateMatch(is_duplicate=False)


def find_content_duplicate(
    *,
    vendor_name: str | None,
    invoice_number: str | None,
    total: float | None,
    invoice_date: date | None,
    candidates: list[tuple[uuid.UUID, str | None, str | None, float | None, date | None]],
) -> DuplicateMatch:
    """`candidates` is `[(document_id, vendor_name, invoice_number,
    total, invoice_date), ...]` for other documents' extraction results
    — again the caller excludes `FAILED` documents and the document
    being checked. Requires all four fields to match (after
    normalization) — a partial match (e.g. same vendor and date, a
    different invoice number) is two genuinely different invoices, not
    a duplicate.
    """
    if None in (vendor_name, invoice_number, total, invoice_date):
        # Can't determine a duplicate without a full comparison key —
        # Phase 7's required-field rule already flags a missing field on
        # its own merits, this check simply declines to guess.
        return DuplicateMatch(is_duplicate=False)

    normalized_vendor = normalize_vendor_name(vendor_name)
    normalized_number = normalize_invoice_number(invoice_number)

    for doc_id, c_vendor, c_number, c_total, c_date in candidates:
        if None in (c_vendor, c_number, c_total, c_date):
            continue
        if normalize_vendor_name(c_vendor) != normalized_vendor:
            continue
        if normalize_invoice_number(c_number) != normalized_number:
            continue
        if abs(float(c_total) - float(total)) > AMOUNT_TOLERANCE:
            continue
        if c_date != invoice_date:
            continue
        return DuplicateMatch(
            is_duplicate=True,
            matched_document_id=doc_id,
            reason=(
                f"matches document {doc_id}: same vendor ('{vendor_name}'), invoice number "
                f"('{invoice_number}'), total ({total}), and invoice date ({invoice_date})"
            ),
        )
    return DuplicateMatch(is_duplicate=False)
