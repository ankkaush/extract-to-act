# Phase 5 — extraction provider spike

Standalone evaluation harness, deliberately **not** part of the FastAPI
application (no import from `app`, no provider SDKs added to the main
`pyproject.toml` dependencies — see below). Its only job is producing
evidence for the extraction-provider decision in
[`docs/extraction-strategy.md`](../docs/extraction-strategy.md) and
[`docs/adr/0006-extraction-provider.md`](../docs/adr/0006-extraction-provider.md).

## Status

The harness (provider wrappers, orchestrator, evaluator) is written and
its scoring logic is verified with synthetic data — see the commit that
introduced this directory. **It has not yet been run against real
provider accounts or real sample invoices**, because this environment has
no Azure / Mistral / Anthropic credentials and the sample-invoice
sourcing decision is still open (see `PLAN.md` Phase 5 and the original
architecture proposal's open decisions). The provider wrapper code is
written against each SDK's documented shape but should be treated as
*also under test* on the first real run — see the "not yet run" note in
each `spike/providers/*.py` file.

## What you need to actually run this

1. **Credentials**, set as real environment variables (not committed —
   this reads from `os.environ` directly, not `.env`, to keep this spike
   fully separate from the application's config):
   - `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT` / `AZURE_DOCUMENT_INTELLIGENCE_KEY` — [free tier](https://azure.microsoft.com/en-us/products/ai-services/ai-document-intelligence), 500 pages/month ongoing, no card.
   - `MISTRAL_API_KEY` — [free "Experiment" tier](https://mistral.ai/), no card, rate-limited (~2 RPM — this spike runs slowly on purpose).
   - `ANTHROPIC_API_KEY` — no free tier; this is the one provider in the spike that costs real money (small — see `docs/cost-strategy.md`).
2. **Sample invoices** in `spike/samples/` (gitignored — see below). 15–20 documents, varied: clean digital PDF, at least one scanned/lower-quality one, multi-column layout, at least one non-USD currency.
3. **Ground truth** in `spike/ground_truth/<doc_id>.json`, one file per sample, hand-verified:
   ```json
   {
     "fields": {
       "vendor_name": "Acme Corp",
       "invoice_number": "INV-1042",
       "invoice_date": "2026-03-01",
       "due_date": "2026-03-31",
       "currency": "USD",
       "subtotal": 1000.00,
       "tax": 80.00,
       "total": 1080.00
     },
     "line_items": [
       {"description": "Widget", "quantity": 10, "unit_price": 100.00, "line_total": 1000.00}
     ]
   }
   ```
   `<doc_id>` must match the sample file's name without extension (e.g. `spike/samples/invoice_01.pdf` → `spike/ground_truth/invoice_01.json`).

## Running it

Install the spike-only dependencies (kept separate from the application's
own dependencies — see "Why not part of the app" below):

```bash
pip install -e ".[spike]"
```

Run every configured provider against every sample:

```bash
python -m spike.run_spike --budget-cap 2.00
```

Providers without credentials set are skipped automatically, not treated
as an error. `--budget-cap` (default $2.00) aborts the run the moment
estimated real spend would exceed it — a safety net against a bug
causing runaway spend, not the expected cost (Azure and Mistral should
both run at $0 on their free tiers for a spike this size).

Score the results against ground truth and generate the report:

```bash
python -m spike.evaluate
```

Writes `spike/report.md` — a table of per-provider accuracy, confidence
calibration (does a "correct" answer actually carry higher confidence
than a "wrong" one?), latency, and cost. This report is what
`docs/extraction-strategy.md`'s final recommendation should cite.

## Why not part of the application

Three reasons this stays outside `app/`:

1. **Cost isolation.** Nothing in the application should be able to
   accidentally trigger a real, billed provider call. Keeping the spike
   entirely separate — its own directory, its own credential-reading
   convention, its own dependency group — makes that structurally true,
   not just a matter of discipline.
2. **Dependency hygiene.** The Azure/Mistral/Anthropic SDKs have no
   business being in the production Docker image before Phase 6 actually
   picks a provider — they'd be dead weight in every deployment until
   then.
3. **Disposability.** This code's job is to produce a decision and a
   written report, not to be maintained long-term. Once Phase 6 picks a
   provider and builds the real `ExtractionProvider` adapter, this
   directory's code is done, not extended.

## What's gitignored and why

`spike/samples/` (the actual invoice files) and `spike/results/` (raw
provider responses, which embed the document's content) are excluded —
see `.gitignore`. `spike/ground_truth/` (small, hand-typed expected
values) and `spike/report.md` (the aggregated, non-sensitive comparison)
are committed once real results exist, since they're the actual evidence
this phase exists to produce.
