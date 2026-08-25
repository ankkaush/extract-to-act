# ADR 0006: Extraction provider — Mistral OCR

**Status:** Accepted
**Confidence:** Medium — a real, single-provider empirical validation, not a comparative one. See caveats below.

## Decision

Mistral OCR is the `ExtractionProvider` implementation for Phase 6.

## Evidence

A real run against the full 18-document synthetic dataset (`spike/invoice_specs.py`), evaluated against the authoritative ground truth: 18/18 documents processed, 98% overall field accuracy, 98% business-critical-field accuracy (invoice number, invoice date, due date, currency, subtotal, tax, total), at a real cost of $0.076 total. Full results, every named error, and what each one means: `docs/extraction-strategy.md`, "Real results."

## Why Mistral, and why not a comparison

Mistral was tested against its own bar (does it work, is it accurate enough, is it affordable), not against Claude or Azure head-to-head:

- **Azure** was excluded from the start by explicit project owner decision — an optional candidate, not a requirement (see the original version of this ADR in git history for that reasoning, which still stands).
- **Claude** was excluded from the real run because the Anthropic credential in this environment was exposed during diagnosis of an unrelated issue and is treated as compromised — no call was made with it, by explicit instruction.

This means the decision rests on Mistral's own results being good enough, not on Mistral beating an alternative. That's a materially different, and weaker, form of evidence than the original three-way (later two-way) comparison this ADR was meant to produce — worth being honest about rather than presenting as more rigorous than it is.

## Alternatives considered

- **Azure Document Intelligence** — not tested empirically; excluded by scope decision, not by evidence. Remains a documented, ready option (`spike/providers/azure_provider.py`, covered by `spike/test_provider_readiness.py`) if a future need reopens the question.
- **Claude vision** — not tested empirically; excluded by credential-safety necessity, not by evidence or preference. The wrapper code is verified correct against the installed SDK (`spike/test_provider_readiness.py`) and ready to run the moment a trusted key exists.
- **AWS Textract, Google Document AI, Tesseract** — never seriously in contention; see `docs/extraction-strategy.md`'s background comparison table.

## Known gap this decision carries into Phase 6

Mistral's schema-constrained structured-output call returned **no per-field confidence** in the real run — confirmed empirically, not merely suspected from documentation. The original architecture's plan to route human review via per-field confidence thresholds (the 95%/90%/70% draft bands) has no field-level number to threshold against for this provider. Phase 6/7 must design review-routing around deterministic validation failures and targeted plausibility checks instead — see `docs/extraction-strategy.md`, "What this means for Phase 6," for the specifics this run surfaced (currency and due-date fields each produced a real critical-field error and need an extra deterministic check layered on top).

## What would change this decision

- A future run with a trusted Claude key showing materially better accuracy or, critically, better handling of the "return null rather than hallucinate" failure mode Mistral exhibited on `inv_13`'s due date.
- Mistral's structured-output confidence gap turning out to matter more in practice than expected once Phase 7's deterministic-only review routing is actually built and tested against a wider document set than this synthetic 18.
- Azure being reconsidered if a concrete need for native per-field confidence and bounding boxes outweighs the cost/complexity of adding a second provider.

None of these are scheduled work — they're the conditions under which this ADR would be reopened, not a plan to reopen it.
