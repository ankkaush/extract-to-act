# ADR 0006: Extraction provider — DEFERRED (empirical comparison scoped to Mistral vs. Claude)

**Status:** Deferred, pending the real Phase 5 run
**Confidence:** N/A — not decided

## Decision

Not made yet. This ADR remains a placeholder so the deferral itself is documented rather than silently assumed. What *has* been decided, explicitly, by the project owner: **the empirical comparison is scoped to Mistral OCR and Claude vision only — Azure Document Intelligence is intentionally excluded from this experiment.**

## Why Azure is excluded from the empirical comparison

Azure was one of several candidates considered in the original discovery work (`docs/extraction-strategy.md`), but it is a candidate, not a requirement — the project needs a working extraction provider, not specifically a three-way comparison. With two viable, sufficiently different candidates already in hand (Mistral: cheap, general-purpose OCR with native structured output; Claude: no native OCR/confidence layer, strongest semantic flexibility), forcing a third provider into the spike adds cost, complexity, and Azure account setup for a comparison that doesn't need it to reach a decision. This is a scope decision, not a judgment that Azure is unsuitable — it stays a documented option (`spike/providers/azure_provider.py` and its readiness test remain in the repo) if a future need reopens the question.

## Why this is otherwise still deferred

The earlier discovery work concluded that a confident pick could not be justified from documentation and third-party benchmarks alone — those sources are marketing-adjacent, not evidence from this project's own documents. Phase 5 exists specifically to replace that assumption with a small empirical spike against the project's own 18-document synthetic dataset (`spike/invoice_specs.py`), scored on both aggregate and business-critical-field accuracy (`spike/evaluate.py`).

## Status of the real run

A first attempt at the real Mistral + Claude comparison surfaced two genuine bugs in `spike/providers/mistral_provider.py` — the installed SDK's public client class lives at `mistralai.client.Mistral`, not `mistralai.Mistral`, and the JSON-schema field name is `schema_definition`, not `schema`. Both were found and fixed through static package introspection (no network call, no credentials touched) and are now covered by `spike/test_provider_readiness.py`, which statically guards against reintroducing either regression. Execution of the real comparison is currently paused for credential-safety reasons — see `PLAN.md` Phase 5 for the full account and exactly what remains.

## What is already known, pending the real run

See `docs/extraction-strategy.md` for the current comparison table, including free-tier terms, native confidence/provenance support, and rough per-document cost for each candidate.

## What will complete this ADR

Once the real Mistral vs. Claude run and evaluation complete, this document will be replaced with the actual decision, its supporting evidence (per-field and business-critical-field accuracy, confidence calibration, itemized errors), and the confidence-threshold starting points derived from it. If a future need reopens the Azure question, that would be a separate, explicitly-scoped follow-up — not a silent expansion of this ADR.
