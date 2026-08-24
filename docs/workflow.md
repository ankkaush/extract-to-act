# Business workflow

## In plain English

An invoice document arrives. The system reads it and pulls out the header details — who it's from, what it's for, how much, when it's due — and, where possible, the individual line items.

Before trusting any of that, the system checks: does this even look like a real invoice, does the math add up, have we seen this exact invoice before, do we recognize this vendor. If everything checks out and the system is confident in what it read, the invoice moves forward on its own — no person touches it.

If anything looks uncertain or wrong, it's set aside for a person to look at, with the original document and the extracted numbers shown side by side so a correction takes seconds, not a full re-read.

Once an invoice is validated — automatically or by a person — it needs a decision: is it small enough to pay without sign-off, or does it need someone's approval first? Either way, the result is a real record created in an accounting system (or a realistic stand-in for one, see `docs/architecture.md`), a notification to the person responsible, and a permanent trail of exactly what happened and why.

Over time, a small dashboard shows whether the system is actually saving anyone time — how many invoices needed no human at all, how many needed a person, and how long the whole thing takes.

## The workflow as a sequence

1. **Document arrives** via authenticated upload (Phase 4).
2. **Extraction** reads the document into structured fields with confidence and provenance (Phase 5–6).
3. **Plausibility check** — if extraction can't populate the basic shape of an invoice (no vendor, no total, no invoice number, at low confidence), the document is treated as unrecognized and routed to review rather than forced through validation (see "Classification" in `docs/architecture.md`).
4. **Deterministic validation** — arithmetic consistency, required fields (Phase 7).
5. **Vendor matching** — is this a known vendor (Phase 8)?
6. **Duplicate detection** — have we processed this invoice before (Phase 9)?
7. **Decision point:** confident and clean → continue automatically. Anything uncertain or failing a rule → **human review** (Phase 10).
8. **Approval routing** — above a configured amount threshold (or missing a PO on a smaller floor), a person must approve; otherwise it proceeds (Phase 11).
9. **Business action** — a record is created in the (mocked, initially) accounting system, and the responsible person is notified (Phase 12).
10. **Audit & metrics** — every step above is logged; the dashboard summarizes outcomes across all processed documents (Phase 16).

## What automatically passes vs. what needs a human

| Condition | Outcome |
|---|---|
| High confidence on all financial-critical fields, arithmetic checks pass, vendor recognized, no duplicate, under approval threshold | Fully automatic — no human touches it |
| Low confidence on any financial-critical field (total, subtotal, tax, invoice number) | Human review |
| Arithmetic mismatch | Human review |
| Vendor not recognized | Human review |
| Suspected duplicate | Routed to a duplicate terminal state — not review, not reprocessed |
| Amount above the configured approval threshold, or missing a PO above a smaller floor | Approval step, regardless of extraction confidence |
| Document doesn't extract as invoice-shaped at all | Human review, reason: not recognized |

The exact confidence thresholds are intentionally not fixed yet — see `docs/extraction-strategy.md` for why, and how they will be set from real data in Phase 5.
