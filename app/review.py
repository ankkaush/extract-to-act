"""Phase 10 — Human Review Workflow. Pure parsing/validation logic for a
reviewer's field corrections — no I/O, no DB session; the DB writes and
state transition live in app/routers/review.py. See docs/workflow.md and
docs/state-machine.md: a correction moves a document straight from
NEEDS_REVIEW to VALIDATED, rejoining the same forward path a touchless
document takes, rather than being re-run through the Phase 7/8 rules —
the reviewer has already asserted the corrected value is right.
"""

from __future__ import annotations

from datetime import date

from app.extraction import EXTRACTED_FIELDS

# Only the promoted header fields on ExtractionResult can be corrected —
# these are exactly the fields Phase 7/8's rules validate. Line items
# aren't correctable through this endpoint (out of scope for Phase 10).
CORRECTABLE_FIELDS = set(EXTRACTED_FIELDS)

_NUMERIC_FIELDS = {"subtotal", "tax", "total"}
_DATE_FIELDS = {"invoice_date", "due_date"}


class UnknownFieldError(ValueError):
    """The correction targets a field that isn't one of CORRECTABLE_FIELDS."""


class InvalidFieldValueError(ValueError):
    """The correction's value can't be parsed into the target field's type."""


def parse_corrected_value(field_name: str, raw_value: str | None) -> str | float | date | None:
    """Parses a correction's raw string value into the type stored on the
    matching ExtractionResult column. Raises rather than silently
    guessing or coercing — a reviewer correction is exactly the kind of
    financially-consequential write that should fail loudly on bad input.
    """
    if field_name not in CORRECTABLE_FIELDS:
        raise UnknownFieldError(f"{field_name!r} is not a correctable field")

    if raw_value is None or raw_value.strip() == "":
        return None

    if field_name in _NUMERIC_FIELDS:
        try:
            return float(raw_value)
        except ValueError as exc:
            raise InvalidFieldValueError(
                f"{field_name} must be numeric, got {raw_value!r}"
            ) from exc

    if field_name in _DATE_FIELDS:
        try:
            return date.fromisoformat(raw_value[:10])
        except ValueError as exc:
            raise InvalidFieldValueError(
                f"{field_name} must be an ISO date (YYYY-MM-DD), got {raw_value!r}"
            ) from exc

    return raw_value
