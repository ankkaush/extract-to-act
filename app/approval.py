"""Phase 11 — Approval Workflow. Pure threshold logic — no I/O, no DB
session. See docs/workflow.md step 8: a VALIDATED invoice at or above
the configured amount needs a person's sign-off before any downstream
write; anything under it proceeds without one.

docs/workflow.md also names a second, smaller floor — "missing a PO on
a smaller floor" — but no purchase-order field exists anywhere in the
extraction schema yet (see app/extraction.py's EXTRACTED_FIELDS), so
there is nothing to check that condition against. Left unimplemented
and stated here rather than silently dropped; revisit if/when a PO
field is ever extracted.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ApprovalRequirement:
    required: bool
    reason: str


def requires_approval(*, total: float, threshold: float) -> ApprovalRequirement:
    if total >= threshold:
        return ApprovalRequirement(
            True, f"total {total:.2f} meets or exceeds the approval threshold {threshold:.2f}"
        )
    return ApprovalRequirement(
        False, f"total {total:.2f} is under the approval threshold {threshold:.2f}"
    )
