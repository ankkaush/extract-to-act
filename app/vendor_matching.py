"""Deterministic vendor matching — see PLAN.md Phase 8.

Plain fuzzy string matching, not AI: an unrecognized or misspelled
vendor name is exactly the kind of problem a similarity score solves
reliably, without needing a model — see docs/architecture.md's design
principle, this project uses AI only where the problem is genuinely
underspecified, and matching a name against a small known list isn't.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from rapidfuzz import fuzz

from app.validation import RuleResult

# 0-100 similarity score (rapidfuzz's scale). Below this, a vendor is
# treated as unrecognized rather than guessed at — silently matching the
# wrong vendor is a worse outcome than asking a human, so the threshold
# errs toward caution, not toward maximizing auto-match rate.
MATCH_THRESHOLD = 85.0


def normalize_vendor_name(name: str) -> str:
    """Lowercase, strip punctuation and collapse whitespace — the same
    normalization Vendor.normalized_name stores, so a lookup and a
    stored value are always compared on equal terms (e.g. "Acme Corp."
    and "Acme Corp" normalize identically).
    """
    cleaned = re.sub(r"[^\w\s]", "", name.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


@dataclass
class VendorMatch:
    matched: bool
    vendor_id: uuid.UUID | None = None
    vendor_name: str | None = None
    score: float = 0.0


def find_best_match(
    extracted_name: str, known_vendors: list[tuple[uuid.UUID, str]]
) -> VendorMatch:
    """`known_vendors` is `[(vendor_id, name), ...]` — deliberately plain
    tuples, not ORM objects, so this stays a pure function with no DB
    dependency and is fully testable at Tier 1. The closest name and
    score are returned even on a non-match, since "did you mean X?" is
    useful review context, not just a bare rejection.
    """
    if not extracted_name or not known_vendors:
        return VendorMatch(matched=False)

    normalized_target = normalize_vendor_name(extracted_name)
    best_id, best_name, best_score = None, None, 0.0
    for vendor_id, name in known_vendors:
        score = fuzz.ratio(normalized_target, normalize_vendor_name(name))
        if score > best_score:
            best_id, best_name, best_score = vendor_id, name, score

    if best_score >= MATCH_THRESHOLD:
        return VendorMatch(matched=True, vendor_id=best_id, vendor_name=best_name, score=best_score)
    return VendorMatch(matched=False, vendor_id=best_id, vendor_name=best_name, score=best_score)


def check_vendor_known(
    vendor_name: str | None, known_vendors: list[tuple[uuid.UUID, str]]
) -> RuleResult:
    """Reuses validation.RuleResult — vendor matching writes to the same
    validation_results audit table as Phase 7's rules; see
    docs/data-model.md, "one row per deterministic rule run".
    """
    rule_name = "vendor:known"

    if vendor_name is None:
        # Already caught by Phase 7's required:vendor_name rule — this
        # rule only judges match quality, not presence, so it states
        # that plainly rather than duplicating the other rule's reason.
        return RuleResult(rule_name, False, "vendor_name is missing, cannot match")

    match = find_best_match(vendor_name, known_vendors)

    if match.matched:
        return RuleResult(
            rule_name, True, f"matched known vendor '{match.vendor_name}' (score {match.score:.0f})"
        )
    if match.vendor_name:
        return RuleResult(
            rule_name,
            False,
            f"'{vendor_name}' did not match any known vendor closely enough (closest: "
            f"'{match.vendor_name}', score {match.score:.0f}, threshold {MATCH_THRESHOLD:.0f})",
        )
    return RuleResult(rule_name, False, f"'{vendor_name}' did not match any known vendor on file")
