# Extraction strategy

**The provider decision is intentionally deferred to Phase 5.** This document records what is already known, what will be tested, and how the decision will actually get made — not a pre-decided answer.

## Why this is deferred rather than decided now

Provider comparisons available in documentation and third-party benchmarks are marketing-adjacent, not evidence from this project's own documents. The previous discovery round initially leaned toward one provider based on exactly that kind of secondhand comparison, and that recommendation was explicitly withdrawn on review — see `docs/adr/0006-extraction-provider.md`. Phase 5 exists to replace assumption with a small, real, measured comparison before anything is built around a guess.

## What's known so far, per candidate

| Provider | Free tier | Card required | After free tier | Native confidence + provenance | Invoice-specific training |
|---|---|---|---|---|---|
| Azure Document Intelligence | 500 pages/month, ongoing | No | ~$0.01–0.05/page | Yes, both, native | Purpose-built prebuilt invoice model |
| Mistral OCR 4 | "Experiment" tier, rate-limited (~2 RPM), no page cap | No | ~$4/1,000 pages ($2 batch) | Yes, both, native | General document model, not invoice-trained |
| AWS Textract | 1,000 pages/month, first 3 months only | Yes | ~$0.05–0.10/page | Yes | Purpose-built (AnalyzeExpense) |
| Google Document AI | $300 one-time credit | Yes | Tiered, comparable to Azure/AWS | Yes | Purpose-built, recently changed underlying tech (2026) — least verified |
| Claude (vision) | None | Yes | ~$0.006–0.01/invoice | No native confidence/bbox; PDF citations don't ground scanned images | None — best general semantic reasoning |
| Tesseract (local, open-source) | Free, unlimited | No | Free forever | No confidence, weak on tables | None — text only |

## Status

The evaluation harness is built — see [`spike/README.md`](../spike/README.md) for how to run it. It has not yet been run against real providers: this repository's environment has no Azure/Mistral/Anthropic credentials, and the sample-invoice sourcing decision below is still open. This section will be replaced with the actual results and recommendation once both are resolved and a real run completes.

## What Phase 5 will actually test

- **Sample:** ~15–20 representative invoices — clean digital PDF, scanned, multi-column, at least one non-USD currency. Sourcing (synthetic vs. anonymized real vs. public dataset) is an open decision — see PLAN.md Phase 1 completion note.
- **Providers:** Azure Document Intelligence, Mistral OCR, and Claude vision — the three genuinely different approaches (purpose-built structured extraction, general-purpose structured extraction, flexible multimodal reasoning without native grounding).
- **Measured per provider:** per-field accuracy against manually verified ground truth, whether confidence scores actually correlate with correctness, line-item extraction quality specifically, latency, and real cost per document.
- **Cost:** run primarily through Azure's and Mistral's free tiers (both genuinely free, no card) — see `docs/cost-strategy.md` for the full budget.

## What this decides

1. Which provider(s) become the real `ExtractionProvider` implementation in Phase 6.
2. The starting confidence thresholds used in validation/review routing (Phase 7, 10) — **not** fixed arbitrarily; the earlier draft's 95%/90%/70% bands are documented here only as an industry-typical starting hypothesis to test against, not a locked decision. See "on confidence scores" below.

## On confidence scores

A provider's confidence score is a provider-internal certainty heuristic, not a calibrated statistical probability, and is not comparable across providers. A high-confidence field can still be wrong; a low-confidence field can still be correct. For this reason, financial-critical fields (total, subtotal, tax) are never trusted on confidence alone — the deterministic arithmetic check in Phase 7 runs regardless of what any confidence score says. Confidence is used to route to review, not as the sole gate on a financial fact.

## Provenance: what's kept, what's deliberately not

Kept per field: value, confidence, page number, bounding box (where the provider supplies one), source text snippet, provider name and model version — this is what lets a reviewer see *why* the system extracted a value, next to the original document.

Deliberately not built at this scale: bounding boxes for every line-item cell (nice-to-have, not MVP), storage of full raw provider payloads beyond what a reviewer needs, or a generic "evidence" abstraction meant to support arbitrary future document types.
