# Demo script

A ~10-minute walkthrough for a portfolio/interview audience, run locally against the real Mistral API (`docker compose`, no mocking) — this is the actual system, not a scripted fake. Every `curl` below is copy-pasteable.

## Setup (once)

```bash
cp .env.example .env
# uncomment and set a real MISTRAL_API_KEY in .env before continuing —
# every step below makes a real (free-tier) extraction call.
docker compose up --build -d
docker compose run --rm app alembic upgrade head
docker compose run --rm app python -m app.seed_vendors
```

```bash
AUTH='-H "Authorization: Bearer dev-only-not-for-production"'
BASE=http://localhost:8000
```

(`dev-only-not-for-production` is `.env.example`'s documented insecure default — fine for a local demo, never for anything real; see `docs/adr/0008-api-authentication.md`.)

## 1. The golden path — extraction, deterministic validation, no human touches it

```bash
curl -s -X POST $BASE/documents \
  -H "Authorization: Bearer dev-only-not-for-production" \
  -F "file=@spike/samples/inv_01_baseline_usd.pdf" | python3 -m json.tool
```

Narrate: the response only returns once extraction *and* every deterministic check (required fields, arithmetic, vendor match, duplicate check) has already run — there's no separate "processing" step to poll. Point out `state`: if the vendor on this sample matches the seeded list and the math checks out, it's `VALIDATED` already, with zero human involvement. Grab the `id` from the response for the next steps — call it `DOC_ID`.

```bash
curl -s $BASE/documents/$DOC_ID/extraction -H "Authorization: Bearer dev-only-not-for-production" | python3 -m json.tool
```

Point out `fields` — every extracted value carries whatever provenance Mistral supplied (confidence, page, source text), stored even for fields that didn't need it, per `docs/extraction-strategy.md`.

## 2. Duplicate detection — deterministic, before it ever costs money twice

```bash
curl -s -X POST $BASE/documents \
  -H "Authorization: Bearer dev-only-not-for-production" \
  -F "file=@spike/samples/inv_01_baseline_usd.pdf" | python3 -m json.tool
```

Same file, byte-for-byte. Narrate: this second upload never called Mistral at all — `state` comes back `DUPLICATE` immediately, caught by content hash before extraction runs (`app/duplicate_detection.py`). This is deliberately guaranteed to work regardless of what Mistral actually extracted from the file, since the hash check doesn't depend on extracted content.

## 3. Human review — a document that needs a person

The reliable way to force this deterministically, without needing to know in advance what a specific sample's vendor name is: upload any sample **before** running `seed_vendors`, or use a vendor name you know isn't seeded. If everything's already seeded, use a different sample:

```bash
curl -s -X POST $BASE/documents \
  -H "Authorization: Bearer dev-only-not-for-production" \
  -F "file=@spike/samples/inv_11_ambiguous_currency.pdf" | python3 -m json.tool
```

If `state` comes back `NEEDS_REVIEW`, walk the queue:

```bash
curl -s $BASE/review -H "Authorization: Bearer dev-only-not-for-production" | python3 -m json.tool
```

Narrate `failed_rules` — the specific reason a person needs to look at this, not a generic flag. Then correct it:

```bash
curl -s -X POST $BASE/review/<id>/correct \
  -H "Authorization: Bearer dev-only-not-for-production" \
  -H "Content-Type: application/json" \
  -d '{"reviewer": "demo@example.com", "corrections": [{"field_name": "vendor_name", "corrected_value": "Acme Corp"}]}' \
  | python3 -m json.tool
```

Point out: this moves straight to `VALIDATED`, and `review_events` (visible via the DB, not yet a dedicated endpoint) has a permanent record of exactly what changed and who changed it.

## 4. Approval routing — forcing it deterministically

The default `APPROVAL_THRESHOLD_AMOUNT` is $1000; most synthetic sample invoices are well under that. Rather than guess which sample happens to exceed it, lower the threshold just for the demo:

```bash
docker compose run --rm -e APPROVAL_THRESHOLD_AMOUNT=1.00 app python -c "
from app.config import get_settings
print(get_settings().approval_threshold_amount)
"
```

Then restart the app container with that same override (`docker compose up -d --force-recreate -e ...` or set it in `.env` temporarily) and upload any sample — now anything at all requires approval:

```bash
curl -s $BASE/approvals -H "Authorization: Bearer dev-only-not-for-production" | python3 -m json.tool

curl -s -X POST $BASE/approvals/<id>/approve \
  -H "Authorization: Bearer dev-only-not-for-production" \
  -H "Content-Type: application/json" \
  -d '{"approver": "demo@example.com"}' | python3 -m json.tool
```

Narrate: the document's `state` stays `VALIDATED` — approval is metadata, not a transition (see `docs/state-machine.md`'s explanation of why). Restore the real threshold before continuing.

## 5. The downstream action — a real ledger entry, idempotent

```bash
curl -s -X POST $BASE/documents/<id>/action -H "Authorization: Bearer dev-only-not-for-production" | python3 -m json.tool
```

Point out `accounting_action.status: CONFIRMED` and `document.state: COMPLETED`. Run the exact same `curl` again — same result, no second ledger entry, no error. That's the idempotency check (`accounting_actions`, `docs/reliability.md` scenario 3), not luck.

## 6. What it all added up to

```bash
curl -s $BASE/dashboard -H "Authorization: Bearer dev-only-not-for-production" | python3 -m json.tool
```

Narrate the split explicitly: `straight_through_rate`, `review_rate`, `correction_rate`, and `average_processing_time_seconds` are all genuinely measured from timestamps just generated by this demo. `estimated_minutes_saved` is the one number that's a stated assumption, not a measurement — say so out loud, don't let it pass as a real number.

## If asked "what happens when something breaks"

Not staged live (it needs a hand-inserted stuck DB row, not a real crash — see `docs/testing-strategy.md` for why that's the deliberate approach over actually killing a process), but worth describing: `app/worker.py` resumes a document left stuck mid-flight from exactly where it stopped, dead-lettering it only after bounded retries are genuinely exhausted (`docs/reliability.md`). `tests/test_worker.py` is the receipts for that claim, not just a description of intent.
