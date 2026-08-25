# Extract to Act

An AI-assisted invoice-to-accounts-payable automation system: it takes an arbitrary invoice document, turns it into a structured record it can actually trust, and carries that record through a real business decision — validate, route to a human when warranted, approve, and post to a downstream ledger — with every step auditable and recoverable.

## Why this exists

Invoice processing is a mature automation domain — deterministic three-way matching already handles the majority of invoice volume in well-run AP departments without any AI involved. This project isn't trying to reinvent that. It's a deliberate demonstration of the part that's still genuinely hard: knowing when an AI extraction is trustworthy, what to do when it isn't, and never letting a probabilistic step make a deterministic financial decision on its own.

See [`docs/problem.md`](docs/problem.md) for the full business-problem writeup, including why this framing was chosen over alternatives like receipts, purchase orders, or claims.

## Status

**Phase 16 of 19 — Observability & Business Metrics — complete.** An uploaded document is extracted (Mistral OCR), then deterministically validated — required fields, arithmetic consistency, vendor matching, and duplicate detection — before landing in `VALIDATED`, `NEEDS_REVIEW`, or `DUPLICATE`, all in one synchronous request. A `NEEDS_REVIEW` document goes to a real queue (`GET /review`); a `VALIDATED` document at or above a configured dollar threshold needs a person's sign-off first (`GET /approvals`). Once eligible, `POST /documents/{id}/action` posts a real payable record to a mock AP ledger and moves the document to `COMPLETED`, with bounded retry-with-backoff and crash recovery behind every step (`app/retry.py`, `app/worker.py`), `docs/security.md`'s full control set implemented and verified (Phase 14), and the whole pipeline proven end to end against the live provider (Phase 15). `GET /dashboard` now shows what any of that actually accomplished: a straight-through rate, a review rate, a correction rate, and an average processing time, every one of them computed live from `state_history` timestamps, not sampled or estimated — plus exactly one number that *is* an estimate ("time saved"), always returned next to the assumption it's built from, never dressed up as measured. Nothing looks at AI confidence to decide any of this; see [`app/validation.py`](app/validation.py), [`app/vendor_matching.py`](app/vendor_matching.py), [`app/duplicate_detection.py`](app/duplicate_detection.py), [`app/review.py`](app/review.py), [`app/approval.py`](app/approval.py), [`app/accounting.py`](app/accounting.py), [`app/retry.py`](app/retry.py), [`app/worker.py`](app/worker.py), and [`app/metrics.py`](app/metrics.py). Nothing schedules the worker to run continuously yet, and the application isn't deployed anywhere — that's Phase 17, the last one. See [`PLAN.md`](PLAN.md) for the full phase roadmap and current progress.

## How the system works, briefly

An invoice arrives, gets read and structured, and is checked deterministically — does the math add up, have we seen this invoice before, do we recognize this vendor. If everything checks out with high confidence, it moves forward untouched. If anything is uncertain, it's queued for a person to review, side by side with the original document. Once validated and (if needed) approved, it becomes a real record in a downstream accounting system, with a full audit trail behind it.

Full plain-English workflow: [`docs/workflow.md`](docs/workflow.md).

## Documentation map

| Document | Answers |
|---|---|
| [`docs/problem.md`](docs/problem.md) | What business problem is this, and why this use case |
| [`docs/workflow.md`](docs/workflow.md) | The end-to-end process in plain English |
| [`docs/architecture.md`](docs/architecture.md) | Components, boundaries, how they interact |
| [`docs/adr/`](docs/adr/) | Why each consequential technology/architecture decision was made |
| [`docs/data-model.md`](docs/data-model.md) | Entities, relationships, why each table exists |
| [`docs/state-machine.md`](docs/state-machine.md) | Every document state, transition, and crash-recovery behavior |
| [`docs/api.md`](docs/api.md) | The eventual API surface |
| [`docs/extraction-strategy.md`](docs/extraction-strategy.md) | How the extraction-provider decision will be made and validated |
| [`docs/security.md`](docs/security.md) | Threats considered and the control for each |
| [`docs/reliability.md`](docs/reliability.md) | Failure modes and how each is handled |
| [`docs/testing-strategy.md`](docs/testing-strategy.md) | The four test tiers, and when a real paid API call is ever allowed |
| [`docs/cost-strategy.md`](docs/cost-strategy.md) | Where money can be spent and how it's kept near zero |
| [`docs/deployment.md`](docs/deployment.md) | How and where this runs |

## Tech stack (planned)

Python, FastAPI, PostgreSQL, SQLAlchemy + Alembic, Docker, a scheduled polling worker (no message queue), deployed on Render. Reasoning for each in [`docs/adr/`](docs/adr/). Extraction provider: Mistral OCR — see [`docs/adr/0006-extraction-provider.md`](docs/adr/0006-extraction-provider.md).

## Local setup

```bash
cp .env.example .env
docker compose up --build -d
docker compose run --rm app alembic upgrade head
docker compose run --rm app python -m app.seed_vendors
```

The app is then available at `http://localhost:8000`. Uploading a document (auth required — the unmodified `.env.example` uses the insecure dev-only default key, `dev-only-not-for-production`; see `docs/adr/0008-api-authentication.md`):

```bash
curl -X POST http://localhost:8000/documents \
  -H "Authorization: Bearer dev-only-not-for-production" \
  -F "file=@some-invoice.pdf"
```

Only PDF/PNG/JPEG/TIFF content is accepted (checked by file content, not extension), up to `MAX_UPLOAD_SIZE_BYTES`. **This call hits the real Mistral API** if `MISTRAL_API_KEY` is set in `.env` — extraction, deterministic validation, and vendor matching all run synchronously as part of the upload (see `docs/api.md`), so the response only comes back once the document is fully `VALIDATED` or `NEEDS_REVIEW` (or `FAILED`, if extraction itself failed). A vendor not in the seeded list (`python -m app.seed_vendors`) routes to `NEEDS_REVIEW`, same as a missing field. See `PLAN.md` for what's built so far.

## Data handling

Every document this project has ever processed — in the Phase 5 provider evaluation and in every test fixture — is synthetic or clearly fabricated, never a real vendor's real invoice (see `docs/security.md`). That matters for what follows.

This project's Mistral usage is on the free/experiment API tier (see `docs/testing-strategy.md`'s cost breakdown — the Phase 5 spike ran on free tiers by design). Per [Mistral's own documentation](https://help.mistral.ai/en/articles/156194-does-mistral-ai-exploit-users-data-to-train-its-models) and [terms](https://legal.mistral.ai/terms/data-processing-addendum), free/experiment-tier API usage **can be used for model training by default**, unlike paid API plans (which exclude training by default, with a 30-day abuse-monitoring retention window). Anyone extending this project to process real invoice data should switch to a paid Mistral plan (or opt out in the Admin Console's Privacy settings) first — this repository never has, because every document it touches is synthetic and there is nothing sensitive at stake in it being used for training.

### Running tests / lint without Docker

```bash
pip install -e ".[dev]"
pytest        # Tier 1 + Tier 2 only, no real API calls — see docs/testing-strategy.md
ruff check .
```

Tier 4 (`tests/test_e2e_real_provider.py`) hits the real Mistral API and is excluded by default. Run it deliberately, rarely, and only with a real `MISTRAL_API_KEY` set: `pytest -m real_api tests/test_e2e_real_provider.py`.

### Pre-commit hooks (lint + secret scanning)

```bash
pre-commit install
```

## Secrets

This is a public repository. No credentials of any kind are ever committed. See [`.env.example`](.env.example) for the full list of configuration variables the application will eventually need, and [`docs/security.md`](docs/security.md) for the full repository-safety approach.
