# Extraction strategy

**Decided: Mistral OCR is the Phase 6 `ExtractionProvider`.** Based on a real, single-provider run against the full 18-document synthetic dataset — see "Real results" below for the evidence and its honest limitations.

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

## Real results (Mistral, 2026-08-25)

A single real run against all 18 synthetic documents, evaluated once against the authoritative ground truth. **Mistral only** — see "Why Mistral alone, not a comparison" below for exactly why, and what that limits.

| Metric | Result |
|---|---|
| Documents processed | 18/18 (one transient `404` on first attempt — a race between file upload and the immediate signed-URL fetch — resolved on a single targeted retry of that one document; not a code bug, not repeated across other documents) |
| Overall field accuracy | 98% |
| Business-critical field accuracy | 98% (identical to overall — no gap between "easy" and critical fields, a good sign) |
| Cost | $0.076 total for 18 documents |
| Avg latency | 2.6s/document |
| Line-item count match | 89% (16/18 — two documents, both by design zero-line-item cases, see below) |

**Per business-critical field:** invoice_number 100%, subtotal 100%, tax 100%, total 100%, invoice_date 94%, due_date 94%, currency 94%.

**All 3 critical-field errors, named, from `spike/report.md`:**

| Document | Difficulty | Field | Expected | Got |
|---|---|---|---|---|
| `inv_11_ambiguous_currency` | hard | currency | `CAD` | `USD` |
| `inv_13_no_due_date` | medium | due_date | `null` | `03/03/2026` |
| `inv_13_no_due_date` | medium | invoice_date | `2026-02-01` | `2026-01-02` |

**What these actually mean, not just that they happened:**

- **`inv_11` (currency):** this was the deliberately-designed test — a bare `$` symbol with only a Canadian address as context. Mistral defaulted to USD rather than inferring CAD. This is a genuine, expected-shape failure mode for *any* provider asked to infer currency from weak context, not a Mistral-specific defect — it's exactly why currency should never be trusted without a deterministic cross-check (e.g. against a known vendor's usual currency) once Phase 8 vendor matching exists.
- **`inv_13` (due_date):** more serious. The document had no explicit due date, only "Payment Terms: Net 30" as text. Mistral **computed** March 3, 2026 — Feb 1 + 30 days — instead of returning null. This is the exact risk `docs/extraction-strategy.md` flagged from the start ("does the provider correctly return null rather than computing/hallucinating a date") and it happened on the very case designed to test it. This is a real behavioral finding, not noise: **a provider will silently fabricate a plausible-looking value rather than admit absence**, which is precisely why this project's design never lets an AI-derived value bypass deterministic validation.
- **`inv_13` (invoice_date):** a month/day transposition on a US-formatted date (`02/01/2026` read as day-first instead of month-first). One data point isn't enough to conclude a systemic locale-parsing weakness, but it's a concrete, reproducible example worth remembering when Phase 6 decides how much to trust date fields without independent verification.

**A real limitation the run itself surfaced, not assumed in advance:** the schema-constrained structured-output call returned **no per-field confidence at all** — `avg confidence (correct)` and `(wrong)` are both empty in `spike/report.md`. This confirms, empirically, the gap already flagged under "On confidence scores" below: Mistral's native confidence lives at the OCR/block level, not on the structured-annotation fields this project actually needs. Phase 6/7's review-routing design cannot lean on Mistral's own per-field confidence the way the original architecture hoped — see "What this means for Phase 6" below.

## Why Mistral alone, not a comparison

The original Phase 5 plan compared Mistral against Claude (Azure was already excluded — see `docs/adr/0006-extraction-provider.md`). Claude was subsequently excluded from the real run too: the Anthropic credential in this environment was exposed during diagnosis of an unrelated connection error and, per project owner instruction, is treated as compromised and was never used to make a real call. **This is a single-provider validation, not a comparison** — there is no data here on whether Claude would have done better or worse on the same documents, and no cross-provider "one succeeded, one failed" analysis is possible because only one provider was actually run.

This is judged sufficient for the project's actual decision — which provider powers Phase 6 — because: the accuracy achieved (98% critical-field) is strong on its own terms, every failure mode found maps to a safeguard the architecture already requires regardless of provider (deterministic validation, human review, vendor matching), and the project's priority at this stage is finishing efficiently, not proving comparative superiority. If Claude (or another provider) is worth revisiting later — e.g. specifically to test whether it handles the `inv_13`-style null-vs-hallucinate case better — that's a well-scoped, cheap follow-up once a working key exists, not a blocker to Phase 6.

## What this means for Phase 6

1. **Mistral OCR is the `ExtractionProvider` implementation.**
2. **Confidence-driven review routing cannot rely on Mistral's native per-field confidence** — the empirical gap above means Phase 7/10's design needs to route to review primarily via deterministic validation failures (arithmetic mismatch, unknown vendor, duplicate) and a small set of explicit plausibility checks (e.g. flag `due_date` when the source document has no due-date text at all), not a confidence-threshold table. The original 95%/90%/70% draft bands are now moot for Mistral specifically — there's no field-level number to threshold.
3. **Currency and due-date fields need a deterministic sanity check layered on top of extraction**, given both produced a critical error in this run: currency should be cross-checked against vendor history once available (Phase 8), and due-date should never be trusted without also checking whether the source document actually contained a due-date-shaped string near it.

## What's known so far, per candidate (background, unchanged since discovery)

| Provider | Free tier | Card required | After free tier | Native confidence + provenance | Invoice-specific training |
|---|---|---|---|---|---|
| Azure Document Intelligence | 500 pages/month, ongoing | No | ~$0.01–0.05/page | Yes, both, native | Purpose-built prebuilt invoice model |
| Mistral OCR 4 | "Experiment" tier, rate-limited (~2 RPM), no page cap | No | ~$4/1,000 pages ($2 batch) | Yes at OCR/block level — **not on schema-constrained structured fields, confirmed empirically above** | General document model, not invoice-trained |
| AWS Textract | 1,000 pages/month, first 3 months only | Yes | ~$0.05–0.10/page | Yes | Purpose-built (AnalyzeExpense) |
| Google Document AI | $300 one-time credit | Yes | Tiered, comparable to Azure/AWS | Yes | Purpose-built, recently changed underlying tech (2026) — least verified |
| Claude (vision) | None | Yes | ~$0.006–0.01/invoice | No native confidence/bbox; PDF citations don't ground scanned images | None — best general semantic reasoning |
| Tesseract (local, open-source) | Free, unlimited | No | Free forever | No confidence, weak on tables | None — text only |

## On confidence scores

A provider's confidence score is a provider-internal certainty heuristic, not a calibrated statistical probability, and is not comparable across providers. A high-confidence field can still be wrong; a low-confidence field can still be correct. For this reason, financial-critical fields (total, subtotal, tax) are never trusted on confidence alone — the deterministic arithmetic check in Phase 7 runs regardless of what any confidence score says. Confidence is used to route to review, not as the sole gate on a financial fact. **For Mistral specifically, this principle isn't optional risk-hedging — it's the only option, since no field-level confidence is available at all (see "Real results" above).**

## Provenance: what's kept, what's deliberately not

Kept per field: value, confidence, page number, bounding box (where the provider supplies one), source text snippet, provider name and model version — this is what lets a reviewer see *why* the system extracted a value, next to the original document.

Deliberately not built at this scale: bounding boxes for every line-item cell (nice-to-have, not MVP), storage of full raw provider payloads beyond what a reviewer needs, or a generic "evidence" abstraction meant to support arbitrary future document types.
