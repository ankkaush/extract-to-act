# ADR 0006: Extraction provider — DEFERRED

**Status:** Deferred to Phase 5
**Confidence:** N/A — not decided

## Decision

Not made yet, intentionally. This ADR is a placeholder so the deferral itself is documented rather than silently assumed.

## Why this is deferred rather than decided now

The earlier discovery work considered Azure Document Intelligence, AWS Textract, Google Document AI, Mistral OCR, and Claude vision, and concluded that a confident pick could not be justified from documentation and third-party benchmarks alone — those sources are marketing-adjacent, not evidence from this project's own documents. Phase 5 exists specifically to replace that assumption with a small empirical spike (~15–20 real/realistic invoices across at least Azure, Mistral, and Claude) before this decision is locked in.

## What is already known, pending the spike

See `docs/extraction-strategy.md` for the current comparison table, including free-tier terms, native confidence/provenance support, and rough per-document cost for each candidate.

## What will complete this ADR

Once Phase 5 concludes, this document will be replaced with the actual decision, its supporting evidence, and the confidence-threshold starting points derived from it.
